"""
database.py — SQLAlchemy async engine and session factory.

Why async:
  The webhook handler must return within 5 seconds. Using async DB access means
  we never block the event loop while waiting for a query to complete.

Why connection pooling:
  Opening a new TCP connection to PostgreSQL per request is expensive (≈10ms).
  A pool reuses connections. pool_size=10 matches the number of uvicorn workers
  times expected concurrency. pool_pre_ping=True detects stale connections.

Crash safety:
  Sessions are used as context managers; they always commit or rollback even
  if the process receives a signal during a request.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# pool_pre_ping=True: before reusing a connection, issue "SELECT 1".
# This handles the case where PostgreSQL restarted while our app was idle.
engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,  # set to True only for debugging SQL; never in production
)

# async_sessionmaker produces AsyncSession objects.
# expire_on_commit=False: after commit() the objects remain usable without
# issuing another SELECT. Important in async code where you may access
# attributes after the session has committed.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """All SQLAlchemy models inherit from this base."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency: yields a database session per request.

    The try/finally guarantees the session is closed even if the handler
    raises an exception. SQLAlchemy rolls back uncommitted transactions
    automatically when the session is closed without an explicit commit.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
