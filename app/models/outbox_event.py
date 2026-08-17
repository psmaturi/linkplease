"""
models/outbox_event.py — Transactional Outbox pattern.
"""
import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    dm_attempt_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
