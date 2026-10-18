import logging

from sqlalchemy import text

from src.core.config import get_settings, secret_is_insecure
from src.core.database import engine
from src.modules.context.core_client import CoreClient
from src.version import APP_VERSION

logger = logging.getLogger("sybeez.ai.health")


def liveness() -> dict:
    return {"status": "ok", "service": "sybeez-ai", "version": APP_VERSION}


async def database_ok() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("database readiness check failed")
        return False


async def readiness() -> tuple[dict, int]:
    settings = get_settings()
    database = await database_ok()
    core = await CoreClient().ping()
    llm_ok = bool(settings.active_chat_api_key)
    # School backend session tokens (HS256 with JWT_SECRET) are what callers present; Cognito is optional.
    auth_ok = settings.cognito_configured or (
        settings.jwt_algorithm == "HS256" and bool(settings.jwt_secret) and not secret_is_insecure(settings.jwt_secret)
    )
    if not database:
        status_name = "not_ready"
    elif not core or not llm_ok or not auth_ok:
        status_name = "degraded"
    else:
        status_name = "ready"
    body = {
        "status": status_name,
        "service": "sybeez-ai",
        "version": APP_VERSION,
        "dependencies": {
            "database": {"ok": database},
            "core_api": {"ok": core},
            "llm": {"ok": llm_ok},
            "auth": {"ok": auth_ok},
        },
    }
    return body, 200 if database else 503
