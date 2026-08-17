"""
utils/retry.py — Retry logic for calling the PseudoGram API.
"""

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class RetryOutcome(str, Enum):
    """Result of a single attempt."""
    SUCCESS = "success"
    RETRYABLE = "retryable"
    RATE_LIMITED = "rate_limited"
    PERMANENT_FAILURE = "permanent_failure"


@dataclass
class RetryConfig:
    """Tunable retry parameters."""
    max_attempts: int = 5
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    timeout_seconds: float = 10.0


async def with_exponential_backoff(
    coro_factory,
    config: RetryConfig | None = None,
    attempt_label: str = "",
):
    """
    Call coro_factory() repeatedly until it succeeds or we exhaust attempts.

    coro_factory must return a tuple: (RetryOutcome, result_or_error, retry_after)
    where retry_after is the number of seconds to wait (only for RATE_LIMITED).

    Returns the result on SUCCESS, raises RuntimeError on permanent failure,
    or raises RuntimeError after max_attempts retryable failures.
    """
    cfg = config or RetryConfig()
    backoff = cfg.base_backoff_seconds

    for attempt in range(1, cfg.max_attempts + 1):
        outcome, result, retry_after = await coro_factory()

        if outcome == RetryOutcome.SUCCESS:
            return result

        if outcome == RetryOutcome.PERMANENT_FAILURE:
            logger.error(
                "Permanent failure on %s (attempt %d): %s",
                attempt_label, attempt, result
            )
            raise RuntimeError(f"Permanent failure: {result}")

        if outcome == RetryOutcome.RATE_LIMITED:
            wait = retry_after or 60
            logger.warning(
                "Rate limited on %s — waiting %ss (attempt %d/%d)",
                attempt_label, wait, attempt, cfg.max_attempts
            )
            await asyncio.sleep(wait)
            continue

        if attempt < cfg.max_attempts:
            logger.warning(
                "Retryable failure on %s (attempt %d/%d) — backing off %ss: %s",
                attempt_label, attempt, cfg.max_attempts, backoff, result
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, cfg.max_backoff_seconds)
        else:
            logger.error(
                "All %d attempts failed for %s: %s",
                cfg.max_attempts, attempt_label, result
            )
            raise RuntimeError(f"All {cfg.max_attempts} attempts failed: {result}")
