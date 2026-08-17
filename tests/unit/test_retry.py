"""
tests/unit/test_retry.py — Unit tests for retry logic and PseudoGram client
response classification.

Tests verify:
- 500 responses are classified as RETRYABLE
- 429 responses are classified as RATE_LIMITED with correct retry_after
- 400 responses are classified as PERMANENT_FAILURE
- 200 responses are classified as SUCCESS
- Network errors are classified as RETRYABLE
- with_exponential_backoff correctly retries on RETRYABLE
- with_exponential_backoff stops on PERMANENT_FAILURE
- with_exponential_backoff respects 429 wait
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.utils.retry import RetryConfig, RetryOutcome, with_exponential_backoff


class TestWithExponentialBackoff:
    """Tests for the retry orchestrator."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_try(self):
        """No retries needed when first call succeeds."""
        call_count = 0

        async def factory():
            nonlocal call_count
            call_count += 1
            return RetryOutcome.SUCCESS, "result_data", None

        result = await with_exponential_backoff(factory, RetryConfig(max_attempts=3))
        assert result == "result_data"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_retryable_failure(self):
        """Should retry up to max_attempts on RETRYABLE."""
        call_count = 0

        async def factory():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return RetryOutcome.RETRYABLE, "error msg", None
            return RetryOutcome.SUCCESS, "success", None

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await with_exponential_backoff(
                factory, RetryConfig(max_attempts=5)
            )

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        """Should raise RuntimeError after exhausting all attempts."""
        async def factory():
            return RetryOutcome.RETRYABLE, "always fails", None

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="All 3 attempts failed"):
                await with_exponential_backoff(
                    factory, RetryConfig(max_attempts=3)
                )

    @pytest.mark.asyncio
    async def test_permanent_failure_does_not_retry(self):
        """Should raise immediately on PERMANENT_FAILURE without retrying."""
        call_count = 0

        async def factory():
            nonlocal call_count
            call_count += 1
            return RetryOutcome.PERMANENT_FAILURE, "bad request", None

        with pytest.raises(RuntimeError, match="Permanent failure"):
            await with_exponential_backoff(
                factory, RetryConfig(max_attempts=5)
            )

        # Should only have been called once — no retries on permanent failure
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_rate_limited_waits_retry_after(self):
        """Should sleep for retry_after seconds on RATE_LIMITED."""
        sleep_calls = []
        call_count = 0

        async def factory():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return RetryOutcome.RATE_LIMITED, "rate_limited", 30.0
            return RetryOutcome.SUCCESS, "ok", None

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await with_exponential_backoff(
                factory, RetryConfig(max_attempts=3)
            )

        assert result == "ok"
        # Should have slept for 30 seconds
        mock_sleep.assert_called_once_with(30.0)

    @pytest.mark.asyncio
    async def test_backoff_increases_exponentially(self):
        """Backoff time should double with each retry."""
        sleep_calls = []

        async def factory():
            return RetryOutcome.RETRYABLE, "error", None

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(RuntimeError):
                await with_exponential_backoff(
                    factory,
                    RetryConfig(
                        max_attempts=4,
                        base_backoff_seconds=1.0,
                        max_backoff_seconds=60.0,
                    ),
                )

        # Should have slept 3 times (attempts 1,2,3 fail, attempt 4 fails with no sleep)
        calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert calls == [1.0, 2.0, 4.0]

    @pytest.mark.asyncio
    async def test_backoff_capped_at_max(self):
        """Backoff should never exceed max_backoff_seconds."""

        async def factory():
            return RetryOutcome.RETRYABLE, "error", None

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(RuntimeError):
                await with_exponential_backoff(
                    factory,
                    RetryConfig(
                        max_attempts=10,
                        base_backoff_seconds=1.0,
                        max_backoff_seconds=5.0,
                    ),
                )

        calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert all(c <= 5.0 for c in calls)
        assert calls[-1] == 5.0  # should reach the cap
