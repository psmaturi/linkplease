"""
services/matching_service.py — Finds which rules match a comment.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rule import Rule

logger = logging.getLogger(__name__)


async def find_matching_rules(
    comment_text: str,
    db: AsyncSession,
) -> list[Rule]:
    """
    Return all rules whose keyword appears (case-insensitively) in comment_text.
    """
    if not comment_text:
        return []

    comment_lower = comment_text.lower()

    result = await db.execute(select(Rule))
    rules = result.scalars().all()

    matching = [
        rule
        for rule in rules
        if rule.keyword in comment_lower
    ]

    if matching:
        logger.info(
            "Comment matched %d rule(s): %s",
            len(matching),
            [r.keyword for r in matching],
        )

    return matching
