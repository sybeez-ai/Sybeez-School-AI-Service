"""Which features the caller's school (or the caller) has switched off, read from Core with the caller's own token.

Core is the authority and enforces the same switches on every API call; this only keeps the assistant from offering
or promising things that would be refused. Fails open (empty) because Core still enforces.
"""

import logging

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
