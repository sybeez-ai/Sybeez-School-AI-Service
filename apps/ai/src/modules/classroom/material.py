"""Today's class page, loaded with the caller's own token.

The school backend decides who may see a class section. A missing route or a
refusal becomes "no page", never another class's text.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

import httpx

from src.core.config import get_settings

logger = logging.getLogger("sybeez.ai.classroom")

_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 60.0


def reset_material_cache() -> None:
    _CACHE.clear()


class ClassroomMaterial:
    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()

    async def today(self, bearer: str | None, class_section_id: UUID, on: str) -> dict:
        if not bearer:
            return _empty()
        key = f"{bearer[-12:]}:{class_section_id}:{on}"
        hit = _CACHE.get(key)
        now = time.monotonic()
        if hit and now - hit[0] < _TTL:
            return hit[1]
        url = f"{self.settings.core_api_url.rstrip('/')}/api/v1/classroom/today"
        try:
            async with httpx.AsyncClient(timeout=self.settings.upstream_timeout_seconds) as client:
                response = await client.get(
                    url,
                    params={"class_section_id": str(class_section_id), "on": on},
                    headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            logger.info("classroom material unreachable: %s", type(exc).__name__)
            return _empty()
        if response.status_code != 200:
            logger.info("classroom material status=%s", response.status_code)
            return _empty()
        data = response.json()
        if not isinstance(data, dict):
            return _empty()
        page = _normalise(data)
        if len(_CACHE) > 500:
            _CACHE.clear()
        _CACHE[key] = (now, page)
        return page

    async def save_picture(self, bearer: str | None, payload: dict) -> str | None:
        return await self._post(bearer, "/api/v1/classroom/board-pictures", payload)

    async def remember(self, bearer: str | None, payload: dict) -> None:
        path = "/api/v1/classroom/memory/class" if payload.get("scope") == "class" else "/api/v1/classroom/memory/student"
        body = {key: value for key, value in payload.items() if key != "scope"}
        await self._post(bearer, path, body)

    async def _post(self, bearer: str | None, path: str, payload: dict) -> str | None:
        if not bearer:
            return None
        url = f"{self.settings.core_api_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.settings.upstream_timeout_seconds) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            logger.info("classroom save unreachable: %s", type(exc).__name__)
            return None
        if response.status_code not in {200, 201}:
            return None
        data = response.json() if response.content else {}
        if isinstance(data, dict) and data.get("id"):
            return str(data["id"])
        return None


def _empty() -> dict:
    return {
        "id": None,
        "class_section_id": None,
        "class_label": "",
        "on": "",
        "subject": "",
        "topic": "",
        "page_ref": "",
        "taught": "",
        "homework": "",
        "chunks": [],
    }


def _normalise(data: dict[str, Any]) -> dict:
    chunks = []
    for row in data.get("chunks") or []:
        if isinstance(row, dict) and str(row.get("text") or "").strip():
            chunks.append(
                {
                    "id": str(row.get("id") or ""),
                    "source": str(row.get("source") or "Today's class")[:80],
                    "text": str(row["text"]).strip()[:2000],
                }
            )
    return {
        "id": data.get("id"),
        "class_section_id": data.get("class_section_id"),
        "class_label": str(data.get("class_label") or "")[:40],
        "on": str(data.get("on") or "")[:10],
        "subject": str(data.get("subject") or "")[:80],
        "topic": str(data.get("topic") or "")[:160],
        "page_ref": str(data.get("page_ref") or "")[:160],
        "taught": str(data.get("taught") or "")[:4000],
        "homework": str(data.get("homework") or "")[:4000],
        "chunks": chunks[:8],
    }
