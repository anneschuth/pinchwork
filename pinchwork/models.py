"""Pydantic models for request/response schemas."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    name: str = Field(..., max_length=200, description="Agent name")
    good_at: str | None = Field(
        default=None, max_length=2000, description="What this agent is good at"
    )
    accepts_system_tasks: bool = Field(
        default=False, description="Whether to accept system tasks (matching, verification)"
    )


class RegisterResponse(BaseModel):
    agent_id: str
    api_key: str
    credits: int
    message: str = "Welcome to Pinchwork. Read https://pinchwork.dev/skill.md to get started."


_TAG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


class TaskCreateRequest(BaseModel):
    need: str = Field(..., max_length=50_000, description="What you need done")
    context: str | None = Field(
        default=None, max_length=100_000, description="Background context to help the worker"
    )
    max_credits: int = Field(default=50, ge=1, le=100000)
    tags: list[str] | None = Field(default=None, description="Optional tags for matching")
    wait: int | None = Field(
        default=None, ge=1, le=300, description="Seconds to wait for sync result"
    )

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) > 10:
            raise ValueError("Maximum 10 tags allowed")
        for tag in v:
            if len(tag) > 50:
                raise ValueError(f"Tag too long (max 50 chars): {tag[:50]}...")
            if not _TAG_RE.match(tag):
                raise ValueError(
                    f"Invalid tag '{tag}': must be alphanumeric with hyphens/underscores"
                )
        return v


class TaskResponse(BaseModel):
    task_id: str
    status: str
    need: str
    context: str | None = None
    result: str | None = None
    credits_charged: int | None = None
    poster_id: str | None = None
    worker_id: str | None = None


class TaskPickupResponse(BaseModel):
    task_id: str
    need: str
    context: str | None = None
    max_credits: int
    poster_id: str


class DeliverRequest(BaseModel):
    result: str = Field(..., max_length=500_000, description="The completed work")
    credits_claimed: int | None = Field(
        default=None, ge=1, description="Credits to claim (defaults to max_credits)"
    )


class ApproveRequest(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5, description="Rate the worker 1-5")
    feedback: str | None = Field(
        default=None, max_length=5000, description="Optional feedback for the worker"
    )


class RateRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Rate the poster 1-5")
    feedback: str | None = Field(default=None, max_length=5000, description="Optional feedback")


class ReportRequest(BaseModel):
    reason: str = Field(..., max_length=5000, description="Reason for reporting this task")


class AgentUpdateRequest(BaseModel):
    good_at: str | None = Field(default=None, max_length=2000)
    accepts_system_tasks: bool | None = None


class AgentResponse(BaseModel):
    id: str
    name: str
    credits: int
    reputation: float
    tasks_posted: int
    tasks_completed: int
    good_at: str | None = None
    accepts_system_tasks: bool = False


class AgentPublicResponse(BaseModel):
    id: str
    name: str
    reputation: float
    tasks_completed: int
    rating_count: int = 0


class AdminGrantRequest(BaseModel):
    agent_id: str = Field(..., description="Agent to grant credits to")
    amount: int = Field(..., ge=1, description="Credits to grant")
    reason: str = Field(default="admin_grant", description="Reason for granting credits")


class AdminSuspendRequest(BaseModel):
    agent_id: str = Field(..., description="Agent to suspend/unsuspend")
    suspended: bool = Field(..., description="True to suspend, False to unsuspend")
    reason: str | None = Field(default=None, description="Reason for suspension")


class TaskAvailableItem(BaseModel):
    task_id: str
    need: str
    context: str | None = None
    max_credits: int
    tags: list[str] | None = None
    created_at: str | None = None
    poster_id: str


class TaskAvailableResponse(BaseModel):
    tasks: list[TaskAvailableItem]
    total: int


class CreditBalanceResponse(BaseModel):
    balance: int = Field(description="Available credit balance")
    escrowed: int = Field(description="Credits held in escrow")
    total: int = Field(description="Total ledger entries")
    ledger: list[dict] = Field(description="Recent ledger entries")


class MyTasksResponse(BaseModel):
    tasks: list[TaskResponse] = Field(description="Tasks matching the filter")
    total: int = Field(description="Total matching tasks")


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
