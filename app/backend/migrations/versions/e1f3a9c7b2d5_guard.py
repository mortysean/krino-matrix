"""guard: usage_days and reports (minor protection, complaints)

Revision ID: e1f3a9c7b2d5
Revises: d4a8e2f7c1b9
Create Date: 2026-11-14 12:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = 'e1f3a9c7b2d5'
down_revision = 'd4a8e2f7c1b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('usage_days',
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('day', sa.String(length=10), nullable=False),
        sa.Column('seconds', sa.Integer(), nullable=False),
        sa.Column('streak_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_ping', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'day'))
    op.create_table('reports',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('reply', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_reports_user_id'), 'reports', ['user_id'], unique=False)
    op.create_index(op.f('ix_reports_created_at'), 'reports', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_reports_created_at'), table_name='reports')
    op.drop_index(op.f('ix_reports_user_id'), table_name='reports')
    op.drop_table('reports')
    op.drop_table('usage_days')
