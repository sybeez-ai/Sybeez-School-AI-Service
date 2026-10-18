"""Which features the caller's school (or the caller) has switched off, read from Core with the caller's own token.

Core is the authority and enforces the same switches on every API call; this only keeps the assistant from offering
or promising things that would be refused. Fails open (empty) because Core still enforces.
"""

import hashlib
import logging
import time

import httpx

from src.core.config import get_settings

logger = logging.getLogger(__name__)


async def disabled_labels(bearer: str | None) -> list[str]:
    if not bearer:
        return []
    s = get_settings()
    url = f"{s.core_api_url.rstrip('/')}/api/v1/features/me"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"})
        if resp.status_code != 200:
            return []
        rows = resp.json()
        return [str(r.get("label")) for r in rows if isinstance(r, dict) and r.get("enabled") is False and r.get("label")]
    except Exception as exc:  # noqa: BLE001
        logger.info("feature switches unavailable: %s", type(exc).__name__)
        return []


def prompt_block(labels: list[str]) -> str:
    if not labels:
        return ""
    names = ", ".join(sorted(set(labels))[:30])
    return (
        f"Switched off for this user (do not offer, open or promise these; if asked, say kindly that their school "
        f"admin has turned them off and suggest asking the school): {names}."
    )


_TTL = 10.0
_cache: dict[str, tuple[float, str | None]] = {}


async def ai_switched_off(bearer: str | None) -> str | None:
    """Label of the AI switch if Core says AI is turned off for this caller (platform or school), else None.

    Core enforces the same switch on its own routes; the AI service is reached directly by the web app, so it has
    to enforce it too. Cached for a few seconds per token. Fails open if Core cannot be reached (Core still
    enforces its own routes and the assistant prompt block).
    """
    if not bearer:
        return None
    key = hashlib.sha256(bearer.encode()).hexdigest()
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    s = get_settings()
    url = f"{s.core_api_url.rstrip('/')}/api/v1/features/me"
    result: str | None = None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"})
        if resp.status_code != 200:
            return None  # do not cache failures
        for r in resp.json():
            if isinstance(r, dict) and r.get("key") == "ai_assistant" and r.get("enabled") is False:
                result = str(r.get("label") or "AI assistant")
    except Exception as exc:  # noqa: BLE001
        logger.info("feature switches unavailable: %s", type(exc).__name__)
        return None
    if len(_cache) > 2000:
        _cache.clear()
    _cache[key] = (now, result)
    return result
