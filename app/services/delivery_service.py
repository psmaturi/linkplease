"""
services/delivery_service.py — Executes a single DM delivery attempt.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.config import settings
from app.models.dm_attempt import DmAttempt
from app.models.rule import Rule
from app.services.pseudogram_client import PseudogramClient
from app.utils.rate_limiter import SlidingWindowRateLimiter
from app.utils.retry import RetryOutcome

logger = logging.getLogger(__name__)


async def deliver_dm(
    attempt_id: str,
    db: AsyncSession,
    redis_client: aioredis.Redis,
    pg_client: PseudogramClient,
    rate_limiter: SlidingWindowRateLimiter,
) -> str:
    """
    Attempt to deliver one DM. Returns the final status.
    """
    result = await db.execute(
        select(DmAttempt).where(DmAttempt.id == uuid.UUID(attempt_id))
    )
    attempt = result.scalar_one_or_none()

    if attempt is None:
        logger.warning("dm_attempt %s not found in DB — skipping", attempt_id)
        return "not_found"

    if attempt.status not in ("queued", "sending"):
        logger.info(
            "dm_attempt %s is already %s — skipping", attempt_id, attempt.status
        )
        return attempt.status

    if attempt.attempt_count >= settings.max_dm_retries:
        await _mark_failed(attempt, "Max retries exceeded", db)
        return "failed"

    if attempt.next_retry_at:
        retry_at = attempt.next_retry_at
        if isinstance(retry_at, str):
            retry_at = datetime.fromisoformat(retry_at)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now < retry_at:
            wait_seconds = (retry_at - now).total_seconds()
            logger.info(
                "dm_attempt %s not ready yet (%.1fs remaining) — re-queuing",
                attempt_id, wait_seconds
            )
            await redis_client.lpush(settings.delivery_queue_key, attempt_id)
            return "queued"

    rule_result = await db.execute(
        select(Rule).where(Rule.id == attempt.rule_id)
    )
    rule = rule_result.scalar_one_or_none()

    if rule is None:
        await _mark_failed(attempt, "Associated rule not found", db)
        return "failed"

    await db.execute(
        text("""
            UPDATE dm_attempts
            SET status = 'sending',
                attempt_count = attempt_count + 1,
                updated_at = now()
            WHERE id = :id
        """),
        {"id": str(attempt.id)},
    )
    await db.commit()

    await rate_limiter.acquire()

    send_result = await pg_client.send_dm(
        recipient_user_id=attempt.recipient_user_id,
        message=rule.dm_message,
        comment_id=attempt.comment_id,
        dm_attempt_id=str(attempt.id),
    )

    if send_result.outcome == RetryOutcome.SUCCESS:
        await db.execute(
            text("""
                UPDATE dm_attempts
                SET status = 'accepted',
                    external_dm_id = :dm_id,
                    last_error = NULL,
                    next_retry_at = NULL,
                    updated_at = now()
                WHERE id = :id
            """),
            {"dm_id": send_result.dm_id, "id": str(attempt.id)},
        )
        await db.commit()
        logger.info(
            "DM sent: attempt_id=%s dm_id=%s user=%s",
            attempt_id, send_result.dm_id, attempt.recipient_user_id,
        )
        return "sent"

    if send_result.outcome == RetryOutcome.PERMANENT_FAILURE:
        await _mark_failed(attempt, send_result.error or "permanent failure", db)
        return "failed"

    if send_result.outcome == RetryOutcome.RATE_LIMITED:
        retry_after = send_result.retry_after or 60
        from datetime import timedelta
        next_retry = datetime.now(timezone.utc) + timedelta(seconds=retry_after)
        await db.execute(
            text("""
                UPDATE dm_attempts
                SET status = 'queued',
                    last_error = :error,
                    next_retry_at = :next_retry_at,
                    updated_at = now()
                WHERE id = :id
            """),
            {
                "error": "rate_limited",
                "next_retry_at": next_retry.isoformat(),
                "id": str(attempt.id),
            },
        )
        await db.commit()
        await redis_client.lpush(settings.delivery_queue_key, attempt_id)
        return "queued"

    new_count = attempt.attempt_count + 1
    if new_count >= settings.max_dm_retries:
        await _mark_failed(
            attempt, send_result.error or "retryable failure exhausted", db
        )
        return "failed"

    await db.execute(
        text("""
            UPDATE dm_attempts
            SET status = 'queued',
                last_error = :error,
                updated_at = now()
            WHERE id = :id
        """),
        {"error": send_result.error, "id": str(attempt.id)},
    )
    await db.commit()
    await redis_client.lpush(settings.delivery_queue_key, attempt_id)
    logger.warning(
        "DM attempt %s failed (attempt %d/%d) — re-queued: %s",
        attempt_id, new_count, settings.max_dm_retries, send_result.error,
    )
    return "queued"


async def _mark_failed(
    attempt: DmAttempt,
    error: str,
    db: AsyncSession,
) -> None:
    """Mark a dm_attempt as permanently failed."""
    await db.execute(
        text("""
            UPDATE dm_attempts
            SET status = 'failed',
                last_error = :error,
                next_retry_at = NULL,
                updated_at = now()
            WHERE id = :id
        """),
        {"error": error[:500], "id": str(attempt.id)},
    )
    await db.commit()
    logger.error(
        "DM attempt %s permanently failed: %s", str(attempt.id), error
    )
