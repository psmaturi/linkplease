"""
services/event_service.py — Webhook event ingestion.
"""

import json
import logging
import uuid

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.rule import Rule
from app.schemas.webhook import WebhookPayload

logger = logging.getLogger(__name__)


async def ingest_event(
    payload: WebhookPayload,
    raw_body: bytes,
    db: AsyncSession,
    redis_client: aioredis.Redis,
) -> dict:
    """
    Ingest a webhook event. Returns a dict with ingestion metadata.
    """
    insert_event_sql = text("""
        INSERT INTO webhook_events
            (id, event_id, event_type, comment_id, post_id,
             user_id, comment_text, raw_payload)
        VALUES
            (:id, :event_id, :event_type, :comment_id, :post_id,
             :user_id, :comment_text, :raw_payload)
        ON CONFLICT (event_id, event_type) DO NOTHING
        RETURNING id
    """)

    result = await db.execute(
        insert_event_sql,
        {
            "id": str(uuid.uuid4()),
            "event_id": payload.event_id,
            "event_type": payload.event_type,
            "comment_id": payload.comment.comment_id,
            "post_id": payload.comment.post_id,
            "user_id": payload.comment.user_id,   # identity — not username
            "comment_text": payload.comment.text,
            "raw_payload": json.dumps(json.loads(raw_body.decode())),
        },
    )
    inserted_row = result.fetchone()

    if inserted_row is None:
        logger.info(
            "Duplicate event blocked: event_id=%s type=%s",
            payload.event_id, payload.event_type
        )
        return {"status": "duplicate", "queued": 0}

    if payload.event_type == "comment.deleted":
        await db.commit()
        logger.info(
            "comment.deleted event recorded (no DM needed): comment_id=%s",
            payload.comment.comment_id,
        )
        return {"status": "deleted", "queued": 0}

    from app.services.matching_service import find_matching_rules

    matching_rules: list[Rule] = await find_matching_rules(
        payload.comment.text, db
    )

    if not matching_rules:
        await db.commit()
        logger.info(
            "No rules matched comment_id=%s text=%r",
            payload.comment.comment_id,
            (payload.comment.text or "")[:50],
        )
        return {"status": "accepted", "queued": 0}

    new_attempt_ids = []
    for rule in matching_rules:
        attempt_id = str(uuid.uuid4())
        insert_attempt_sql = text("""
            INSERT INTO dm_attempts
                (id, rule_id, recipient_user_id, comment_id, status, attempt_count)
            VALUES
                (:id, :rule_id, :recipient_user_id, :comment_id, 'queued', 0)
            ON CONFLICT (rule_id, recipient_user_id) DO NOTHING
            RETURNING id
        """)
        res = await db.execute(
            insert_attempt_sql,
            {
                "id": attempt_id,
                "rule_id": str(rule.id),
                "recipient_user_id": payload.comment.user_id,
                "comment_id": payload.comment.comment_id,
            },
        )
        if res.fetchone():
            new_attempt_ids.append(attempt_id)
            outbox_sql = text("""
                INSERT INTO outbox_events (id, dm_attempt_id, published)
                VALUES (:id, :dm_attempt_id, false)
            """)
            await db.execute(outbox_sql, {"id": str(uuid.uuid4()), "dm_attempt_id": attempt_id})
        else:
            await redis_client.incr("stats:duplicates_blocked")

    await db.commit()

    if new_attempt_ids:
        await redis_client.lpush(settings.delivery_queue_key, *new_attempt_ids)
        logger.info(
            "Queued %d DM attempt(s) for user=%s comment_id=%s",
            len(new_attempt_ids),
            payload.comment.user_id,
            payload.comment.comment_id,
        )

    return {"status": "accepted", "queued": len(new_attempt_ids)}
