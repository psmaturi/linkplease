"""
models/rule.py — The Rule table stores keyword→DM mappings.
"""

import uuid

from sqlalchemy import String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    keyword: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    dm_message: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[str] = mapped_column(
        server_default=func.now(), nullable=False
    )
