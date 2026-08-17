"""
models/event.py — Records every received webhook event.
"""

import uuid

from sqlalchemy import String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    __table_args__ = (
        UniqueConstraint("event_id", "event_type", name="uq_event_id_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    comment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    post_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    comment_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    received_at: Mapped[str] = mapped_column(
        server_default=func.now(), nullable=False
    )
