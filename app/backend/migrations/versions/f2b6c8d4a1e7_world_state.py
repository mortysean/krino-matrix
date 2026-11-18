"""world state: where each character is and what she is doing, plus her life log

Revision ID: f2b6c8d4a1e7
Revises: e1f3a9c7b2d5
Create Date: 2026-11-19 10:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = 'f2b6c8d4a1e7'
down_revision = 'e1f3a9c7b2d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('char_states',
        sa.Column('char_id', sa.String(length=32), nullable=False),
        sa.Column('place', sa.String(length=16), nullable=False),
        sa.Column('activity', sa.String(length=16), nullable=False),
        sa.Column('mood', sa.String(length=12), nullable=False),
        sa.Column('energy', sa.Float(), nullable=False),
        sa.Column('with_id', sa.String(length=32), nullable=True),
        sa.Column('since', sa.DateTime(timezone=True), nullable=False),
        sa.Column('until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['char_id'], ['characters.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['with_id'], ['characters.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('char_id'))
    op.create_table('life_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('char_id', sa.String(length=32), nullable=False),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('place', sa.String(length=16), nullable=False),
        sa.Column('activity', sa.String(length=16), nullable=False),
        sa.Column('other_id', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['char_id'], ['characters.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['other_id'], ['characters.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_life_events_char_id'), 'life_events', ['char_id'], unique=False)
    op.create_index(op.f('ix_life_events_created_at'), 'life_events', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_life_events_created_at'), table_name='life_events')
    op.drop_index(op.f('ix_life_events_char_id'), table_name='life_events')
    op.drop_table('life_events')
    op.drop_table('char_states')
