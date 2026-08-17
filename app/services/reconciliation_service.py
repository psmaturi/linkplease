"""
services/reconciliation_service.py — Detect silently failed DMs.
"""

import asyncio
import logging

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dm_attempt import DmAttempt
from app.services.pseudogram_client import PseudogramClient

logger = logging.getLogger(__name__)

MAX_RECONCILIATION_ATTEMPTS = 5


async def reconcile_sent_dms(
    db: AsyncSession,
    pg_client: PseudogramClient,
) -> dict:
    """
    Check PseudoGram for the current status of all 'accepted' DMs.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(DmAttempt)
        .where(DmAttempt.status == "accepted")
        .where(DmAttempt.external_dm_id.isnot(None))
        .where(
            or_(
                DmAttempt.next_reconciliation_at.is_(None),
                DmAttempt.next_reconciliation_at <= now,
            )
        )
    )
    sent_attempts = result.scalars().all()

    if not sent_attempts:
        logger.debug("Reconciliation: no accepted DMs to check")
        return {"checked": 0, "newly_failed": 0, "delivered": 0, "unresolved": 0}

    logger.info("Reconciliation: checking %d accepted DM(s)", len(sent_attempts))

    newly_failed = 0
    delivered = 0
    unresolved = 0
    errors = 0

    sem = asyncio.Semaphore(10)

    async def check_dm(attempt):
        nonlocal newly_failed, delivered, unresolved, errors
        async with sem:
            status = await pg_client.get_dm_status(attempt.external_dm_id)

            if status is None:
                errors += 1
                return

            db.add(attempt)

            if status.status == "failed":
                attempt.status = "failed"
                attempt.last_error = "PseudoGram reported delivery failure"
                newly_failed += 1
                logger.warning(
                    "DM %s reconciled as failed (attempt_id=%s user=%s)",
                    attempt.external_dm_id, str(attempt.id), attempt.recipient_user_id,
                )

            elif status.status == "delivered":
                attempt.status = "delivered"
                delivered += 1

            elif status.status == "queued":
                attempt.reconciliation_attempts += 1
                if attempt.reconciliation_attempts >= MAX_RECONCILIATION_ATTEMPTS:
                    attempt.status = "unresolved"
                    attempt.last_error = "Reconciliation timeout: external API stalled in queued state."
                    unresolved += 1
                    logger.warning(
                        "DM %s abandoned as unresolved (attempt_id=%s user=%s).",
                        attempt.external_dm_id, str(attempt.id), attempt.recipient_user_id,
                    )
                else:
                    base_delay = 10 * (2 ** (attempt.reconciliation_attempts - 1))
                    jitter = random.uniform(0.8, 1.2)
                    delay_seconds = base_delay * jitter
                    attempt.next_reconciliation_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)

    tasks = [check_dm(attempt) for attempt in sent_attempts]
    await asyncio.gather(*tasks)

    if newly_failed > 0 or delivered > 0 or unresolved > 0 or len(sent_attempts) > 0:
        await db.commit()

    summary = {
        "checked": len(sent_attempts),
        "newly_failed": newly_failed,
        "delivered": delivered,
        "unresolved": unresolved,
        "errors": errors,
    }
    logger.info("Reconciliation complete: %s", summary)
    return summary
