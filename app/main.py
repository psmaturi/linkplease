"""
app/main.py — FastAPI application entry point.

Responsibilities:
  1. Create the FastAPI app.
  2. Register all routers (webhook, rules, stats, health).
  3. Manage application lifespan.
  4. Configure structured logging.
"""

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from app.config import settings

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

redis_client: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Code before `yield` runs on startup; code after `yield` runs on shutdown.
    """
    global redis_client

    logger.info("LinkPlease starting up...")

    redis_client = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=20,
    )
    await redis_client.ping()
    logger.info("Redis connected: %s", settings.redis_url)



    logger.info("LinkPlease ready")

    yield

    logger.info("LinkPlease shutting down...")

    if redis_client:
        await redis_client.aclose()
        logger.info("Redis connection closed")

    from app.database import engine
    await engine.dispose()
    logger.info("Database connections closed")

    logger.info("LinkPlease stopped cleanly")


app = FastAPI(
    title="LinkPlease",
    description="Automates Instagram creator DMs when users comment keywords.",
    version="1.0.0",
    lifespan=lifespan,
)

from app.api.health import router as health_router
from app.api.rules import router as rules_router
from app.api.stats import router as stats_router
from app.api.webhook import router as webhook_router

app.include_router(health_router)
app.include_router(webhook_router)
app.include_router(rules_router)
app.include_router(stats_router)


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "LinkPlease", "docs": "/docs"}
