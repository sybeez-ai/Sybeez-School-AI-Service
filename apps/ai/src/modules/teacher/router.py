import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import AuthDep, BearerToken, get_db
from src.core.database import AsyncSessionLocal, install_tenant_context
from src.core.exceptions import AppError
from src.core.security import authenticate_token
from src.modules.teacher.protocol import PROTOCOL_VERSION, board_action_schema
from src.modules.teacher.schemas import MessageRequest, SessionDetail, SessionSummary, StartSessionRequest, TurnResponse
from src.modules.teacher.service import TeacherService
from src.modules.teacher.timeline import pace_events

router = APIRouter(prefix="/teacher", tags=["teacher"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def get_teacher_service(db: Annotated[AsyncSession, Depends(get_db)]) -> TeacherService:
    return TeacherService(db)


def _sse(events, status_code: int = 200):
    async def generate():
        async for event in events:
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        generate(),
        status_code=status_code,
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/protocol")
async def protocol(_: AuthDep):
    return {"version": PROTOCOL_VERSION, "schema": board_action_schema()}


@router.post("/sessions", status_code=201)
async def start_session(
    body: StartSessionRequest,
    auth: AuthDep,
    bearer: BearerToken,
    service: Annotated[TeacherService, Depends(get_teacher_service)],
):
    if body.stream:
        turn = await service.start(auth, body, bearer)
        return _sse(pace_events(turn.events, pace=body.pace), status_code=201)
    return await service.start(auth, body, bearer)


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(auth: AuthDep, service: Annotated[TeacherService, Depends(get_teacher_service)]):
    return await service.list_sessions(auth)


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: UUID,
    auth: AuthDep,
    service: Annotated[TeacherService, Depends(get_teacher_service)],
):
    return await service.get_session(auth, session_id)


@router.post("/sessions/{session_id}/messages", response_model=None)
async def send_message(
    session_id: UUID,
    body: MessageRequest,
    auth: AuthDep,
    bearer: BearerToken,
    service: Annotated[TeacherService, Depends(get_teacher_service)],
):
    if body.stream:
        return _sse(service.stream(auth, session_id, body.message, bearer, pace=body.pace))
    result: TurnResponse = await service.send(auth, session_id, body.message, bearer)
    return result


@router.post("/sessions/{session_id}/stream")
async def stream_message(
    session_id: UUID,
    body: MessageRequest,
    auth: AuthDep,
    bearer: BearerToken,
    service: Annotated[TeacherService, Depends(get_teacher_service)],
):
    return _sse(service.stream(auth, session_id, body.message, bearer, pace=body.pace))


@router.post("/sessions/{session_id}/resume", response_model=SessionDetail)
async def resume_session(
    session_id: UUID,
    auth: AuthDep,
    bearer: BearerToken,
    service: Annotated[TeacherService, Depends(get_teacher_service)],
):
    return await service.resume(auth, session_id, bearer)


def _ws_token(websocket: WebSocket) -> str:
    header = websocket.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return (websocket.query_params.get("token") or "").strip()


@router.websocket("/sessions/{session_id}/live")
async def live(websocket: WebSocket, session_id: UUID):
    await websocket.accept()
    token = _ws_token(websocket)
    if not token:
        await websocket.send_json({"type": "error", "message": "Missing bearer token"})
        await websocket.close(code=1008)
        return
    try:
        auth = await authenticate_token(token)
    except AppError as exc:
        await websocket.send_json({"type": "error", "message": exc.message})
        await websocket.close(code=1008)
        return
    if auth.school_id is None:
        await websocket.send_json({"type": "error", "message": "School context required"})
        await websocket.close(code=1008)
        return
    try:
        payload = await websocket.receive_json()
    except Exception:
        await websocket.close(code=1008)
        return
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        await websocket.send_json({"type": "error", "message": "Message required"})
        await websocket.close(code=1008)
        return
    pace = bool(payload.get("pace")) if isinstance(payload, dict) else False
    async with AsyncSessionLocal() as session:
        install_tenant_context(session, school_id=auth.school_id, user_id=auth.user_id)
        service = TeacherService(session)
        try:
            async for event in service.stream(auth, session_id, message.strip(), token, pace=pace):
                await websocket.send_json(event)
        except AppError as exc:
            await websocket.send_json({"type": "error", "code": exc.code, "message": exc.message})
            await session.rollback()
            await websocket.close(code=1008)
            return
    await websocket.close()
