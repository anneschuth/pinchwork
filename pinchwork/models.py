"""Pydantic models for request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    name: str = Field(..., description="Agent name")
    good_at: str | None = Field(default=None, description="What this agent is good at")
    accepts_system_tasks: bool = Field(
        default=False, description="Whether to accept system tasks (matching, verification)"
    )
    filters: dict | None = Field(default=None, description="Task filters")


class RegisterResponse(BaseModel):
    agent_id: str
    api_key: str
    credits: int
    message: str = "Welcome to Pinchwork. Read https://pinchwork.dev/skill.md to get started."


class TaskCreateRequest(BaseModel):
    need: str = Field(..., description="What you need done")
    max_credits: int = Field(default=50, ge=1, le=1000)
    tags: list[str] | None = Field(default=None, description="Optional tags for matching")
    wait: int | None = Field(
        default=None, ge=1, le=300, description="Seconds to wait for sync result"
    )


class TaskResponse(BaseModel):
    task_id: str
    status: str
    need: str
    result: str | None = None
    credits_charged: int | None = None
    poster_id: str | None = None
    worker_id: str | None = None


class TaskPickupResponse(BaseModel):
    task_id: str
    need: str
    max_credits: int
    poster_id: str


class DeliverRequest(BaseModel):
    result: str = Field(..., description="The completed work")
    credits_claimed: int | None = Field(
        default=None, ge=1, description="Credits to claim (defaults to max_credits)"
    )


class AgentUpdateRequest(BaseModel):
    good_at: str | None = None
    accepts_system_tasks: bool | None = None
    filters: dict | None = None


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


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
