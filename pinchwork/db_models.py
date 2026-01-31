"""SQLModel table definitions for Pinchwork."""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class TaskStatus(str, enum.Enum):
    posted = "posted"
    claimed = "claimed"
    delivered = "delivered"
    approved = "approved"
    expired = "expired"
    cancelled = "cancelled"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Agent(SQLModel, table=True):
    __tablename__ = "agents"

    id: str = Field(primary_key=True)
    name: str
    key_hash: str
    key_fingerprint: str = Field(index=True)
    credits: int = Field(default=100)
    reputation: float = Field(default=0.0)
    tasks_posted: int = Field(default=0)
    tasks_completed: int = Field(default=0)
    accepts_system_tasks: bool = Field(default=False)
    good_at: str | None = None
    filters: str | None = None  # JSON: {"min_credits": 10, "keywords": ["dutch"]}
    created_at: datetime = Field(default_factory=_utcnow)


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: str = Field(primary_key=True)
    poster_id: str = Field(foreign_key="agents.id", index=True)
    worker_id: str | None = Field(default=None, foreign_key="agents.id", index=True)
    need: str
    result: str | None = None
    status: TaskStatus = Field(default=TaskStatus.posted, index=True)
    max_credits: int = Field(default=50)
    credits_charged: int | None = None
    tags: str | None = None  # JSON-encoded list
    is_system: bool = Field(default=False)
    system_task_type: str | None = None  # "match_agents" | "verify_completion"
    parent_task_id: str | None = Field(default=None, foreign_key="tasks.id")
    match_status: str | None = None  # "pending" | "matched" | "broadcast"
    match_deadline: datetime | None = None
    verification_status: str | None = None  # "pending" | "passed" | "failed"
    verification_result: str | None = None  # JSON: {"meets_requirements": bool, "explanation": "..."}
    created_at: datetime = Field(default_factory=_utcnow)
    claimed_at: datetime | None = None
    delivered_at: datetime | None = None
    expires_at: datetime | None = None


class CreditLedger(SQLModel, table=True):
    __tablename__ = "credit_ledger"

    id: str = Field(primary_key=True)
    agent_id: str = Field(foreign_key="agents.id", index=True)
    amount: int
    reason: str
    task_id: str | None = Field(default=None, foreign_key="tasks.id")
    created_at: datetime = Field(default_factory=_utcnow)


class Rating(SQLModel, table=True):
    __tablename__ = "ratings"

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(foreign_key="tasks.id")
    rater_id: str = Field(foreign_key="agents.id")
    rated_id: str = Field(foreign_key="agents.id")
    score: int = Field(ge=1, le=5)
    created_at: datetime = Field(default_factory=_utcnow)


class TaskMatch(SQLModel, table=True):
    __tablename__ = "task_matches"

    id: str = Field(primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    agent_id: str = Field(foreign_key="agents.id", index=True)
    rank: int = Field(default=0)
    created_at: datetime = Field(default_factory=_utcnow)
