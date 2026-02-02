"""Add timeout columns to tasks table and backfill delivered tasks.

Revision ID: 004
Revises: 003
Create Date: 2026-02-02

Adds review_timeout_minutes, claim_timeout_minutes, claim_deadline,
and verification_deadline columns. Then backfills review_timeout_minutes=1440
on existing delivered tasks to preserve the old 24h auto-approve window
(new default is 30 minutes).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("review_timeout_minutes", sa.INTEGER(), nullable=True))
        batch_op.add_column(sa.Column("claim_timeout_minutes", sa.INTEGER(), nullable=True))
        batch_op.add_column(sa.Column("claim_deadline", sa.DATETIME(), nullable=True))
        batch_op.add_column(sa.Column("verification_deadline", sa.DATETIME(), nullable=True))
        batch_op.create_index("ix_tasks_claim_deadline", ["claim_deadline"])
        batch_op.create_index("ix_tasks_verification_deadline", ["verification_deadline"])

    # Backfill: preserve 24h auto-approve for tasks already in flight
    op.execute(
        "UPDATE tasks SET review_timeout_minutes = 1440 "
        "WHERE status = 'delivered' AND review_timeout_minutes IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_index("ix_tasks_verification_deadline")
        batch_op.drop_index("ix_tasks_claim_deadline")
        batch_op.drop_column("verification_deadline")
        batch_op.drop_column("claim_deadline")
        batch_op.drop_column("claim_timeout_minutes")
        batch_op.drop_column("review_timeout_minutes")
