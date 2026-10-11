from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.core.health import liveness, readiness
from src.modules.chat.router import router as chat_router
from src.modules.conversations.router import router as conversations_router
from src.modules.evaluation.router import router as evaluation_router
from src.modules.learning.router import router as learning_router
from src.modules.practice.router import router as practice_router
from src.modules.teacher.router import router as teacher_router

api_router = APIRouter()

api_router.include_router(chat_router)
api_router.include_router(conversations_router)
api_router.include_router(practice_router)
api_router.include_router(evaluation_router)
api_router.include_router(learning_router)
api_router.include_router(teacher_router)


@api_router.get("/health")
async def health():
    return liveness()


@api_router.get("/ready")
async def ready():
    body, status_code = await readiness()
    return JSONResponse(status_code=status_code, content=body)
