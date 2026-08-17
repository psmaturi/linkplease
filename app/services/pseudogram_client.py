"""
services/pseudogram_client.py — HTTP client for the PseudoGram API.
"""

import logging
from dataclasses import dataclass

import httpx

from app.config import settings
from app.utils.retry import RetryOutcome

logger = logging.getLogger(__name__)


@dataclass
class SendDMResult:
    """Result of a single POST /v1/dm/send call."""
    outcome: RetryOutcome
    dm_id: str | None = None
    error: str | None = None
    retry_after: float | None = None


@dataclass
class DMStatus:
    """Result of a GET /v1/dm/{dm_id} call."""
    dm_id: str
    status: str
    recipient_user_id: str
    updated_at: str


class PseudogramClient:
    """
    Async HTTP client for the PseudoGram external API.

    Instantiate once at application startup and share across workers.
    """

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=settings.pseudogram_base_url,
            headers={
                "x-api-key": settings.pseudogram_api_key,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(10.0),  # 10s per request
        )

    async def send_dm(
        self,
        recipient_user_id: str,
        message: str,
        comment_id: str | None,
        dm_attempt_id: str,
    ) -> SendDMResult:
        """
        POST /v1/dm/send — send a DM via PseudoGram.

        Returns a SendDMResult describing what happened.
        The caller is responsible for retry logic (see delivery_worker.py).
        """
        payload = {
            "recipient_user_id": recipient_user_id,
            "message": message,
        }
        if comment_id:
            payload["comment_id"] = comment_id

        try:
            response = await self._client.post(
                "/v1/dm/send",
                json=payload,
                headers={"Idempotency-Key": dm_attempt_id},
            )
        except httpx.TimeoutException as e:
            logger.warning("Timeout calling PseudoGram send_dm: %s", e)
            return SendDMResult(outcome=RetryOutcome.RETRYABLE, error=str(e))
        except httpx.RequestError as e:
            logger.warning("Network error calling PseudoGram send_dm: %s", e)
            return SendDMResult(outcome=RetryOutcome.RETRYABLE, error=str(e))

        if response.status_code in (200, 202):
            data = response.json()
            dm_id = data.get("dm_id")
            logger.info(
                "PseudoGram accepted DM for %s — dm_id=%s",
                recipient_user_id, dm_id
            )
            return SendDMResult(outcome=RetryOutcome.SUCCESS, dm_id=dm_id)

        if response.status_code == 429:
            retry_after = float(
                response.headers.get("Retry-After", "60")
            )
            logger.warning(
                "PseudoGram rate limited — Retry-After: %ss", retry_after
            )
            return SendDMResult(
                outcome=RetryOutcome.RATE_LIMITED,
                error="rate_limited",
                retry_after=retry_after,
            )

        if response.status_code == 500:
            body = response.text[:200]
            logger.warning("PseudoGram 500 error: %s", body)
            return SendDMResult(
                outcome=RetryOutcome.RETRYABLE,
                error=f"HTTP 500: {body}",
            )

        if response.status_code == 400:
            body = response.text[:200]
            logger.error("PseudoGram 400 (permanent failure): %s", body)
            return SendDMResult(
                outcome=RetryOutcome.PERMANENT_FAILURE,
                error=f"HTTP 400: {body}",
            )

        body = response.text[:200]
        logger.warning("Unexpected PseudoGram status %d: %s", response.status_code, body)
        return SendDMResult(
            outcome=RetryOutcome.RETRYABLE,
            error=f"HTTP {response.status_code}: {body}",
        )

    async def get_dm_status(self, dm_id: str) -> DMStatus | None:
        """
        GET /v1/dm/{dm_id} — check delivery status of a sent DM.

        Returns None if the request fails (caller should try again later).
        """
        try:
            response = await self._client.get(f"/v1/dm/{dm_id}")
        except httpx.RequestError as e:
            logger.warning("Network error checking DM status for %s: %s", dm_id, e)
            return None

        if response.status_code == 200:
            data = response.json()
            return DMStatus(
                dm_id=data["dm_id"],
                status=data["status"],
                recipient_user_id=data.get("recipient_user_id", ""),
                updated_at=data.get("updated_at", ""),
            )

        logger.warning(
            "Unexpected status %d checking DM %s", response.status_code, dm_id
        )
        return None

    async def close(self):
        """Close the underlying HTTP connection pool."""
        await self._client.aclose()
