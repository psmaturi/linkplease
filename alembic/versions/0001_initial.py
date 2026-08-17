"""
Initial migration — creates all LinkPlease tables.

Generated from: app/models/{rule,event,dm_attempt}.py

Every constraint and index is documented with its reason below.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── rules ─────────────────────────────────────────────────────────────────
    # Stores keyword→DM message mappings configured by the operator.
    op.create_table(
        "rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("keyword", sa.String(255), nullable=False),
        sa.Column("dm_message", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Index on keyword: matching_service does "keyword IN comment_text" by
    # fetching all rules and checking in Python (rules are few, ≤1000).
    # Index is still useful for direct keyword lookups.
    op.create_index("ix_rules_keyword", "rules", ["keyword"])

    # ── webhook_events ────────────────────────────────────────────────────────
    # Records every received webhook event. Source of truth for deduplication.
    op.create_table(
        "webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("comment_id", sa.String(255), nullable=False),
        sa.Column("post_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("comment_text", sa.Text, nullable=True),
        sa.Column("raw_payload", postgresql.JSONB, nullable=False),
        sa.Column("is_duplicate", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "received_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # THE deduplication constraint. If two concurrent webhook calls arrive with
    # the same (event_id, event_type), one INSERT wins and one gets
    # UniqueViolation. We catch that and return 200 (idempotent).
    op.create_unique_constraint(
        "uq_event_id_type", "webhook_events", ["event_id", "event_type"]
    )
    op.create_index("ix_webhook_events_event_id", "webhook_events", ["event_id"])
    op.create_index("ix_webhook_events_comment_id", "webhook_events", ["comment_id"])
    op.create_index("ix_webhook_events_user_id", "webhook_events", ["user_id"])

    # ── dm_attempts ───────────────────────────────────────────────────────────
    # Tracks every DM delivery attempt. The business idempotency table.
    op.create_table(
        "dm_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient_user_id", sa.String(255), nullable=False),
        sa.Column("comment_id", sa.String(255), nullable=True),
        sa.Column("external_dm_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "next_retry_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # THE business idempotency constraint.
    # "The same user must never receive the same rule's DM twice."
    # Enforced at DB level: only one row per (rule_id, recipient_user_id) exists.
    op.create_unique_constraint(
        "uq_rule_recipient", "dm_attempts", ["rule_id", "recipient_user_id"]
    )
    op.create_index("ix_dm_attempts_rule_id", "dm_attempts", ["rule_id"])
    op.create_index(
        "ix_dm_attempts_recipient_user_id", "dm_attempts", ["recipient_user_id"]
    )
    # Status index: worker queries WHERE status IN ('queued', 'sending') on startup
    op.create_index("ix_dm_attempts_status", "dm_attempts", ["status"])


def downgrade() -> None:
    op.drop_table("dm_attempts")
    op.drop_table("webhook_events")
    op.drop_table("rules")
