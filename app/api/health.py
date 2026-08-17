"""
api/health.py — Simple health check endpoint.

WHY a health endpoint:
  Docker healthchecks, load balancers, and monitoring tools use this to
  determine if the application is running. Without it, a Docker container
  that starts but fails internally looks healthy.

  This health check verifies:
  - The application process is alive (trivially: it responded)
  - The database is reachable (SELECT 1)

WHY we check the DB in the health endpoint:
  A process can be "up" but unable to serve requests if the DB is unreachable.
  Returning 503 in that case lets the orchestrator restart or reroute traffic.
"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health", tags=["operations"])
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Returns 200 if the application and database are healthy.
    Returns 503 if the database is unreachable.
    """
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}
    except Exception as e:
        logger.error("Health check DB failure: %s", e)
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unreachable"},
        )
