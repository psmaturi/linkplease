"""
tests/conftest.py — Shared test fixtures.
"""

import asyncio
import hashlib
import hmac
import pytest
import pytest_asyncio

from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock


# ── Event loop ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


# ── Test settings (override before importing app) ─────────────────────────────
@pytest.fixture(autouse=True, scope="session")
def test_settings(monkeypatch_session=None):
    import os
    os.environ.setdefault("PSEUDOGRAM_API_KEY", "test_api_key_12345")
    os.environ.setdefault("WEBHOOK_SECRET", "test_api_key_12345")
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://linkplease:linkplease_dev@localhost:5432/linkplease_test"
    )
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")  # DB 1 for tests


def make_signature(body: bytes, secret: str = "test_api_key_12345") -> str:
    digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def make_webhook_payload(
    event_id: str = "evt_001",
    event_type: str = "comment.created",
    comment_id: str = "cmt_001",
    post_id: str = "post_001",
    user_id: str = "usr_001",
    text: str = "I want to know the PRICE please",
) -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "comment": {
            "comment_id": comment_id,
            "post_id": post_id,
            "user_id": user_id,
            "username": "someuser",
            "text": text,
        },
    }


# ── Mocked app client (no real DB/Redis) ─────────────────────────────────────
@pytest_asyncio.fixture
async def mock_app_client():
    from app.main import app
    from app.database import get_db
    from app.api.webhook import get_redis
    from app.api.stats import get_redis as stats_get_redis

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    mock_redis = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[stats_get_redis] = lambda: mock_redis

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, mock_db, mock_redis

    app.dependency_overrides.clear()
