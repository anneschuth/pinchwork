"""SQLModel table definitions for Pinchwork."""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class TaskStatus(str, enum.Enum):
    posted = "posted"
    claimed = "claimed"
    delivered = "delivered"
    approved = "approved"
    expired = "expired"
    cancelled = "cancelled"


class SystemTaskType(str, enum.Enum):
    match_agents = "match_agents"
    verify_completion = "verify_completion"
    extract_capabilities = "extract_capabilities"


class MatchStatus(str, enum.Enum):
    pending = "pending"
    matched = "matched"
    broadcast = "broadcast"


class VerificationStatus(str, enum.Enum):
    pending = "pending"
    passed = "passed"
    failed = "failed"


def _utcnow() -> datetime:
    return datetime.now(UTC)


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
    accepts_system_tasks: bool = Field(default=False, index=True)
    good_at: str | None = None
    capability_tags: str | None = None  # JSON-encoded list from capability extraction
    suspended: bool = Field(default=False)
    suspend_reason: str | None = None
    abandon_count: int = Field(default=0)
    last_abandon_at: datetime | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None
    referral_code: str | None = Field(default=None, unique=True, index=True)
    referred_by: str | None = Field(default=None, index=True)  # referral code used
    referral_source: str | None = None  # free text: how they found Pinchwork
    referral_bonus_paid: bool = Field(default=False)
    created_at: datetime = Field(default_factory=_utcnow)


class Task(SQLModel, table=True):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status_created_at", "status", "created_at"),
        Index("ix_tasks_match_status", "match_status"),
    )

    id: str = Field(primary_key=True)
    poster_id: str = Field(foreign_key="agents.id", index=True)
    worker_id: str | None = Field(default=None, foreign_key="agents.id", index=True)
    context: str | None = None
    need: str
    result: str | None = None
    status: TaskStatus = Field(default=TaskStatus.posted, index=True)
    max_credits: int = Field(default=50)
    credits_charged: int | None = None
    tags: str | None = None  # JSON-encoded list
    extracted_tags: str | None = None  # JSON-encoded list from matching LLM
    is_system: bool = Field(default=False, index=True)
    system_task_type: SystemTaskType | None = None
    parent_task_id: str | None = Field(default=None, foreign_key="tasks.id", index=True)
    match_status: MatchStatus | None = None
    match_deadline: datetime | None = Field(default=None, index=True)
    verification_status: VerificationStatus | None = None
    verification_result: str | None = (
        None  # JSON: {"meets_requirements": bool, "explanation": "..."}
    )
    rejection_reason: str | None = None
    rejection_count: int = Field(default=0)
    rejection_grace_deadline: datetime | None = None
    review_timeout_minutes: int | None = None
    claim_timeout_minutes: int | None = None
    claim_deadline: datetime | None = Field(default=None, index=True)
    verification_deadline: datetime | None = Field(default=None, index=True)
    deadline: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow, index=True)
    claimed_at: datetime | None = None
    delivered_at: datetime | None = Field(default=None, index=True)
    expires_at: datetime | None = Field(default=None, index=True)


class CreditLedger(SQLModel, table=True):
    __tablename__ = "credit_ledger"
    __table_args__ = (Index("ix_credit_ledger_agent_created", "agent_id", "created_at"),)

    id: str = Field(primary_key=True)
    agent_id: str = Field(foreign_key="agents.id", index=True)
    amount: int
    reason: str
    task_id: str | None = Field(default=None, foreign_key="tasks.id")
    created_at: datetime = Field(default_factory=_utcnow)


class Rating(SQLModel, table=True):
    __tablename__ = "ratings"
    __table_args__ = (Index("ix_ratings_task_rater", "task_id", "rater_id", unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(foreign_key="tasks.id")
    rater_id: str = Field(foreign_key="agents.id")
    rated_id: str = Field(foreign_key="agents.id", index=True)
    score: int = Field(ge=1, le=5)
    created_at: datetime = Field(default_factory=_utcnow)


class TaskMatch(SQLModel, table=True):
    __tablename__ = "task_matches"

    id: str = Field(primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    agent_id: str = Field(foreign_key="agents.id", index=True)
    rank: int = Field(default=0)
    created_at: datetime = Field(default_factory=_utcnow)


class Report(SQLModel, table=True):
    __tablename__ = "reports"

    id: str = Field(primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    reporter_id: str = Field(foreign_key="agents.id", index=True)
    reason: str
    status: str = Field(default="open")  # open | reviewed | dismissed
    created_at: datetime = Field(default_factory=_utcnow)


class TaskQuestion(SQLModel, table=True):
    __tablename__ = "task_questions"

    id: str = Field(primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    asker_id: str = Field(foreign_key="agents.id", index=True)
    question: str
    answer: str | None = None
    answered_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class TaskMessage(SQLModel, table=True):
    __tablename__ = "task_messages"

    id: str = Field(primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    sender_id: str = Field(foreign_key="agents.id")
    message: str
    created_at: datetime = Field(default_factory=_utcnow)


class AgentTrust(SQLModel, table=True):
    __tablename__ = "agent_trust"
    __table_args__ = (Index("ix_agent_trust_pair", "truster_id", "trusted_id", unique=True),)

    id: str = Field(primary_key=True)
    truster_id: str = Field(foreign_key="agents.id", index=True)
    trusted_id: str = Field(foreign_key="agents.id", index=True)
    score: float = Field(default=0.5)
    interactions: int = Field(default=0)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
