"""outbox_and_duplicates

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-16 18:43:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Remove is_duplicate from webhook_events
    op.drop_column('webhook_events', 'is_duplicate')

    # Create outbox_events table
    op.create_table('outbox_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('dm_attempt_id', sa.String(), nullable=False),
        sa.Column('published', sa.Boolean(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_outbox_events_dm_attempt_id'), 'outbox_events', ['dm_attempt_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_outbox_events_dm_attempt_id'), table_name='outbox_events')
    op.drop_table('outbox_events')
    op.add_column('webhook_events', sa.Column('is_duplicate', sa.BOOLEAN(), autoincrement=False, nullable=True))
