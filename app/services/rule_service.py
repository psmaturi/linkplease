"""
services/rule_service.py — CRUD operations for Rules.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rule import Rule
from app.schemas.rule import RuleCreate, RuleResponse

logger = logging.getLogger(__name__)


async def create_rule(payload: RuleCreate, db: AsyncSession) -> RuleResponse:
    """
    Insert a new rule into the database and return it.

    The keyword is normalised to lowercase before storage.
    """
    rule = Rule(
        id=uuid.uuid4(),
        keyword=payload.keyword.lower().strip(),
        dm_message=payload.dm_message,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    logger.info("Created rule id=%s keyword=%s", rule.id, rule.keyword)

    return RuleResponse(
        rule_id=str(rule.id),
        keyword=rule.keyword,
        dm_message=rule.dm_message,
    )
