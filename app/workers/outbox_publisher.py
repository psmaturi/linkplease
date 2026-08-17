"""
workers/outbox_publisher.py — Transactional Outbox Publisher
"""

import asyncio
import logging
import sys
import signal

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.models.outbox_event import OutboxEvent

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def publish_outbox_events(db: AsyncSession, redis_client: aioredis.Redis):
    """
    Find unpublished outbox events, push to Redis, mark published.
    """
    result = await db.execute(
        select(OutboxEvent).where(OutboxEvent.published == False).limit(100)
    )
    events = result.scalars().all()

    if not events:
        return 0

    attempt_ids = [event.dm_attempt_id for event in events]

    if attempt_ids:
        await redis_client.lpush(settings.delivery_queue_key, *attempt_ids)

    for event in events:
        event.published = True

    await db.commit()
    logger.info("Outbox publisher: Pushed %d recovered dm_attempts to Redis", len(events))
    return len(events)


async def run_publisher():
    logger.info("Outbox publisher starting...")
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)

    while True:
        try:
            async with AsyncSessionLocal() as db:
                published_count = await publish_outbox_events(db, redis_client)
            
            if published_count == 100:
                await asyncio.sleep(0.1)
            else:
                await asyncio.sleep(5.0)

        except asyncio.CancelledError:
            logger.info("Outbox publisher shutting down (CancelledError)")
            break
        except Exception as e:
            logger.error("Outbox publisher error: %s", e)
            await asyncio.sleep(5.0)

    await redis_client.aclose()
    await engine.dispose()
    logger.info("Outbox publisher stopped cleanly")


def main():
    loop = asyncio.new_event_loop()

    def _shutdown(sig):
        logger.info("Received signal %s — shutting down outbox publisher", sig.name)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGTERM, _shutdown, signal.SIGTERM)
        loop.add_signal_handler(signal.SIGINT, _shutdown, signal.SIGINT)

    try:
        loop.run_until_complete(run_publisher())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
