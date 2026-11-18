"""visits: the owner walking into the town to be with one of her souls

Revision ID: a3c9e5f1b7d2
Revises: f2b6c8d4a1e7
Create Date: 2026-11-19 12:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = 'a3c9e5f1b7d2'
down_revision = 'f2b6c8d4a1e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('visits',
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('character_id', sa.String(length=32), nullable=False),
        sa.Column('place', sa.String(length=16), nullable=False),
        sa.Column('how', sa.String(length=8), nullable=False),
        sa.Column('session_id', sa.String(length=32), nullable=True),
        sa.Column('since', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'))
    op.create_index(op.f('ix_visits_character_id'), 'visits', ['character_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_visits_character_id'), table_name='visits')
    op.drop_table('visits')
