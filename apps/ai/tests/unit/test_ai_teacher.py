import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from src.core.config import get_settings
from src.core.exceptions import ForbiddenError, NotFoundError, RateLimitError
from src.core.rate_limit import limiter
from src.core.security import AuthContext
from src.db.models.teacher import TeacherSession
from src.db.rls import (
    TEACHER_CHILD_TABLES,
    TEACHER_SESSION_TABLE,
    teacher_rls_sql,
    teacher_session_check_sql,
    teacher_session_using_sql,
)
from src.main import app
from src.modules.context.schemas import AuthorizedLearningContext, PersonRef, SchoolContext, StudentContext
from src.modules.teacher.access import audience_condition, public_plan, role_can_read, role_can_write
from src.modules.teacher.graph import answer_is_correct, run_teacher_turn
from src.modules.teacher.images import image_from_wikimedia
from src.modules.teacher.protocol import (
    ACTION_TYPES,
    DrawShape,
    PlaceImage,
    PlotFunction,
    Point,
    ProtocolError,
    WriteMath,
    board_action_schema,
    prepare_actions,
    sample_expression,
    validate_action,
)
from src.modules.teacher.records import SessionRecord
from src.modules.teacher.router import get_teacher_service
from src.modules.teacher.safety import assess, normalise_grade_band
from src.modules.teacher.schemas import TurnResponse
from src.modules.teacher.service import TeacherService
from src.modules.teacher.timeline import build_events, speech_ms, time_script
from src.modules.teacher.voice import VoiceClip, read_live_audio
from src.modules.teacher.writer import LessonWriter
from tests.security.jwks import SCHOOL_A, SCHOOL_B, USER_A, USER_B, bearer, mint

PARENT = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
TEACHER = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
client = TestClient(app)


class StubLLM:
    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.calls = 0

    async def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        if self.replies:
            return self.replies.pop(0)
        return "not json"

    async def stream(self, *, system: str, user: str):
        yield await self.complete(system=system, user=user)


