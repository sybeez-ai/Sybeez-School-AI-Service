"""Daily caps for paid voice sessions and language-model calls.

The per-minute limiter stops bursts. These stop one account, or one school,
from running the model all day. A limit of 0 disables that check. Counters
reset 24 hours after the first call in the window, using the same Redis (or
in-process) store as the per-minute limiter. No extra infrastructure.
"""

from src.core.config import get_settings
from src.core.rate_limit import limiter

DAY_SECONDS = 86_400

DAILY_LIMIT_MESSAGE = "Daily AI limit reached for this account. Please try again tomorrow."


async def _allow(key: str, limit: int) -> bool:
    if limit <= 0:
        return True
    return await limiter.allow(key, limit=limit, window=DAY_SECONDS)


async def allow_voice(auth) -> bool:
    settings = get_settings()
    if not await _allow(f"day:voice:user:{auth.user_id}", settings.voice_sessions_per_user_per_day):
        return False
    if auth.school_id is None:
        return True
    return await _allow(f"day:voice:school:{auth.school_id}", settings.voice_sessions_per_school_per_day)


async def allow_model(auth) -> bool:
    settings = get_settings()
    if not await _allow(f"day:model:user:{auth.user_id}", settings.model_calls_per_user_per_day):
        return False
    if auth.school_id is None:
        return True
    return await _allow(f"day:model:school:{auth.school_id}", settings.model_calls_per_school_per_day)
