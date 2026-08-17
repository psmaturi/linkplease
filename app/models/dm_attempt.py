"""
models/dm_attempt.py — Tracks every DM delivery attempt.
"""

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DmAttempt(Base):
    __tablename__ = "dm_attempts"

    __table_args__ = (
        UniqueConstraint("rule_id", "recipient_user_id", name="uq_rule_recipient"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    recipient_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    comment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_dm_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[str | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    reconciliation_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_reconciliation_at: Mapped[str | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    created_at: Mapped[str] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[str] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
