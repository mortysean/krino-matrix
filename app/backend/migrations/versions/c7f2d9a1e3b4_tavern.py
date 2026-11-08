"""tavern: the owner's own characters chatting in one room

Revision ID: c7f2d9a1e3b4
Revises: b5e1c0a4d921
Create Date: 2026-11-09 10:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = 'c7f2d9a1e3b4'
down_revision = 'b5e1c0a4d921'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('tavern_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('author_id', sa.String(length=32), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_tavern_messages_user_id'), 'tavern_messages', ['user_id'], unique=False)
    op.create_index(op.f('ix_tavern_messages_created_at'), 'tavern_messages', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tavern_messages_created_at'), table_name='tavern_messages')
    op.drop_index(op.f('ix_tavern_messages_user_id'), table_name='tavern_messages')
    op.drop_table('tavern_messages')
