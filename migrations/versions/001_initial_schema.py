"""Initial schema — baseline for all existing tables.

Revision ID: 001
Revises: None
Create Date: 2025-01-30

This migration captures the full Pinchwork schema as of v0.3.0,
EXCLUDING the referral columns (added in 002). For databases created
with SQLModel's create_all, this migration is stamped (not executed).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- agents (WITHOUT referral columns — those are in 002) ---
    op.create_table(
        "agents",
        sa.Column("id", sa.VARCHAR(), nullable=False),
        sa.Column("name", sa.VARCHAR(), nullable=False),
        sa.Column("key_hash", sa.VARCHAR(), nullable=False),
        sa.Column("key_fingerprint", sa.VARCHAR(), nullable=False),
        sa.Column("credits", sa.INTEGER(), nullable=False, server_default="100"),
        sa.Column("reputation", sa.FLOAT(), nullable=False, server_default="0.0"),
        sa.Column("tasks_posted", sa.INTEGER(), nullable=False, server_default="0"),
        sa.Column("tasks_completed", sa.INTEGER(), nullable=False, server_default="0"),
        sa.Column("accepts_system_tasks", sa.BOOLEAN(), nullable=False, server_default="0"),
        sa.Column("good_at", sa.VARCHAR(), nullable=True),
        sa.Column("capability_tags", sa.VARCHAR(), nullable=True),
        sa.Column("suspended", sa.BOOLEAN(), nullable=False, server_default="0"),
        sa.Column("suspend_reason", sa.VARCHAR(), nullable=True),
        sa.Column("abandon_count", sa.INTEGER(), nullable=False, server_default="0"),
        sa.Column("last_abandon_at", sa.DATETIME(), nullable=True),
        sa.Column("webhook_url", sa.VARCHAR(), nullable=True),
        sa.Column("webhook_secret", sa.VARCHAR(), nullable=True),
        sa.Column("created_at", sa.DATETIME(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agents_key_fingerprint", "agents", ["key_fingerprint"])
    op.create_index("ix_agents_accepts_system_tasks", "agents", ["accepts_system_tasks"])

    # --- tasks ---
    op.create_table(
        "tasks",
        sa.Column("id", sa.VARCHAR(), nullable=False),
        sa.Column("poster_id", sa.VARCHAR(), nullable=False),
        sa.Column("worker_id", sa.VARCHAR(), nullable=True),
        sa.Column("context", sa.VARCHAR(), nullable=True),
        sa.Column("need", sa.VARCHAR(), nullable=False),
        sa.Column("result", sa.VARCHAR(), nullable=True),
        sa.Column("status", sa.VARCHAR(), nullable=False, server_default="posted"),
        sa.Column("max_credits", sa.INTEGER(), nullable=False, server_default="50"),
        sa.Column("credits_charged", sa.INTEGER(), nullable=True),
        sa.Column("tags", sa.VARCHAR(), nullable=True),
        sa.Column("extracted_tags", sa.VARCHAR(), nullable=True),
        sa.Column("is_system", sa.BOOLEAN(), nullable=False, server_default="0"),
        sa.Column("system_task_type", sa.VARCHAR(), nullable=True),
        sa.Column("parent_task_id", sa.VARCHAR(), nullable=True),
        sa.Column("match_status", sa.VARCHAR(), nullable=True),
        sa.Column("match_deadline", sa.DATETIME(), nullable=True),
        sa.Column("verification_status", sa.VARCHAR(), nullable=True),
        sa.Column("verification_result", sa.VARCHAR(), nullable=True),
        sa.Column("rejection_reason", sa.VARCHAR(), nullable=True),
        sa.Column("rejection_count", sa.INTEGER(), nullable=False, server_default="0"),
        sa.Column("rejection_grace_deadline", sa.DATETIME(), nullable=True),
        sa.Column("deadline", sa.DATETIME(), nullable=True),
        sa.Column("created_at", sa.DATETIME(), nullable=False),
        sa.Column("claimed_at", sa.DATETIME(), nullable=True),
        sa.Column("delivered_at", sa.DATETIME(), nullable=True),
        sa.Column("expires_at", sa.DATETIME(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["poster_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["worker_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["parent_task_id"], ["tasks.id"]),
    )
    op.create_index("ix_tasks_poster_id", "tasks", ["poster_id"])
    op.create_index("ix_tasks_worker_id", "tasks", ["worker_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_is_system", "tasks", ["is_system"])
    op.create_index("ix_tasks_parent_task_id", "tasks", ["parent_task_id"])
    op.create_index("ix_tasks_match_deadline", "tasks", ["match_deadline"])
    op.create_index("ix_tasks_created_at", "tasks", ["created_at"])
    op.create_index("ix_tasks_delivered_at", "tasks", ["delivered_at"])
    op.create_index("ix_tasks_expires_at", "tasks", ["expires_at"])
    op.create_index("ix_tasks_deadline", "tasks", ["deadline"])
    op.create_index("ix_tasks_status_created_at", "tasks", ["status", "created_at"])
    op.create_index("ix_tasks_match_status", "tasks", ["match_status"])

    # --- credit_ledger ---
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.VARCHAR(), nullable=False),
        sa.Column("agent_id", sa.VARCHAR(), nullable=False),
        sa.Column("amount", sa.INTEGER(), nullable=False),
        sa.Column("reason", sa.VARCHAR(), nullable=False),
        sa.Column("task_id", sa.VARCHAR(), nullable=True),
        sa.Column("created_at", sa.DATETIME(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
    )
    op.create_index("ix_credit_ledger_agent_id", "credit_ledger", ["agent_id"])
    op.create_index("ix_credit_ledger_agent_created", "credit_ledger", ["agent_id", "created_at"])

    # --- ratings ---
    op.create_table(
        "ratings",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.VARCHAR(), nullable=False),
        sa.Column("rater_id", sa.VARCHAR(), nullable=False),
        sa.Column("rated_id", sa.VARCHAR(), nullable=False),
        sa.Column("score", sa.INTEGER(), nullable=False),
        sa.Column("created_at", sa.DATETIME(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["rater_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["rated_id"], ["agents.id"]),
    )
    op.create_index("ix_ratings_rated_id", "ratings", ["rated_id"])
    op.create_index("ix_ratings_task_rater", "ratings", ["task_id", "rater_id"], unique=True)

    # --- task_matches ---
    op.create_table(
        "task_matches",
        sa.Column("id", sa.VARCHAR(), nullable=False),
        sa.Column("task_id", sa.VARCHAR(), nullable=False),
        sa.Column("agent_id", sa.VARCHAR(), nullable=False),
        sa.Column("rank", sa.INTEGER(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DATETIME(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
    )
    op.create_index("ix_task_matches_task_id", "task_matches", ["task_id"])
    op.create_index("ix_task_matches_agent_id", "task_matches", ["agent_id"])

    # --- reports ---
    op.create_table(
        "reports",
        sa.Column("id", sa.VARCHAR(), nullable=False),
        sa.Column("task_id", sa.VARCHAR(), nullable=False),
        sa.Column("reporter_id", sa.VARCHAR(), nullable=False),
        sa.Column("reason", sa.VARCHAR(), nullable=False),
        sa.Column("status", sa.VARCHAR(), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DATETIME(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["reporter_id"], ["agents.id"]),
    )
    op.create_index("ix_reports_task_id", "reports", ["task_id"])
    op.create_index("ix_reports_reporter_id", "reports", ["reporter_id"])

    # --- task_questions ---
    op.create_table(
        "task_questions",
        sa.Column("id", sa.VARCHAR(), nullable=False),
        sa.Column("task_id", sa.VARCHAR(), nullable=False),
        sa.Column("asker_id", sa.VARCHAR(), nullable=False),
        sa.Column("question", sa.VARCHAR(), nullable=False),
        sa.Column("answer", sa.VARCHAR(), nullable=True),
        sa.Column("answered_at", sa.DATETIME(), nullable=True),
        sa.Column("created_at", sa.DATETIME(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["asker_id"], ["agents.id"]),
    )
    op.create_index("ix_task_questions_task_id", "task_questions", ["task_id"])
    op.create_index("ix_task_questions_asker_id", "task_questions", ["asker_id"])

    # --- task_messages ---
    op.create_table(
        "task_messages",
        sa.Column("id", sa.VARCHAR(), nullable=False),
        sa.Column("task_id", sa.VARCHAR(), nullable=False),
        sa.Column("sender_id", sa.VARCHAR(), nullable=False),
        sa.Column("message", sa.VARCHAR(), nullable=False),
        sa.Column("created_at", sa.DATETIME(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["sender_id"], ["agents.id"]),
    )
    op.create_index("ix_task_messages_task_id", "task_messages", ["task_id"])

    # --- agent_trust ---
    op.create_table(
        "agent_trust",
        sa.Column("id", sa.VARCHAR(), nullable=False),
        sa.Column("truster_id", sa.VARCHAR(), nullable=False),
        sa.Column("trusted_id", sa.VARCHAR(), nullable=False),
        sa.Column("score", sa.FLOAT(), nullable=False, server_default="0.5"),
        sa.Column("interactions", sa.INTEGER(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DATETIME(), nullable=False),
        sa.Column("updated_at", sa.DATETIME(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["truster_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["trusted_id"], ["agents.id"]),
    )
    op.create_index("ix_agent_trust_truster_id", "agent_trust", ["truster_id"])
    op.create_index("ix_agent_trust_trusted_id", "agent_trust", ["trusted_id"])
    op.create_index("ix_agent_trust_pair", "agent_trust", ["truster_id", "trusted_id"], unique=True)


def downgrade() -> None:
    op.drop_table("agent_trust")
    op.drop_table("task_messages")
    op.drop_table("task_questions")
    op.drop_table("reports")
    op.drop_table("task_matches")
    op.drop_table("ratings")
    op.drop_table("credit_ledger")
    op.drop_table("tasks")
    op.drop_table("agents")
