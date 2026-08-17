"""
api/stats.py — GET /stats endpoint.
"""

import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.dm_attempt import DmAttempt
from app.schemas.stats import StatsResponse

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_redis() -> aioredis.Redis:
    """FastAPI dependency: yields a Redis client."""
    from app.main import redis_client  # imported here to avoid circular imports
    return redis_client


@router.get(
    "/stats",
    response_model=StatsResponse,
    tags=["stats"],
    summary="Get delivery statistics",
)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    Returns accurate, database-derived delivery statistics.
    """
    result = await db.execute(
        select(
            func.count(DmAttempt.id).filter(DmAttempt.status == "delivered").label("sent"),
            func.count(DmAttempt.id).filter(DmAttempt.status == "failed").label("failed"),
            func.count(DmAttempt.id)
            .filter(DmAttempt.status.in_(["queued", "sending", "accepted", "unresolved"]))
            .label("queued"),
        )
    )
    row = result.one()

    try:
        dup_raw = await redis.get("stats:duplicates_blocked")
        duplicates_blocked = int(dup_raw) if dup_raw else 0
    except Exception:
        duplicates_blocked = 0

    return StatsResponse(
        sent=row.sent or 0,
        failed=row.failed or 0,
        queued=row.queued or 0,
        duplicates_blocked=duplicates_blocked,
    )
