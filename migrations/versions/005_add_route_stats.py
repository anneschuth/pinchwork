"""Add route_stats table for API analytics.

Revision ID: 005
Revises: 004
Create Date: 2026-02-03

Adds route_stats table to track request counts, error rates,
and response times per route with hourly aggregation.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "route_stats",
        sa.Column("id", sa.INTEGER(), primary_key=True, autoincrement=True),
        sa.Column("route", sa.VARCHAR(), nullable=False),
        sa.Column("method", sa.VARCHAR(), nullable=False),
        sa.Column("hour", sa.DATETIME(), nullable=False),
        sa.Column("request_count", sa.INTEGER(), nullable=False, server_default="0"),
        sa.Column("error_4xx", sa.INTEGER(), nullable=False, server_default="0"),
        sa.Column("error_5xx", sa.INTEGER(), nullable=False, server_default="0"),
        sa.Column("total_ms", sa.INTEGER(), nullable=False, server_default="0"),
        sa.Column("min_ms", sa.INTEGER(), nullable=False, server_default="999999"),
        sa.Column("max_ms", sa.INTEGER(), nullable=False, server_default="0"),
    )
    op.create_index("ix_route_stats_route", "route_stats", ["route"])
    op.create_index("ix_route_stats_hour", "route_stats", ["hour"])
    op.create_index(
        "ix_route_stats_unique",
        "route_stats",
        ["route", "method", "hour"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_route_stats_unique", "route_stats")
    op.drop_index("ix_route_stats_hour", "route_stats")
    op.drop_index("ix_route_stats_route", "route_stats")
    op.drop_table("route_stats")
