"""bond feelings: trust, and a knot in her heart (what hurt her and when)

Revision ID: b8d1f4a6c3e9
Revises: a3c9e5f1b7d2
Create Date: 2026-11-19 14:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = 'b8d1f4a6c3e9'
down_revision = 'a3c9e5f1b7d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bonds', sa.Column('trust', sa.Float(), server_default='50', nullable=False))
    op.add_column('bonds', sa.Column('hurt', sa.Text(), nullable=True))
    op.add_column('bonds', sa.Column('hurt_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('bonds', 'hurt_at')
    op.drop_column('bonds', 'hurt')
    op.drop_column('bonds', 'trust')
