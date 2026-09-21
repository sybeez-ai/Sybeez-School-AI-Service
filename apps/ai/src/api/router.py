from fastapi import APIRouter

from src.modules.chat.router import router as chat_router
from src.modules.conversations.router import router as conversations_router
from src.modules.evaluation.router import router as evaluation_router
from src.modules.learning.router import router as learning_router
from src.modules.practice.router import router as practice_router

api_router = APIRouter()

api_router.include_router(chat_router)
api_router.include_router(conversations_router)
api_router.include_router(practice_router)
api_router.include_router(evaluation_router)
api_router.include_router(learning_router)


@api_router.get("/health")
async def health():
    return {"status": "ok", "service": "sybeez-ai"}


@api_router.get("/ready")
async def ready():
    from src.core.config import get_settings
    from src.modules.context.core_client import CoreClient

    settings = get_settings()
    core_ok = await CoreClient().ping()
    return {
        "status": "ready" if core_ok else "degraded",
        "service": "sybeez-ai",
        "dependencies": {
            "core_api": {
                "url": settings.core_api_url,
                "ok": core_ok,
            }
        },
    }
