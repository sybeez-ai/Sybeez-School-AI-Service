import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import AuthContext, require_school
from src.core.telemetry import track
from src.modules.chat.persona import persona_system
from src.modules.chat.schemas import ChatRequest, ChatResponse
from src.modules.context.service import ContextService
from src.modules.conversations.schemas import ConversationCreate
from src.modules.conversations.service import ConversationService
from src.modules.memory.service import MemoryService
from src.modules.retrieval.service import RetrievalService
from src.providers.llm import get_llm, guarded_complete
from src.shared.enums import MessageRole
from src.shared.utils import load_prompt

logger = logging.getLogger("sybeez.ai.chat")


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conversations = ConversationService(db)
        self.retrieval = RetrievalService(db)
        self.memory = MemoryService(db)
        self.context = ContextService()
        self.llm = get_llm()

    async def chat(
        self,
        auth: AuthContext,
        body: ChatRequest,
        *,
        bearer_token: str | None = None,
    ) -> ChatResponse:
        school_id = require_school(auth)
        learning = await self.context.for_user(auth, bearer_token=bearer_token, subject_id=body.subject_id)

        if body.conversation_id:
            conv = await self.conversations.get(auth, body.conversation_id)
        else:
            conv = await self.conversations.create(
                auth,
                ConversationCreate(subject_id=body.subject_id or (learning.current_learning.subject_id if learning.current_learning else None), title="AI Teacher"),
                student_id=learning.student.id,
            )

        await self.conversations.append(
            auth=auth, conversation_id=conv.id, role=MessageRole.USER, content=body.message
        )

        history = await self.conversations.repo.recent_messages(conv.id, school_id=school_id, limit=12)
        history_text = "\n".join(f"{m.role}: {m.content}" for m in history)

        retrieved = await self.retrieval.search(
            auth,
            query=body.message,
            subject_id=conv.subject_id,
            class_id=conv.class_id or learning.student.class_id,
        )
        recalled = await self.memory.recall(auth, student_id=learning.student.id, query=body.message)

        system = persona_system(load_prompt("system/ai_teacher.txt"), auth.role)
        teaching = load_prompt("teaching/explain.txt")
        user_prompt = (
            f"{teaching}\n\n"
            f"=== AUTHORIZED SCHOOL CONTEXT ===\n{learning.as_prompt_block()}\n\n"
            f"=== RETRIEVED KNOWLEDGE ===\n{retrieved.as_prompt_block()}\n\n"
            f"=== AI MEMORY ===\n{recalled.as_prompt_block()}\n\n"
            f"=== CONVERSATION ===\n{history_text}\n\n"
            f"Respond as the AI Teacher."
        )

        reply = await guarded_complete(self.llm, system=system, user=user_prompt)
        assistant = await self.conversations.append(
            auth=auth,
            conversation_id=conv.id,
            role=MessageRole.ASSISTANT,
            content=reply,
            meta={"sources": [h.source for h in retrieved.hits if h.source]},
        )

        track("ai_chat", school_id=str(school_id), conversation_id=str(conv.id))
        return ChatResponse(
            conversation_id=conv.id,
            message_id=assistant.id,
            reply=reply,
            sources=[str(h.chunk_id) for h in retrieved.hits if h.chunk_id],
        )

    async def stream_tokens(
        self,
        auth: AuthContext,
        body: ChatRequest,
        *,
        bearer_token: str | None = None,
    ):
        """Yield SSE-friendly events; persists full reply at end."""
        school_id = require_school(auth)
        learning = await self.context.for_user(auth, bearer_token=bearer_token, subject_id=body.subject_id)

        if body.conversation_id:
            conv = await self.conversations.get(auth, body.conversation_id)
        else:
            conv = await self.conversations.create(
                auth,
                ConversationCreate(subject_id=body.subject_id, title="AI Teacher"),
                student_id=learning.student.id,
            )

        await self.conversations.append(
            auth=auth, conversation_id=conv.id, role=MessageRole.USER, content=body.message
        )

        history = await self.conversations.repo.recent_messages(conv.id, school_id=school_id, limit=12)
        history_text = "\n".join(f"{m.role}: {m.content}" for m in history)
        retrieved = await self.retrieval.search(auth, query=body.message, subject_id=conv.subject_id)
        recalled = await self.memory.recall(auth, student_id=learning.student.id, query=body.message)

        system = persona_system(load_prompt("system/ai_teacher.txt"), auth.role)
        user_prompt = (
            f"{load_prompt('teaching/explain.txt')}\n\n"
            f"CONTEXT:\n{learning.as_prompt_block()}\n\n"
            f"KNOWLEDGE:\n{retrieved.as_prompt_block()}\n\n"
            f"MEMORY:\n{recalled.as_prompt_block()}\n\n"
            f"HISTORY:\n{history_text}"
        )

        parts: list[str] = []
        yield {"type": "meta", "conversation_id": str(conv.id)}
        try:
            async for token in self.llm.stream(system=system, user=user_prompt):
                parts.append(token)
                yield {"type": "token", "content": token}
        except Exception:
            logger.exception("llm stream failed")
            yield {"type": "error", "message": "The teacher could not finish this response"}
            return

        full = "".join(parts)
        msg = await self.conversations.append(
            auth=auth, conversation_id=conv.id, role=MessageRole.ASSISTANT, content=full
        )
        yield {"type": "done", "message_id": str(msg.id), "conversation_id": str(conv.id)}
