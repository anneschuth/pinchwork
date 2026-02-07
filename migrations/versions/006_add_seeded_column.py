"""Add seeded column to agents and tasks tables.

Revision ID: 006
Revises: 005
Create Date: 2026-02-07

Adds seeded boolean column to agents and tasks tables to mark
seed data for analytics filtering and easy cleanup.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("seeded", sa.BOOLEAN(), nullable=True, server_default="0"))
        batch_op.create_index("ix_agents_seeded", ["seeded"])

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("seeded", sa.BOOLEAN(), nullable=True, server_default="0"))
        batch_op.create_index("ix_tasks_seeded", ["seeded"])


def downgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_index("ix_tasks_seeded")
        batch_op.drop_column("seeded")

    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.drop_index("ix_agents_seeded")
        batch_op.drop_column("seeded")
