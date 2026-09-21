import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import AuthDep, BearerToken, get_db
from src.modules.chat.schemas import ChatRequest, ChatResponse
from src.modules.chat.service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
async def chat(
    body: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: AuthDep,
    bearer: BearerToken,
) -> Any:
    service = ChatService(db)
    if body.stream:

        async def event_gen():
            async for event in service.stream_tokens(auth, body, bearer_token=bearer):
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    result: ChatResponse = await service.chat(auth, body, bearer_token=bearer)
    return result