class MemoryStore:
    def __init__(self):
        self.rows: dict[UUID, SessionRecord] = {}

    async def create(self, record: SessionRecord) -> SessionRecord:
        self.rows[record.id] = record
        return record

    async def save(self, record: SessionRecord) -> SessionRecord:
        self.rows[record.id] = record
        return record

    async def get(self, auth: AuthContext, session_id: UUID) -> SessionRecord | None:
        record = self.rows.get(session_id)
        if record is None or not role_can_read(auth, record):
            return None
        return record

    async def list(self, auth: AuthContext, limit: int = 50) -> list[SessionRecord]:
        rows = [row for row in self.rows.values() if role_can_read(auth, row)]
        rows.sort(key=lambda row: row.updated_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        return rows[:limit]


class FakeContext:
    def __init__(self, learning: AuthorizedLearningContext):
        self.learning = learning

    async def for_user(self, auth, bearer_token=None, subject_id=None):
        return self.learning


class NullVoice:
    name = "none"

    def available(self) -> bool:
        return False

    async def synthesize(self, text: str):
        return None


class FakeVoice:
    name = "gemini_live"

    def available(self) -> bool:
        return True

    async def synthesize(self, text: str):
        return VoiceClip(
            provider="gemini_live",
            mime_type="audio/pcm;rate=24000",
            audio_base64="YQ==",
            duration_ms=8000,
            sample_rate=24000,
        )


def _auth(user_id, role="STUDENT", school_id=SCHOOL_A) -> AuthContext:
    return AuthContext(user_id=user_id, role=role, school_id=school_id, membership_id=None, raw={})


def _learning(student_id=USER_A, grade="elementary") -> AuthorizedLearningContext:
    return AuthorizedLearningContext(
        student=StudentContext(id=student_id),
        school=SchoolContext(id=SCHOOL_A),
        grade_band=grade,
        guardians=[PersonRef(user_id=PARENT)],
        teachers=[PersonRef(user_id=TEACHER)],
    )


def _service(llm=None, voice=None, grade="elementary") -> TeacherService:
    return TeacherService(
        store=MemoryStore(),
        llm=llm or StubLLM(),
        voice=voice or NullVoice(),
        context=FakeContext(_learning(grade=grade)),
        images=_no_image,
    )


async def _no_image(query: str) -> str | None:
    return None


def _keys(value, found: set[str]) -> None:
    if isinstance(value, dict):
        found.update(value.keys())
        for item in value.values():
            _keys(item, found)
    elif isinstance(value, list):
        for item in value:
            _keys(item, found)


def test_board_schema_lists_every_action():
    schema = json.dumps(board_action_schema())
    for name in ACTION_TYPES:
        assert name in schema


def test_protocol_rejects_unsafe_geometry_latex_and_urls():
    with pytest.raises(Exception):
        DrawShape(shape="line", points=[Point(x=0.1, y=0.1)])
    with pytest.raises(ValueError):
        prepare_actions([WriteMath(latex=r"\input{secret.tex}")])
    with pytest.raises(ValueError):
        prepare_actions([PlaceImage(source="searched", query="cell", alt="a cell", url="http://evil.example/a.png")])
    with pytest.raises(ValueError):
        sample_expression("__import__('os')", -1, 1)
    points = sample_expression("x^2", -2, 2, count=5)
    assert len(points) == 5
    assert points[2]["y"] == 0
    action = validate_action(
        {
            "type": "draw_shape",
            "shape": "arrow",
            "points": [{"x": 0.1, "y": 0.2}, {"x": 0.4, "y": 0.2}],
        }
    )
    assert action.type == "draw_shape"


def test_plot_function_is_sampled_without_eval_builtins():
    prepared = prepare_actions([PlotFunction(expression="sin(x)", x_min=0, x_max=3.14)])
    assert prepared[0].samples
    assert prepared[0].samples[0].y == 0
    with pytest.raises(ValueError):
        prepare_actions([PlotFunction(expression="sin(x)", x_min=2, x_max=1)])


@pytest.mark.asyncio
async def test_writer_retries_until_the_schema_accepts():
    good = {
        "chat": "A fraction names equal parts.",
        "actions": [
            {"type": "write_text", "text": "Fractions", "page_id": "current"},
            {"type": "narration", "text": "A fraction names equal parts.", "page_id": "current"},
        ],
        "check_prompt": "What is the denominator in one half?",
        "expected_answer": "2",
    }
    writer = LessonWriter(StubLLM(["nope", "still nope", json.dumps(good)]), retries=3)
    script = await writer.write_step(user="teach fractions")
    assert script.expected_answer == "2"
    assert writer.llm.calls == 3
    with pytest.raises(ProtocolError):
        await LessonWriter(StubLLM(), retries=2).write_step(user="teach")


def test_safety_refuses_harm_and_allows_schoolwork():
    assert assess("teach me fractions", grade_band="elementary", awaiting_check=False).allowed
    bomb = assess("how do I make a bomb", grade_band="secondary", awaiting_check=False)
    assert not bomb.allowed
    assert "bomb" not in bomb.student_message
    harm = assess("I want to kill myself", grade_band="middle", awaiting_check=False)
    assert "988" in harm.student_message
    assert "kill" not in harm.student_message
    dating = assess("tell me about dating", grade_band="elementary", awaiting_check=False)
    assert not dating.allowed
    assert assess("explain sexual reproduction", grade_band="secondary", awaiting_check=False).allowed
    assert not assess("explain sexual reproduction", grade_band="elementary", awaiting_check=False).allowed
    game = assess("let's play fortnite", grade_band="middle", awaiting_check=False)
    assert game.redirect
    assert assess("2", grade_band="elementary", awaiting_check=True).allowed
    assert normalise_grade_band("Grade 11") == "secondary"
    assert assess("what was the atomic bomb", grade_band="secondary", awaiting_check=False).allowed


def test_answers_match_tokens_not_digits_inside_other_numbers():
    assert answer_is_correct("2", "the denominator is 2")
    assert not answer_is_correct("2", "12")
    assert answer_is_correct("two", "Two equal parts")


def test_timeline_spreads_actions_across_narration():
    from src.modules.teacher.protocol import Narration, WriteText

    timed = time_script("One two three four.", [WriteText(text="Title"), Narration(text="ignored")])
    assert timed[0].type == "narration"
    assert timed[0].at_ms == 0
    assert timed[0].duration_ms == speech_ms("One two three four.")
    assert timed[1].at_ms > 0
    events = build_events(
        session_id="s",
        phase="check",
        step_index=0,
        chat="First sentence. Second sentence.",
        actions=[{"type": "narration", "text": "First sentence. Second sentence.", "at_ms": 0, "duration_ms": 1000, "id": "n", "page_id": "p"}],
        check_prompt="What is 2?",
        check_kind="ask",
        choices=[],
        message_id="m",
        voice=None,
        refused=False,
        redirected=False,
    )
    kinds = [event["type"] for event in events]
    assert kinds[0] == "meta"
    assert "chat" in kinds
    assert "narration" in kinds
    assert "check" in kinds
    assert kinds[-1] == "done"
    assert events[1]["delay_ms"] == 0


def test_rls_limits_teacher_rows_to_student_parent_and_teacher():
    sql = teacher_rls_sql()
    using = teacher_session_using_sql()
    check = teacher_session_check_sql()
    assert "student_user_id" in using
    assert "guardian_user_ids" in using
    assert "teacher_user_ids" in using
    assert "app.user_id" in using
    assert "app.school_id" in using
    assert "student_user_id" in check
    assert f"ALTER TABLE {TEACHER_SESSION_TABLE} FORCE ROW LEVEL SECURITY;" in sql
    for table in TEACHER_CHILD_TABLES:
        assert f"CREATE POLICY {table}_audience" in sql
        assert f"{table}.session_id" in sql


def test_audience_sql_matches_role():
    parent = _auth(PARENT, "PARENT")
    teacher = _auth(TEACHER, "TEACHER")
    student = _auth(USER_A, "STUDENT")
    admin = _auth(USER_B, "SCHOOL_ADMIN")
    dialect = postgresql.dialect()
    parent_sql = str(select(TeacherSession.id).where(audience_condition(parent)).compile(dialect=dialect))
    teacher_sql = str(select(TeacherSession.id).where(audience_condition(teacher)).compile(dialect=dialect))
    student_sql = str(select(TeacherSession.id).where(audience_condition(student)).compile(dialect=dialect))
    admin_sql = str(select(TeacherSession.id).where(audience_condition(admin)).compile(dialect=dialect))
    assert "guardian_user_ids" in parent_sql
    assert "teacher_user_ids" in teacher_sql
    assert "student_user_id" in student_sql
    assert "false" in admin_sql.lower()


def _session(**kwargs) -> SessionRecord:
    base = dict(
        id=uuid4(),
        school_id=SCHOOL_A,
        student_user_id=USER_A,
        student_id=USER_A,
        guardian_user_ids=[PARENT],
        teacher_user_ids=[TEACHER],
        subject_id=None,
        class_id=None,
        conversation_id=None,
        title="Fractions",
        topic="fractions",
        status="active",
        phase="check",
        grade_band="elementary",
        step_index=0,
        attempt=0,
        turn_index=1,
        awaiting_check=True,
        expected_answer="2",
        check_prompt="What is the denominator?",
        check_kind="ask",
    )
    base.update(kwargs)
    return SessionRecord(**base)


def test_access_matrix():
    record = _session()
    assert role_can_read(_auth(USER_A), record)
    assert role_can_write(_auth(USER_A), record)
    assert role_can_read(_auth(PARENT, "PARENT"), record)
    assert not role_can_write(_auth(PARENT, "PARENT"), record)
    assert role_can_read(_auth(TEACHER, "TEACHER"), record)
    assert not role_can_read(_auth(USER_B), record)
    assert not role_can_read(_auth(USER_A, school_id=SCHOOL_B), record)
    assert not role_can_read(_auth(USER_B, "SCHOOL_ADMIN"), record)
    hidden = public_plan(
        {"topic": "fractions", "reasoning": "hidden", "steps": [{"title": "A", "expected_answer": "2", "reasoning": "x"}]},
        role="STUDENT",
    )
    assert "expected_answer" not in hidden["steps"][0]
    assert "reasoning" not in hidden
    visible = public_plan(
        {"topic": "fractions", "steps": [{"title": "A", "expected_answer": "2"}]},
        role="TEACHER",
    )
    assert visible["steps"][0]["expected_answer"] == "2"


@pytest.mark.asyncio
async def test_lesson_flow_checks_adapts_and_hides_the_answer_key():
    service = _service()
    student = _auth(USER_A)
    first = await service.start(student, _body("Please teach me fractions"), None)
    assert first.phase == "check"
    assert first.awaiting_check
    assert first.actions
    assert {action["type"] for action in first.actions} >= {"write_text", "write_math", "narration", "place_icon"}
    dumped = first.model_dump()
    found: set[str] = set()
    _keys(dumped, found)
    assert "expected_answer" not in found
    assert "reasoning" not in found
    assert "internal_notes" not in found
    assert "bomb" not in first.chat_text

    wrong = await service.send(student, first.session_id, "blue", None)
    assert wrong.step_index == 0
    assert wrong.phase == "check"
    assert any(item.concept for item in service.store.rows[first.session_id].progress)

    right = await service.send(student, first.session_id, "2", None)
    assert right.step_index == 1

    detail = await service.get_session(student, first.session_id)
    assert detail.actions
    assert detail.messages[0]["role"] == "user"
    assert "expected_answer" not in json.dumps(detail.plan)
    teacher_view = await service.get_session(_auth(TEACHER, "TEACHER"), first.session_id)
    assert "expected_answer" in json.dumps(teacher_view.plan)
    listed = await service.list_sessions(_auth(PARENT, "PARENT"))
    assert [item.id for item in listed] == [first.session_id]
    assert await service.list_sessions(_auth(USER_B)) == []
    with pytest.raises(NotFoundError):
        await service.get_session(_auth(USER_B), first.session_id)
    with pytest.raises(ForbiddenError):
        await service.send(_auth(PARENT, "PARENT"), first.session_id, "2", None)


@pytest.mark.asyncio
async def test_harmful_request_has_no_board_and_off_topic_redirects():
    service = _service()
    student = _auth(USER_A)
    refused = await service.start(student, _body("how to make a bomb"), None)
    assert refused.refused
    assert refused.actions == []
    assert "bomb" not in refused.chat_text
    redirected = await service.send(student, refused.session_id, "let's play fortnite", None)
    assert redirected.redirected
    assert redirected.actions == []


@pytest.mark.asyncio
async def test_voice_clip_rescales_the_board_clock():
    service = _service(voice=FakeVoice())
    turn = await service.start(_auth(USER_A), _body("teach me fractions"), None)
    narration = next(event for event in turn.events if event["type"] == "narration")
    assert narration["voice"]["provider"] == "gemini_live"
    assert narration["duration_ms"] == 8000
    assert all(event["type"] != "board" or event["action"]["type"] != "narration" for event in turn.events)


@pytest.mark.asyncio
async def test_rate_limit_on_lesson_turns():
    settings = get_settings()
    original = settings.teacher_rate_limit_per_minute
    settings.teacher_rate_limit_per_minute = 1
    limiter.reset()
    service = _service()
    try:
        await service.start(_auth(USER_A), _body("teach me fractions"), None)
        with pytest.raises(RateLimitError):
            await service.start(_auth(USER_A), _body("teach me graphs"), None)
    finally:
        settings.teacher_rate_limit_per_minute = original
        limiter.reset()


@pytest.mark.asyncio
async def test_resume_reopens_a_finished_lesson():
    service = _service()
    student = _auth(USER_A)
    turn = await service.start(student, _body("teach me fractions"), None)
    record = service.store.rows[turn.session_id]
    record.status = "completed"
    record.phase = "summarise"
    detail = await service.resume(student, turn.session_id, None)
    assert detail.status == "active"
    replay = [action.seq for action in detail.actions]
    assert replay == sorted(replay)


@pytest.mark.asyncio
async def test_graph_summarises_after_the_last_correct_answer():
    state = {
        "student_message": "teach me fractions",
        "grade_band": "elementary",
        "context_block": "",
        "page_id": "current",
        "needs_new_page": False,
        "has_plan": False,
        "awaiting_check": False,
        "step_index": 0,
        "attempt": 0,
        "plan": {},
        "expected_answer": "",
        "phase": "understand",
        "status": "active",
        "actions": [],
        "trace": [],
        "progress_updates": [],
    }
    llm = StubLLM()
    first = await run_teacher_turn(state, llm)
    assert first["phase"] == "check"
    assert first["plan"]["topic"] == "fractions"
    assert "trace" in first
    for _ in range(2):
        first = await run_teacher_turn(
            {
                **state,
                "student_message": first["expected_answer"],
                "has_plan": True,
                "awaiting_check": True,
                "plan": first["plan"],
                "expected_answer": first["expected_answer"],
                "step_index": first["step_index"],
                "attempt": 0,
                "phase": first["phase"],
                "status": first["status"],
            },
            llm,
        )
        assert first["phase"] == "check"
    done = await run_teacher_turn(
        {
            **state,
            "student_message": first["expected_answer"],
            "has_plan": True,
            "awaiting_check": True,
            "plan": first["plan"],
            "expected_answer": first["expected_answer"],
            "step_index": first["step_index"],
            "phase": "check",
            "status": "active",
        },
        llm,
    )
    assert done["phase"] == "summarise"
    assert done["status"] == "completed"
    assert done["actions"]


def test_wikimedia_payload_picks_an_https_image():
    payload = {
        "query": {
            "pages": {
                "1": {
                    "imageinfo": [
                        {"mime": "image/jpeg", "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/a.jpg"}
                    ]
                }
            }
        }
    }
    assert image_from_wikimedia(payload).startswith("https://upload.wikimedia.org/")
    assert image_from_wikimedia({"query": {"pages": {}}}) is None


@pytest.mark.asyncio
async def test_gemini_live_reader_collects_pcm_chunks():
    pcm = __import__("base64").b64encode(b"\x00\x01" * 8).decode()

    class FakeSocket:
        def __init__(self):
            self.sent = []
            self._incoming = [
                json.dumps({"setupComplete": {}}),
                json.dumps({"serverContent": {"modelTurn": {"parts": [{"inlineData": {"data": pcm}}]}}}),
                json.dumps({"serverContent": {"turnComplete": True}}),
            ]

        async def send(self, raw):
            self.sent.append(raw)

        async def recv(self):
            return self._incoming.pop(0)

    audio = await read_live_audio(FakeSocket(), text="Hello class", timeout=2)
    assert audio.startswith(b"\x00\x01")


def test_http_protocol_and_auth_and_sse_shape():
    assert client.post("/api/v1/ai/teacher/sessions", json={"message": "fractions"}).status_code == 401
    token = mint()
    schema = client.get("/api/v1/ai/teacher/protocol", headers=bearer(token))
    assert schema.status_code == 200
    assert schema.json()["version"] == "1.0"
    for name in ACTION_TYPES:
        assert name in json.dumps(schema.json()["schema"])

    class FakeService:
        async def start(self, auth, body, bearer_token):
            return TurnResponse(
                session_id=uuid4(),
                message_id=uuid4(),
                phase="check",
                status="active",
                step_index=0,
                chat_text="A fraction is a part of a whole.",
                actions=[],
                events=[
                    {"type": "meta", "at_ms": 0, "delay_ms": 0, "session_id": "s", "phase": "check"},
                    {"type": "chat", "at_ms": 0, "delay_ms": 0, "content": "A fraction is a part of a whole."},
                    {"type": "done", "at_ms": 0, "delay_ms": 0, "session_id": "s", "message_id": "m"},
                ],
                awaiting_check=True,
                check_prompt="What is a fraction?",
            )

    app.dependency_overrides[get_teacher_service] = lambda: FakeService()
    try:
        streamed = client.post(
            "/api/v1/ai/teacher/sessions",
            headers=bearer(token),
            json={"message": "fractions", "stream": True},
        )
        assert streamed.status_code == 201
        assert "text/event-stream" in streamed.headers["content-type"]
        assert "event: meta" in streamed.text
        assert "event: chat" in streamed.text
        assert "event: done" in streamed.text
    finally:
        app.dependency_overrides.clear()


def test_live_socket_rejects_a_missing_token():
    with client.websocket_connect(f"/api/v1/ai/teacher/sessions/{uuid4()}/live") as socket:
        payload = socket.receive_json()
    assert payload["type"] == "error"


def _body(message: str):
    from src.modules.teacher.schemas import StartSessionRequest

    return StartSessionRequest(message=message)


def test_request_timeout_covers_teacher_streams():
    from src.core.middleware import request_timeout_for_path

    settings = get_settings()
    assert request_timeout_for_path("/api/v1/ai/teacher/sessions/abc/stream") == settings.stream_timeout_seconds
    assert request_timeout_for_path("/api/v1/ai/chat") == settings.stream_timeout_seconds
    assert request_timeout_for_path("/api/v1/ai/learning/summary") == settings.request_timeout_seconds
