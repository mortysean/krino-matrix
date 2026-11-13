"""api_keys: developer API keys created in Settings

Revision ID: d4a8e2f7c1b9
Revises: c7f2d9a1e3b4
Create Date: 2026-11-14 10:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = 'd4a8e2f7c1b9'
down_revision = 'c7f2d9a1e3b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('api_keys',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('prefix', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_hash'))
    op.create_index(op.f('ix_api_keys_user_id'), 'api_keys', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_api_keys_user_id'), table_name='api_keys')
    op.drop_table('api_keys')
