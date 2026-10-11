"""Run a teacher turn, persist it, and build the playback events."""

import logging
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.exceptions import ForbiddenError, NotFoundError, RateLimitError
from src.core.rate_limit import limiter
from src.core.security import AuthContext, require_school
from src.modules.conversations.schemas import ConversationCreate
from src.modules.conversations.service import ConversationService
from src.modules.teacher.access import linked_ids, public_plan, role_can_write
from src.modules.teacher.graph import run_teacher_turn
from src.modules.teacher.images import search_educational_image
from src.modules.teacher.protocol import PROTOCOL_VERSION, ensure_image_url
from src.modules.teacher.records import ActionRecord, MessageRecord, PageRecord, ProgressRecord, SessionRecord
from src.modules.teacher.repository import SqlTeacherStore
from src.modules.teacher.safety import normalise_grade_band
from src.modules.teacher.schemas import ReplayAction, SessionDetail, SessionSummary, TurnResponse
from src.modules.teacher.timeline import build_events, rescale_timing
from src.modules.teacher.voice import get_voice
from src.providers.llm import get_llm
from src.shared.enums import MessageRole
from src.shared.utils import utcnow

logger = logging.getLogger("sybeez.ai.teacher")


def _as_uuid(value: object) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return uuid4()


def bind_pages(actions: list[dict], current_page_id: str) -> tuple[list[dict], list[tuple[str, str]]]:
    """Give every action a real page id. new_page allocates the page it opens."""
    alias = {"current": current_page_id}
    active = current_page_id
    created: list[tuple[str, str]] = []
    rewritten: list[dict] = []
    for raw in actions:
        action = dict(raw)
        if action.get("type") == "new_page":
            new_id = str(uuid4())
            requested = str(action.get("page_id") or "")
            if requested:
                alias[requested] = new_id
            alias["current"] = new_id
            action["page_id"] = new_id
            action["id"] = str(_as_uuid(action.get("id")))
            active = new_id
            created.append((new_id, str(action.get("title") or "Board")[:120]))
            rewritten.append(action)
            continue
        pid = str(action.get("page_id") or "current")
        mapped = alias.get(pid, active)
        try:
            UUID(mapped)
        except ValueError:
            mapped = active
        action["page_id"] = mapped
        action["id"] = str(_as_uuid(action.get("id")))
        rewritten.append(action)
    return rewritten, created


