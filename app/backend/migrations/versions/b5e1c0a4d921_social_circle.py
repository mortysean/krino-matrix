"""social circle: character public ids, friendships, character DMs, moments

Revision ID: b5e1c0a4d921
Revises: 7d3a71496bc6
Create Date: 2026-11-08 12:00:00
"""
import secrets

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'b5e1c0a4d921'
down_revision = '7d3a71496bc6'
branch_labels = None
depends_on = None

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 不要 0/O/1/I，念出来不会混


def upgrade() -> None:
    op.add_column('characters', sa.Column('public_id', sa.String(length=16), nullable=True))
    op.create_index(op.f('ix_characters_public_id'), 'characters', ['public_id'], unique=True)
    # 已有角色补上角色号
    conn = op.get_bind()
    used = set()
    for (cid,) in conn.execute(sa.text("SELECT id FROM characters WHERE public_id IS NULL")):
        while True:
            pid = "KR-" + "".join(secrets.choice(ALPHABET) for _ in range(6))
            if pid not in used:
                break
        used.add(pid)
        conn.execute(sa.text("UPDATE characters SET public_id = :p WHERE id = :i"), {"p": pid, "i": cid})

    op.create_table('friendships',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('a_id', sa.String(length=32), nullable=False),
        sa.Column('b_id', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('note', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['a_id'], ['characters.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['b_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('a_id', 'b_id'))
    op.create_index(op.f('ix_friendships_a_id'), 'friendships', ['a_id'])
    op.create_index(op.f('ix_friendships_b_id'), 'friendships', ['b_id'])

    op.create_table('char_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('friendship_id', sa.String(length=32), nullable=False),
        sa.Column('author_id', sa.String(length=32), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('trigger', sa.String(length=12), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['friendship_id'], ['friendships.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_char_messages_friendship_id'), 'char_messages', ['friendship_id'])
    op.create_index(op.f('ix_char_messages_created_at'), 'char_messages', ['created_at'])

    op.create_table('char_knows',
        sa.Column('char_id', sa.String(length=32), nullable=False),
        sa.Column('other_id', sa.String(length=32), nullable=False),
        sa.Column('impression', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['char_id'], ['characters.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['other_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('char_id', 'other_id'))

    op.create_table('posts',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('author_id', sa.String(length=32), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('mood', sa.String(length=16), nullable=False),
        sa.Column('trigger', sa.String(length=12), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_posts_author_id'), 'posts', ['author_id'])
    op.create_index(op.f('ix_posts_created_at'), 'posts', ['created_at'])

    op.create_table('post_reactions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('post_id', sa.String(length=32), nullable=False),
        sa.Column('author_id', sa.String(length=32), nullable=False),
        sa.Column('kind', sa.String(length=8), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_post_reactions_post_id'), 'post_reactions', ['post_id'])


def downgrade() -> None:
    op.drop_table('post_reactions')
    op.drop_table('posts')
    op.drop_table('char_knows')
    op.drop_table('char_messages')
    op.drop_table('friendships')
    op.drop_index(op.f('ix_characters_public_id'), table_name='characters')
    op.drop_column('characters', 'public_id')
