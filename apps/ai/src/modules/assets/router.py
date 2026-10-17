"""Asset lookup for the AI Teacher (picture and 3D tabs)."""

from fastapi import APIRouter, Query

from src.api.dependencies import AuthDep
from src.core.exceptions import ForbiddenError
from src.modules.assets.catalog import library, lookup

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/topic")
async def topic_assets(
    auth: AuthDep,
    q: str = Query(min_length=1, max_length=200),
    subject: str = Query(default="", max_length=60),
    class_no: int | None = Query(default=None, ge=1, le=12),
):
    if auth.school_id is None:
        raise ForbiddenError("School context required")
    return lookup(q, subject=subject, class_no=class_no)


@router.get("/library")
async def asset_library(
    auth: AuthDep,
    subject: str = Query(default="", max_length=60),
    class_no: int | None = Query(default=None, ge=1, le=12),
):
    if auth.school_id is None:
        raise ForbiddenError("School context required")
    return {"items": library(subject=subject, class_no=class_no)}
