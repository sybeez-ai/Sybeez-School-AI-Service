from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import AuthDep, BearerToken, get_db
from src.modules.context.service import ContextService
from src.modules.conversations.schemas import ConversationCreate, ConversationDetail, ConversationOut, MessageOut
from src.modules.conversations.service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationOut, status_code=201)
async def create_conversation(
    body: ConversationCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: AuthDep,
    bearer: BearerToken,
):
    ctx = await ContextService().for_user(auth, bearer_token=bearer, subject_id=body.subject_id)
    student_id = ctx.student.id
    conv = await ConversationService(db).create(auth, body, student_id=student_id)
    return conv


@router.get("", response_model=list[ConversationOut])
async def list_conversations(db: Annotated[AsyncSession, Depends(get_db)], auth: AuthDep):
    return await ConversationService(db).list(auth)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: AuthDep,
):
    conv = await ConversationService(db).get(auth, conversation_id)
    messages = [MessageOut.model_validate(m) for m in sorted(conv.messages, key=lambda x: x.created_at)]
    detail = ConversationDetail.model_validate(conv)
    detail.messages = messages
    return detail
