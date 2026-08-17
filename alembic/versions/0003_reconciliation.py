"""bounded_reconciliation

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-16 19:05:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('dm_attempts', sa.Column('reconciliation_attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('dm_attempts', sa.Column('next_reconciliation_at', sa.TIMESTAMP(timezone=True), nullable=True))

def downgrade() -> None:
    op.drop_column('dm_attempts', 'next_reconciliation_at')
    op.drop_column('dm_attempts', 'reconciliation_attempts')
