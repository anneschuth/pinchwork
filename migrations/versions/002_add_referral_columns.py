"""Add referral columns to agents table.

Revision ID: 002
Revises: 001
Create Date: 2025-01-30

Adds referral_code, referred_by, referral_source, referral_bonus_paid
to the agents table. Uses batch mode for SQLite compatibility.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("referral_code", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("referred_by", sa.VARCHAR(), nullable=True))
        batch_op.add_column(sa.Column("referral_source", sa.VARCHAR(), nullable=True))
        batch_op.add_column(
            sa.Column("referral_bonus_paid", sa.BOOLEAN(), nullable=True, server_default="0")
        )
        batch_op.create_index("ix_agents_referral_code", ["referral_code"], unique=True)
        batch_op.create_index("ix_agents_referred_by", ["referred_by"])


def downgrade() -> None:
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.drop_index("ix_agents_referred_by")
        batch_op.drop_index("ix_agents_referral_code")
        batch_op.drop_column("referral_bonus_paid")
        batch_op.drop_column("referral_source")
        batch_op.drop_column("referred_by")
        batch_op.drop_column("referral_code")
