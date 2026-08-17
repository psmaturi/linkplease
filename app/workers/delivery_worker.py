"""
workers/delivery_worker.py — Pulls DM jobs from Redis and delivers them.
"""

import asyncio
import logging
import signal
import sys

import redis.asyncio as aioredis

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.services.delivery_service import deliver_dm
from app.services.pseudogram_client import PseudogramClient
from app.utils.rate_limiter import SlidingWindowRateLimiter

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

pg_client = PseudogramClient()


async def startup_scan(db_session_factory, redis_client: aioredis.Redis) -> int:
    """
    On startup, find dm_attempts with status in ('queued', 'sending') that
    are NOT already in the Redis queue, and re-enqueue them.

    This recovers from crashes that happened between DB write and Redis push,
    or between 'sending' and the API call completing.

    Returns the number of jobs re-enqueued.
    """
    from sqlalchemy import select, text
    from app.models.dm_attempt import DmAttempt

    async with db_session_factory() as db:
        result = await db.execute(
            select(DmAttempt.id, DmAttempt.status)
            .where(DmAttempt.status.in_(["queued", "sending"]))
        )
        stuck_attempts = result.all()

    if not stuck_attempts:
        logger.info("Startup scan: no stuck jobs found")
        return 0

    async with db_session_factory() as db:
        await db.execute(
            text("UPDATE dm_attempts SET status = 'queued' WHERE status = 'sending'")
        )
        await db.commit()

    attempt_ids = [str(row.id) for row in stuck_attempts]

    if attempt_ids:
        await redis_client.lpush(settings.delivery_queue_key, *attempt_ids)
        logger.info("Startup scan: re-enqueued %d stuck job(s)", len(attempt_ids))

    return len(attempt_ids)


async def run_worker():
    """
    Main worker loop. Runs indefinitely, pulling jobs from Redis.
    """
    logger.info("Delivery worker starting...")

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    rate_limiter = SlidingWindowRateLimiter(redis_client)

    await startup_scan(AsyncSessionLocal, redis_client)

    logger.info("Delivery worker ready — listening on queue '%s'", settings.delivery_queue_key)

    while True:
        try:
            item = await redis_client.brpop(settings.delivery_queue_key, timeout=5)

            if item is None:
                continue

            _queue_name, attempt_id = item
            logger.info("Processing dm_attempt: %s", attempt_id)

            async with AsyncSessionLocal() as db:
                status = await deliver_dm(
                    attempt_id=attempt_id,
                    db=db,
                    redis_client=redis_client,
                    pg_client=pg_client,
                    rate_limiter=rate_limiter,
                )
                logger.info("dm_attempt %s final status: %s", attempt_id, status)

        except asyncio.CancelledError:
            logger.info("Delivery worker shutting down (CancelledError)")
            break
        except Exception as e:
            logger.exception("Unexpected error processing job: %s", e)
            await asyncio.sleep(1)

    await pg_client.close()
    await redis_client.aclose()
    await engine.dispose()
    logger.info("Delivery worker stopped cleanly")


def main():
    """Entry point for `python -m app.workers.delivery_worker`."""
    loop = asyncio.new_event_loop()

    # Handle SIGTERM (Docker stop) and SIGINT (Ctrl+C) gracefully
    def _shutdown(sig):
        logger.info("Received signal %s — shutting down worker", sig.name)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGTERM, _shutdown, signal.SIGTERM)
        loop.add_signal_handler(signal.SIGINT, _shutdown, signal.SIGINT)

    try:
        loop.run_until_complete(run_worker())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
