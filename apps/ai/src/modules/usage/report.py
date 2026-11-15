"""Send one completion's token counts to the school backend.

A failure here is logged and swallowed. The user-facing reply still returns.
"""

from __future__ import annotations

import logging

from src.modules.usage.tokens import collect_usage, post_body

logger = logging.getLogger("sybeez.ai.usage")


def attach_usage(message, record: dict) -> None:
    if message is None:
        return
    meta = dict(getattr(message, "meta", None) or {})
    meta["usage"] = dict(record)
    message.meta = meta


async def publish_usage(record: dict | None, bearer: str | None, message=None) -> dict | None:
    """POST the usage. On success mark the stored row so a later backfill does not send it again."""
    if not record or post_body(record) is None:
        return None
    ok = False
    try:
        from src.modules.context.core_client import CoreClient

        ok = await CoreClient().post_ai_usage(record, bearer)
    except Exception as exc:
        logger.warning("ai usage record failed: %s", type(exc).__name__)
        ok = False
    stored = {**record, "reported": bool(ok)}
    try:
        attach_usage(message, stored)
    except Exception as exc:
        logger.warning("ai usage meta update failed: %s", type(exc).__name__)
    return stored


async def publish_llm_usage(provider: object, *, auth, bearer: str | None, capability: str = "CHAT", start: int = 0, message=None) -> dict | None:
    record = collect_usage(provider, auth=auth, capability=capability, start=start)
    return await publish_usage(record, bearer, message)
