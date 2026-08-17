"""
api/webhook.py — POST /webhook endpoint.

THIS IS THE MOST LATENCY-SENSITIVE ENDPOINT.
Real processing must happen asynchronously.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.config import settings
from app.database import get_db
from app.schemas.webhook import WebhookPayload
from app.services.event_service import ingest_event
from app.utils.security import verify_signature

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_redis() -> aioredis.Redis:
    """FastAPI dependency: yields the shared Redis client."""
    from app.main import redis_client
    return redis_client


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    tags=["webhook"],
    summary="Receive webhook events from PseudoGram",
)
async def receive_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    Handles PseudoGram comment webhook events.
    """
    raw_body = await request.body()

    signature = request.headers.get("X-PseudoGram-Signature", "")
    if not verify_signature(raw_body, signature, settings.webhook_secret):
        logger.warning(
            "Invalid webhook signature from %s",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )

    try:
        data = WebhookPayload.model_validate_json(raw_body)
    except Exception as e:
        logger.error("Failed to parse webhook payload: %s", e)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid payload: {e}",
        )

    logger.info(
        "Received webhook: event_id=%s type=%s user_id=%s comment_id=%s",
        data.event_id,
        data.event_type,
        data.comment.user_id,
        data.comment.comment_id,
    )

    result = await ingest_event(data, raw_body, db, redis)

    return {"status": result["status"]}