class TeacherService:
    def __init__(self, db: AsyncSession | None = None, *, store=None, llm=None, voice=None, context=None, images=None):
        if store is None:
            if db is None:
                raise ValueError("db or store is required")
            store = SqlTeacherStore(db)
        self.db = db
        self.store = store
        self.llm = llm if llm is not None else get_llm()
        self.voice = voice if voice is not None else get_voice()
        if context is None:
            from src.modules.context.service import ContextService

            context = ContextService()
        self.context = context
        self.images = images if images is not None else search_educational_image
        self.conversations = ConversationService(db) if db is not None else None

    async def start(self, auth: AuthContext, body, bearer: str | None) -> TurnResponse:
        self._require_student(auth)
        await self._limit(auth)
        learning = await self.context.for_user(auth, bearer_token=bearer, subject_id=body.subject_id)
        now = utcnow()
        page_id = uuid4()
        subject_id = body.subject_id
        if subject_id is None and learning.current_learning is not None:
            subject_id = learning.current_learning.subject_id
        record = SessionRecord(
            id=uuid4(),
            school_id=require_school(auth),
            student_user_id=auth.user_id,
            student_id=learning.student.id,
            guardian_user_ids=linked_ids(learning.guardians),
            teacher_user_ids=linked_ids(learning.teachers),
            subject_id=subject_id,
            class_id=learning.student.class_id,
            conversation_id=None,
            title=(body.title or "AI Teacher")[:255],
            topic="",
            status="active",
            phase="understand",
            grade_band=normalise_grade_band(learning.grade_band),
            step_index=0,
            attempt=0,
            turn_index=0,
            awaiting_check=False,
            expected_answer="",
            check_prompt="",
            check_kind="ask",
            pages=[PageRecord(id=page_id, page_index=0, title="Board")],
            created_at=now,
            updated_at=now,
        )
        return await self._turn(auth, record, body.message, learning, is_new=True)

    async def send(self, auth: AuthContext, session_id: UUID, message: str, bearer: str | None) -> TurnResponse:
        self._require_student(auth)
        await self._limit(auth)
        record = await self._owned(auth, session_id)
        learning = await self.context.for_user(auth, bearer_token=bearer, subject_id=record.subject_id)
        record.guardian_user_ids = linked_ids(learning.guardians)
        record.teacher_user_ids = linked_ids(learning.teachers)
        record.grade_band = normalise_grade_band(learning.grade_band)
        return await self._turn(auth, record, message, learning, is_new=False)

    async def stream(self, auth: AuthContext, session_id: UUID, message: str, bearer: str | None, *, pace: bool = False):
        from src.modules.teacher.timeline import pace_events

        turn = await self.send(auth, session_id, message, bearer)
        async for event in pace_events(turn.events, pace=pace):
            yield event

    async def list_sessions(self, auth: AuthContext) -> list[SessionSummary]:
        require_school(auth)
        rows = await self.store.list(auth)
        return [
            SessionSummary(
                id=row.id,
                student_id=row.student_id,
                title=row.title,
                topic=row.topic,
                status=row.status,
                phase=row.phase,
                step_index=row.step_index,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def get_session(self, auth: AuthContext, session_id: UUID) -> SessionDetail:
        require_school(auth)
        record = await self.store.get(auth, session_id)
        if record is None:
            raise NotFoundError("Session not found")
        return self.to_detail(auth, record)

    async def resume(self, auth: AuthContext, session_id: UUID, bearer: str | None) -> SessionDetail:
        self._require_student(auth)
        record = await self._owned(auth, session_id)
        learning = await self.context.for_user(auth, bearer_token=bearer, subject_id=record.subject_id)
        record.guardian_user_ids = linked_ids(learning.guardians)
        record.teacher_user_ids = linked_ids(learning.teachers)
        if record.status in {"paused", "completed"}:
            record.status = "active"
        record.updated_at = utcnow()
        await self.store.save(record)
        await self._commit()
        return self.to_detail(auth, record)

    def to_detail(self, auth: AuthContext, record: SessionRecord) -> SessionDetail:
        return SessionDetail(
            id=record.id,
            student_id=record.student_id,
            title=record.title,
            topic=record.topic,
            status=record.status,
            phase=record.phase,
            grade_band=record.grade_band,
            step_index=record.step_index,
            protocol=PROTOCOL_VERSION,
            awaiting_check=record.awaiting_check,
            check_prompt=record.check_prompt or None,
            check_kind=record.check_kind,
            check_choices=list(record.check_choices),
            plan=public_plan(record.plan, role=auth.role),
            pages=[{"id": str(page.id), "page_index": page.page_index, "title": page.title} for page in record.pages],
            actions=[
                ReplayAction(seq=action.seq, turn_index=action.turn_index, at_ms=action.at_ms, action=action.action)
                for action in sorted(record.actions, key=lambda item: item.seq)
            ],
            messages=[
                {
                    "id": str(message.id),
                    "role": message.role,
                    "content": message.content,
                    "turn_index": message.turn_index,
                    "created_at": message.created_at,
                }
                for message in record.messages
            ],
            progress=[
                {"concept": item.concept, "status": item.status, "score": item.score}
                for item in record.progress
            ],
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    async def _turn(self, auth: AuthContext, record: SessionRecord, message: str, learning, *, is_new: bool) -> TurnResponse:
        now = utcnow()
        record.updated_at = now
        user_message = MessageRecord(id=uuid4(), role="user", content=message, turn_index=None, created_at=now)
        record.messages.append(user_message)
        await self._mirror(auth, record, user_message)

        finished = record.phase == "summarise" or record.status == "completed"
        state = {
            "student_message": message,
            "grade_band": record.grade_band,
            "context_block": learning.as_prompt_block(),
            "page_id": str(record.pages[-1].id) if record.pages else "current",
            "needs_new_page": bool(record.actions) or finished,
            "has_plan": bool(record.plan and record.plan.get("steps")) and not finished,
            "awaiting_check": bool(record.awaiting_check) and not finished,
            "step_index": record.step_index,
            "attempt": record.attempt,
            "plan": record.plan or {},
            "expected_answer": "" if finished else record.expected_answer,
            "phase": "understand" if finished else record.phase,
            "status": "active" if finished else record.status,
            "actions": [],
            "trace": [],
            "progress_updates": [],
            "check_choices": [],
        }
        result = await run_teacher_turn(state, self.llm)
        chat = result.get("chat_text") or ""
        actions = await self._prepare_actions(record, list(result.get("actions") or []))
        voice_event = await self._voice_for(actions)
        record.phase = result.get("phase") or record.phase
        record.status = result.get("status") or record.status
        record.step_index = int(result.get("step_index") or 0)
        record.attempt = int(result.get("attempt") or 0)
        record.awaiting_check = bool(result.get("awaiting_check"))
        record.expected_answer = result.get("expected_answer") or ""
        record.check_prompt = result.get("check_prompt") or ""
        record.check_kind = result.get("check_kind") or record.check_kind
        record.check_choices = list(result.get("check_choices") or [])
        if result.get("plan"):
            record.plan = result["plan"]
            record.plan_version += 1
            record.topic = str(result["plan"].get("topic") or record.topic)[:160]
            if record.topic:
                record.title = record.topic[:255]
        trace = result.get("trace") or []
        if trace:
            record.internal_notes = "\n".join(str(line) for line in trace)[:8000]
        self._apply_progress(record, result.get("progress_updates") or [])
        record.turn_index += 1
        seq = len(record.actions)
        for action in actions:
            seq += 1
            record.actions.append(
                ActionRecord(
                    id=UUID(action["id"]),
                    page_id=UUID(action["page_id"]),
                    seq=seq,
                    turn_index=record.turn_index,
                    at_ms=int(action.get("at_ms") or 0),
                    action=action,
                )
            )
        assistant = MessageRecord(
            id=uuid4(),
            role="assistant",
            content=chat,
            turn_index=record.turn_index,
            created_at=utcnow(),
        )
        record.messages.append(assistant)
        await self._mirror(auth, record, assistant)
        if is_new:
            await self.store.create(record)
        else:
            await self.store.save(record)
        await self._commit()
        refused = record.phase == "refuse"
        redirected = record.phase == "redirect"
        events = build_events(
            session_id=str(record.id),
            phase=record.phase,
            step_index=record.step_index,
            chat=chat,
            actions=actions,
            check_prompt=record.check_prompt if record.awaiting_check else "",
            check_kind=record.check_kind,
            choices=record.check_choices if record.awaiting_check else [],
            message_id=str(assistant.id),
            voice=voice_event,
            refused=refused,
            redirected=redirected,
        )
        return TurnResponse(
            session_id=record.id,
            message_id=assistant.id,
            phase=record.phase,
            status=record.status,
            step_index=record.step_index,
            chat_text=chat,
            actions=actions,
            events=events,
            awaiting_check=record.awaiting_check,
            check_prompt=record.check_prompt or None,
            refused=refused,
            redirected=redirected,
            protocol=PROTOCOL_VERSION,
        )

    async def _prepare_actions(self, record: SessionRecord, actions: list[dict]) -> list[dict]:
        current = str(record.pages[-1].id) if record.pages else str(uuid4())
        if not record.pages:
            record.pages.append(PageRecord(id=UUID(current), page_index=0, title="Board"))
        bound, created = bind_pages(actions, current)
        for page_id, title in created:
            record.pages.append(PageRecord(id=UUID(page_id), page_index=len(record.pages), title=title))
        for action in bound:
            if action.get("type") != "place_image" or action.get("url"):
                continue
            try:
                found = await self.images(action.get("query") or "")
            except Exception:
                logger.warning("image lookup failed")
                found = None
            if isinstance(found, str):
                try:
                    action["url"] = ensure_image_url(found)
                except ValueError:
                    action["url"] = None
        return bound

    async def _voice_for(self, actions: list[dict]) -> dict | None:
        narration = next((action for action in actions if action.get("type") == "narration"), None)
        if narration is None or not self.voice.available():
            return None
        clip = await self.voice.synthesize(narration.get("text") or "")
        if clip is None:
            return None
        rescale_timing(actions, clip.duration_ms, clip.provider)
        return clip.as_event()

    def _apply_progress(self, record: SessionRecord, updates: list[dict]) -> None:
        for update in updates:
            concept = str(update.get("concept") or "step")[:160]
            found = next((item for item in record.progress if item.concept == concept), None)
            if found is None:
                record.progress.append(
                    ProgressRecord(
                        id=uuid4(),
                        concept=concept,
                        status=str(update.get("status") or "learning"),
                        score=update.get("score"),
                        notes=update.get("notes"),
                    )
                )
            else:
                found.status = str(update.get("status") or found.status)
                found.score = update.get("score")
                found.notes = update.get("notes")

    async def _mirror(self, auth: AuthContext, record: SessionRecord, message: MessageRecord) -> None:
        if self.conversations is None:
            return
        if record.conversation_id is None:
            conv = await self.conversations.create(
                auth,
                ConversationCreate(
                    subject_id=record.subject_id,
                    class_id=record.class_id,
                    title=record.title,
                    mode="board",
                ),
                student_id=record.student_id,
            )
            record.conversation_id = conv.id
        role = MessageRole.USER if message.role == "user" else MessageRole.ASSISTANT
        await self.conversations.append(
            auth=auth,
            conversation_id=record.conversation_id,
            role=role,
            content=message.content,
        )

    async def _owned(self, auth: AuthContext, session_id: UUID) -> SessionRecord:
        record = await self.store.get(auth, session_id)
        if record is None or not role_can_write(auth, record):
            raise NotFoundError("Session not found")
        return record

    def _require_student(self, auth: AuthContext) -> None:
        require_school(auth)
        if auth.role != "STUDENT":
            raise ForbiddenError("Only a student can start or continue a lesson")

    async def _limit(self, auth: AuthContext) -> None:
        cap = get_settings().teacher_rate_limit_per_minute
        if not await limiter.allow(f"teacher:{auth.user_id}", limit=cap):
            raise RateLimitError("Too many lesson requests")

    async def _commit(self) -> None:
        if self.db is not None:
            await self.db.commit()
