"""Backfill referral_code for existing agents.

Revision ID: 003
Revises: 002
Create Date: 2026-02-02

Migration 002 added the referral_code column but didn't generate codes
for existing agents. This migration backfills them using secrets.token_urlsafe(12).
"""

from __future__ import annotations

import secrets

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def _generate_code() -> str:
    """Match the format from pinchwork.ids.referral_code()."""
    return f"ref-{secrets.token_urlsafe(12)}"


def upgrade() -> None:
    conn = op.get_bind()
    # Find agents without a referral code
    rows = conn.execute(sa.text("SELECT id FROM agents WHERE referral_code IS NULL")).fetchall()

    for (agent_id,) in rows:
        # Generate unique code, retry on collision (extremely unlikely)
        for _ in range(10):
            code = _generate_code()
            try:
                conn.execute(
                    sa.text("UPDATE agents SET referral_code = :code WHERE id = :id"),
                    {"code": code, "id": agent_id},
                )
                break
            except sa.exc.IntegrityError:
                continue  # Collision, retry with new code


def downgrade() -> None:
    # Cannot distinguish backfilled codes from registration-time codes,
    # so downgrade is a no-op. Migration 002 downgrade drops the column entirely.
    pass
