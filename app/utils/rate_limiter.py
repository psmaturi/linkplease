"""
utils/rate_limiter.py — Sliding-window rate limiter using Redis.

PURPOSE: Ensure we never exceed 10 PseudoGram API requests per 60 seconds.
"""

import asyncio
import logging
import time
import uuid

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """
    Enforces a sliding-window rate limit using a Redis sorted set.

    Usage:
        limiter = SlidingWindowRateLimiter(redis_client)
        await limiter.acquire()
    """

    def __init__(self, redis_client: aioredis.Redis):
        self._redis = redis_client
        self._key = settings.rate_limit_key
        self._limit = settings.pseudogram_rate_limit
        self._window = settings.pseudogram_rate_window_seconds

    async def acquire(self) -> None:
        """
        Block until a rate-limit slot is available, then claim it.
        This must be called before every PseudoGram API request.
        """
        while True:
            now = time.time()
            window_start = now - self._window

            slot_acquired = await self._try_acquire(now, window_start)

            if slot_acquired:
                return

            oldest = await self._get_oldest_timestamp()
            if oldest is None:
                await asyncio.sleep(0.05)
                continue

            wait_seconds = (oldest + self._window) - time.time()
            if wait_seconds > 0:
                logger.info(
                    "Rate limit reached (%d/%ds). Waiting %.2fs",
                    self._limit, self._window, wait_seconds
                )
                await asyncio.sleep(wait_seconds + 0.1)  # +0.1s buffer

    async def _try_acquire(self, now: float, window_start: float) -> bool:
        """
        Atomically check count and add a new entry if under the limit.
        """
        lua_script = """
        local key = KEYS[1]
        local window_start = tonumber(ARGV[1])
        local now = tonumber(ARGV[2])
        local limit = tonumber(ARGV[3])
        local ttl = tonumber(ARGV[4])
        local member = ARGV[5]

        -- Remove expired entries
        redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

        -- Check current count
        local count = redis.call('ZCARD', key)

        if count < limit then
            -- Claim a slot
            redis.call('ZADD', key, now, member)
            redis.call('EXPIRE', key, ttl)
            return 1
        end

        return 0
        """
        member = str(uuid.uuid4())
        result = await self._redis.eval(
            lua_script,
            1,
            self._key,
            str(window_start),
            str(now),
            str(self._limit),
            str(self._window + 5),
            member,
        )
        return bool(result)

    async def _get_oldest_timestamp(self) -> float | None:
        """Return the score (timestamp) of the oldest entry in the window."""
        results = await self._redis.zrange(
            self._key, 0, 0, withscores=True
        )
        if not results:
            return None
        return results[0][1]  # (member, score) — we want score
