"""
api/rules.py — POST /rules endpoint.
"""

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.rule import RuleCreate, RuleResponse
from app.services.rule_service import create_rule

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/rules",
    response_model=RuleResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["rules"],
    summary="Create a new keyword→DM rule",
)
async def create_rule_endpoint(
    payload: RuleCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a rule that sends a DM when a comment contains the keyword.
    """
    logger.info("Creating rule: keyword=%s", payload.keyword)
    return await create_rule(payload, db)
