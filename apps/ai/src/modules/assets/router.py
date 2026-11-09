"""Asset lookup for the AI Teacher (picture and 3D tabs)."""

from fastapi import APIRouter, Query

from src.api.dependencies import AuthDep
from src.core.exceptions import ForbiddenError
from src.modules.assets.catalog import library, lookup
from src.modules.teacher.images import search_educational_image

router = APIRouter(prefix="/assets", tags=["assets"])


def _commons_image(url: str, query: str) -> dict:
    label = " ".join(query.split())[:120] or "Diagram"
    return {
        "url": url,
        "caption": "Simple labelled diagram",
        "alt": label,
        "license": "See Wikimedia Commons",
        "license_url": "https://commons.wikimedia.org/wiki/Commons:Licensing",
        "author": "",
        "source": "https://commons.wikimedia.org/",
        "regions": [],
    }


@router.get("/topic")
async def topic_assets(
    auth: AuthDep,
    q: str = Query(min_length=1, max_length=200),
    subject: str = Query(default="", max_length=60),
    class_no: int | None = Query(default=None, ge=1, le=12),
):
    if auth.school_id is None:
        raise ForbiddenError("School context required")
    result = lookup(q, subject=subject, class_no=class_no)
    # A matched topic whose curated pictures are too technical (or missing) gets one
    # allowlisted Commons search, biased to a simple diagram for this grade.
    if result.get("found") and not result.get("images"):
        url = await search_educational_image(q, class_no=class_no)
        if url:
            result = {**result, "images": [_commons_image(url, q)], "picture_source": "wikimedia"}
    return result


@router.get("/library")
async def asset_library(
    auth: AuthDep,
    subject: str = Query(default="", max_length=60),
    class_no: int | None = Query(default=None, ge=1, le=12),
):
    if auth.school_id is None:
        raise ForbiddenError("School context required")
    return {"items": library(subject=subject, class_no=class_no)}
