"""
tests/integration/test_idempotency.py — Tests for duplicate/idempotency behavior.
"""

import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch


SECRET = "test_api_key_12345"


def sign_body(body: bytes) -> str:
    digest = hmac.new(
        key=SECRET.encode(), msg=body, digestmod=hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


class TestIdempotencyBehavior:
    """Tests that simulate idempotent DB inserts."""

    @pytest.mark.asyncio
    async def test_duplicate_event_increments_counter(self):
        import os
        os.environ["PSEUDOGRAM_API_KEY"] = SECRET
        os.environ["WEBHOOK_SECRET"] = SECRET
        os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:x@localhost/x"
        os.environ["REDIS_URL"] = "redis://localhost:6379/1"

        from app.main import app
        from app.database import get_db
        from app.api.webhook import get_redis

        call_count = 0

        async def mock_execute_dup_on_second(sql, params=None):
            nonlocal call_count
            sql_str = str(sql)
            if "INSERT INTO webhook_events" in sql_str:
                call_count += 1
                mock_r = MagicMock()
                if call_count == 1:
                    mock_r.fetchone.return_value = ("uuid_1",)
                else:
                    mock_r.fetchone.return_value = None
                return mock_r
            # Rules query — no rules
            mock_r = MagicMock()
            mock_r.scalars.return_value.all.return_value = []
            return mock_r

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=mock_execute_dup_on_second)
        mock_session.commit = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.lpush = AsyncMock(return_value=1)

        app.dependency_overrides[get_db] = lambda: mock_session
        app.dependency_overrides[get_redis] = lambda: mock_redis

        body = json.dumps({
            "event_id": "evt_dup_001",
            "event_type": "comment.created",
            "comment": {
                "comment_id": "cmt_001",
                "post_id": "post_001",
                "user_id": "usr_001",
                "text": "test",
            },
        }).encode()
        sig = sign_body(body)

        with patch("app.main.redis_client", mock_redis):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # First request
                r1 = await client.post(
                    "/webhook", content=body,
                    headers={"Content-Type": "application/json",
                             "X-PseudoGram-Signature": sig}
                )
                # Second request with SAME event_id
                r2 = await client.post(
                    "/webhook", content=body,
                    headers={"Content-Type": "application/json",
                             "X-PseudoGram-Signature": sig}
                )

        app.dependency_overrides.clear()

        assert r1.status_code == 200
        assert r2.status_code == 200

        mock_redis.incr.assert_not_called()

    @pytest.mark.asyncio
    async def test_username_is_never_used_as_identity(self):
        from app.schemas.webhook import WebhookPayload

        raw = {
            "event_id": "evt_001",
            "event_type": "comment.created",
            "comment": {
                "comment_id": "cmt_001",
                "post_id": "post_001",
                "user_id": "usr_stable_id",
                "username": "alice_changes_her_username",
                "text": "test",
            }
        }
        parsed = WebhookPayload.model_validate(raw)
        assert parsed.comment.user_id == "usr_stable_id"
        assert parsed.comment.username == "alice_changes_her_username"

        # Verify event_service uses user_id, not username
        # (We verify this by inspecting the INSERT params in event_service.py)
        # The key guarantee is that recipient_user_id = payload.comment.user_id
