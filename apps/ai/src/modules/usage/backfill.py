"""Replay token counts already stored on ai_messages.meta.usage.

Rows with no usage object are skipped. Counts that were never stored are not invented.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import AIMessage
from src.modules.usage.report import attach_usage, publish_usage
from src.modules.usage.tokens import stored_usage

logger = logging.getLogger("sybeez.ai.usage")


async def load_usage_messages(session: AsyncSession, *, limit: int) -> list[AIMessage]:
    result = await session.execute(
        select(AIMessage)
        .where(AIMessage.meta["usage"].is_not(None))
        .order_by(AIMessage.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def backfill_messages(messages, bearer: str | None) -> dict:
    posted = skipped = failed = 0
    for message in messages:
        record = stored_usage(getattr(message, "meta", None))
        if record is None or record.get("reported") is True:
            skipped += 1
            continue
        try:
            stored = await publish_usage(dict(record), bearer, message)
        except Exception as exc:
            logger.warning("ai usage backfill failed: %s", type(exc).__name__)
            stored = None
        if stored and stored.get("reported") is True:
            posted += 1
        else:
            failed += 1
            attach_usage(message, {**record, "reported": False})
    return {"posted": posted, "skipped": skipped, "failed": failed}


async def run_backfill(auth, bearer: str | None, school_id, limit: int) -> dict:
    from src.core.database import AsyncSessionLocal, install_tenant_context

    async with AsyncSessionLocal() as session:
        install_tenant_context(session, school_id=school_id, user_id=auth.user_id, role=auth.role)
        try:
            messages = await load_usage_messages(session, limit=limit)
            result = await backfill_messages(messages, bearer)
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise
