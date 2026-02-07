"""Add Moltbook karma verification fields

Revision ID: 007
Revises: 006
Create Date: 2026-02-07 12:34:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    # Add Moltbook verification fields
    op.add_column('agents', sa.Column('moltbook_handle', sa.String(), nullable=True))
    op.add_column('agents', sa.Column('moltbook_karma', sa.Integer(), nullable=True))
    op.add_column('agents', sa.Column('karma_verified_at', sa.DateTime(), nullable=True))
    op.add_column('agents', sa.Column('verified', sa.Boolean(), server_default='false', nullable=False))
    
    # Add unique constraint and index on moltbook_handle
    # Unique constraint prevents one Moltbook account from being linked to multiple Pinchwork agents
    # Partial index (WHERE moltbook_handle IS NOT NULL) allows multiple NULL values
    # Note: SQLite 3.8.0+ allows multiple NULLs in unique indexes by default
    op.create_index(
        'ix_agents_moltbook_handle_unique',
        'agents',
        ['moltbook_handle'],
        unique=True,
        postgresql_where=sa.text('moltbook_handle IS NOT NULL')
    )


def downgrade():
    op.drop_index('ix_agents_moltbook_handle_unique', table_name='agents')
    op.drop_column('agents', 'verified')
    op.drop_column('agents', 'karma_verified_at')
    op.drop_column('agents', 'moltbook_karma')
    op.drop_column('agents', 'moltbook_handle')
