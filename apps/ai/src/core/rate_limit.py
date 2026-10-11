import logging
import time

from src.core.config import get_settings

logger = logging.getLogger("sybeez.ai.ratelimit")


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._lock = None
        self._redis = None

    def _mutex(self):
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()
        return self._lock

    def reset(self) -> None:
        self._hits.clear()

    async def allow(self, key: str, *, limit: int | None = None) -> bool:
        settings = get_settings()
        cap = settings.rate_limit_per_minute if limit is None else limit
        window = settings.rate_limit_window_seconds
        if settings.rate_limit_backend.lower() == "redis":
            try:
                return await self._redis_allow(key, cap, window)
            except Exception:
                logger.warning("redis rate limit unavailable; using in-process limiter")
        return await self._memory_allow(key, cap, window)

    async def _memory_allow(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        async with self._mutex():
            fresh = [stamp for stamp in self._hits.get(key, []) if now - stamp < window]
            if len(fresh) >= limit:
                self._hits[key] = fresh
                return False
            fresh.append(now)
            self._hits[key] = fresh
            if len(self._hits) > 10000:
                cutoff = now - window
                self._hits = {
                    name: [stamp for stamp in stamps if stamp >= cutoff]
                    for name, stamps in self._hits.items()
                    if any(stamp >= cutoff for stamp in stamps)
                }
            return True

    async def _redis_client(self):
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                get_settings().redis_url,
                socket_timeout=0.25,
                socket_connect_timeout=0.25,
                decode_responses=True,
            )
        return self._redis

    async def _redis_allow(self, key: str, limit: int, window: int) -> bool:
        client = await self._redis_client()
        redis_key = f"sybeez:ai:rl:{key}"
        count = await client.incr(redis_key)
        ttl = await client.ttl(redis_key)
        if count == 1 or ttl < 0:
            await client.expire(redis_key, window)
        return int(count) <= limit


limiter = RateLimiter()
