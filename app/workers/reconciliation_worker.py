"""
workers/reconciliation_worker.py — Periodically checks PseudoGram DM statuses.
"""

import asyncio
import logging
import signal
import sys

import redis.asyncio as aioredis

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.services.pseudogram_client import PseudogramClient
from app.services.reconciliation_service import reconcile_sent_dms

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

pg_client = PseudogramClient()


async def run_reconciliation_worker():
    logger.info(
        "Reconciliation worker starting (interval=%ds)",
        settings.reconciliation_interval_seconds,
    )

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)

    while True:
        try:
            async with AsyncSessionLocal() as db:
                await reconcile_sent_dms(db, pg_client)
        except asyncio.CancelledError:
            logger.info("Reconciliation worker shutting down")
            break
        except Exception as e:
            logger.exception("Reconciliation error: %s", e)

        try:
            await asyncio.sleep(settings.reconciliation_interval_seconds)
        except asyncio.CancelledError:
            logger.info("Reconciliation worker shutting down (sleep interrupted)")
            break

    await pg_client.close()
    await redis_client.aclose()
    await engine.dispose()
    logger.info("Reconciliation worker stopped cleanly")


def main():
    """Entry point for `python -m app.workers.reconciliation_worker`."""
    loop = asyncio.new_event_loop()

    def _shutdown(sig):
        logger.info("Received signal %s — shutting down reconciliation worker", sig.name)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGTERM, _shutdown, signal.SIGTERM)
        loop.add_signal_handler(signal.SIGINT, _shutdown, signal.SIGINT)

    try:
        loop.run_until_complete(run_reconciliation_worker())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
