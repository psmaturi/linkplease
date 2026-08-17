"""
tests/integration/test_webhook.py — Integration tests for POST /webhook.
"""

import hashlib
import hmac
import json

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch


SECRET = "test_api_key_12345"


def sign_body(body: bytes) -> str:
    digest = hmac.new(
        key=SECRET.encode(), msg=body, digestmod=hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def payload(**kwargs) -> bytes:
    data = {
        "event_id": "evt_001",
        "event_type": "comment.created",
        "comment": {
            "comment_id": "cmt_001",
            "post_id": "post_001",
            "user_id": "usr_001",
            "username": "alice",
            "text": "What is the PRICE?",
        },
        **kwargs,
    }
    return json.dumps(data).encode()


@pytest_asyncio.fixture
async def app_client():
    import os
    os.environ["PSEUDOGRAM_API_KEY"] = SECRET
    os.environ["WEBHOOK_SECRET"] = SECRET
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://x:x@localhost/x"
    os.environ["REDIS_URL"] = "redis://localhost:6379/1"

    from app.main import app
    from app.database import get_db
    from app.api.webhook import get_redis

    mock_session = AsyncMock()
    mock_insert_result = MagicMock()
    mock_insert_result.fetchone.return_value = ("fake_uuid",)
    mock_rules_result = MagicMock()
    mock_rules_result.scalars.return_value.all.return_value = []

    async def mock_execute(sql, params=None):
        sql_str = str(sql)
        if "INSERT INTO webhook_events" in sql_str:
            return mock_insert_result
        if "INSERT INTO dm_attempts" in sql_str:
            mock_dm_result = MagicMock()
            mock_dm_result.fetchone.return_value = ("dm_uuid",)
            return mock_dm_result
        return mock_rules_result

    mock_session.execute = AsyncMock(side_effect=mock_execute)
    mock_session.commit = AsyncMock()

    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.lpush = AsyncMock(return_value=1)

    app.dependency_overrides[get_db] = lambda: mock_session
    app.dependency_overrides[get_redis] = lambda: mock_redis

    with patch("app.main.redis_client", mock_redis):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, mock_session, mock_redis

    app.dependency_overrides.clear()


class TestWebhookEndpoint:
    @pytest.mark.asyncio
    async def test_valid_event_returns_200(self, app_client):
        client, db, redis = app_client
        body = payload()
        response = await client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-PseudoGram-Signature": sign_body(body),
            },
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_401(self, app_client):
        client, db, redis = app_client
        body = payload()
        response = await client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-PseudoGram-Signature": "sha256=invalid_signature_here",
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_signature_returns_401(self, app_client):
        client, db, redis = app_client
        body = payload()
        response = await client.post(
            "/webhook",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_deleted_event_returns_200(self, app_client):
        client, db, redis = app_client
        body = payload(event_type="comment.deleted")
        response = await client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-PseudoGram-Signature": sign_body(body),
            },
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_response_time_is_fast(self, app_client):
        import time
        client, db, redis = app_client
        body = payload()
        start = time.monotonic()
        response = await client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-PseudoGram-Signature": sign_body(body),
            },
        )
        elapsed = time.monotonic() - start
        assert response.status_code == 200
        assert elapsed < 1.0, f"Webhook took {elapsed:.2f}s — too slow"
