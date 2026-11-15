"""Replay stored token counts onto the school backend.

Protected the same way other internal routes are (bearer plus the internal token),
and also for a platform admin.
"""

from __future__ import annotations

import hmac
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from src.api.dependencies import AuthDep, BearerToken
from src.core.config import get_settings
from src.core.exceptions import AppError, ForbiddenError
from src.modules.platform_assistant.prompt import PLATFORM_ROLES
from src.modules.usage.backfill import run_backfill

logger = logging.getLogger("sybeez.ai.usage")

router = APIRouter(prefix="/internal", tags=["internal"])


class BackfillBody(BaseModel):
    school_id: UUID | None = None
    limit: int = Field(default=500, ge=1, le=2000)


def _internal_ok(token: str | None) -> bool:
    expected = get_settings().core_internal_token or ""
    if not token or not expected or len(token) != len(expected):
        return False
    return hmac.compare_digest(token, expected)


def _authorize(auth, internal_token: str | None) -> None:
    if auth.role in PLATFORM_ROLES:
        return
    if _internal_ok(internal_token):
        return
    raise ForbiddenError("Usage backfill is only available through the school platform")


def _school_id(auth, requested: UUID | None) -> UUID:
    if auth.school_id is not None:
        return auth.school_id
    if auth.role in PLATFORM_ROLES and requested is not None:
        return requested
    raise AppError("A school_id is required to backfill usage", code="school_required", status_code=400)


@router.post("/ai-usage/backfill")
async def backfill_ai_usage(
    auth: AuthDep,
    bearer: BearerToken,
    body: BackfillBody | None = None,
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
):
    payload = body or BackfillBody()
    _authorize(auth, x_internal_token)
    school_id = _school_id(auth, payload.school_id)
    try:
        return await run_backfill(auth, bearer, school_id, payload.limit)
    except AppError:
        raise
    except Exception as exc:
        logger.warning("ai usage backfill failed: %s", type(exc).__name__)
        raise AppError("Could not backfill AI usage", code="backfill_failed", status_code=502) from None
