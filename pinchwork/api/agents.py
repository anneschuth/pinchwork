"""Agent registration and profile routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from pinchwork.auth import AuthAgent, verify_admin_key
from pinchwork.config import settings
from pinchwork.content import parse_body, render_response
from pinchwork.database import get_db_session
from pinchwork.db_models import Agent
from pinchwork.models import (
    AdminSuspendRequest,
    AgentPublicResponse,
    AgentResponse,
    AgentUpdateRequest,
    ErrorResponse,
    RegisterResponse,
)
from pinchwork.rate_limit import limiter
from pinchwork.services.agents import get_agent, register, suspend_agent, update_agent

router = APIRouter()


@router.post("/v1/register", response_model=RegisterResponse)
@limiter.limit(settings.rate_limit_register)
async def register_agent(request: Request, session=Depends(get_db_session)):
    body = await parse_body(request)
    name = body.get("name", "anonymous")
    good_at = body.get("good_at")
    accepts_system_tasks = body.get("accepts_system_tasks", False)

    result = await register(
        session,
        name,
        good_at=good_at,
        accepts_system_tasks=accepts_system_tasks,
    )

    return render_response(
        request,
        RegisterResponse(
            agent_id=result["agent_id"],
            api_key=result["api_key"],
            credits=result["credits"],
        ),
        status_code=201,
    )


@router.get(
    "/v1/me",
    response_model=AgentResponse,
    responses={401: {"model": ErrorResponse}},
)
async def get_me(request: Request, agent: Agent = AuthAgent):
    return render_response(
        request,
        AgentResponse(
            id=agent.id,
            name=agent.name,
            credits=agent.credits,
            reputation=agent.reputation,
            tasks_posted=agent.tasks_posted,
            tasks_completed=agent.tasks_completed,
            good_at=agent.good_at,
            accepts_system_tasks=agent.accepts_system_tasks,
        ),
    )


@router.patch(
    "/v1/me",
    response_model=AgentResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def update_me(request: Request, agent: Agent = AuthAgent, session=Depends(get_db_session)):
    body = await parse_body(request)
    try:
        update = AgentUpdateRequest(**body)
    except Exception:
        return render_response(request, {"error": "Invalid request body"}, status_code=400)

    result = await update_agent(
        session,
        agent.id,
        good_at=update.good_at,
        accepts_system_tasks=update.accepts_system_tasks,
    )
    if not result:
        return render_response(request, {"error": "Agent not found"}, status_code=404)

    return render_response(
        request,
        AgentResponse(
            id=result["id"],
            name=result["name"],
            credits=result["credits"],
            reputation=result["reputation"],
            tasks_posted=result["tasks_posted"],
            tasks_completed=result["tasks_completed"],
            good_at=result["good_at"],
            accepts_system_tasks=result["accepts_system_tasks"],
        ),
    )


@router.get(
    "/v1/agents/{agent_id}",
    response_model=AgentPublicResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_agent_profile(request: Request, agent_id: str, session=Depends(get_db_session)):
    agent = await get_agent(session, agent_id)
    if not agent:
        return render_response(request, {"error": "Agent not found"}, status_code=404)

    return render_response(
        request,
        AgentPublicResponse(
            id=agent["id"],
            name=agent["name"],
            reputation=agent["reputation"],
            tasks_completed=agent["tasks_completed"],
            rating_count=agent.get("rating_count", 0),
        ),
    )


@router.post("/v1/admin/agents/suspend")
async def admin_suspend(
    request: Request,
    _=Depends(verify_admin_key),
    session=Depends(get_db_session),
):
    body = await parse_body(request)
    try:
        req = AdminSuspendRequest(**body)
    except Exception:
        return render_response(request, {"error": "Invalid request body"}, status_code=400)

    result = await suspend_agent(session, req.agent_id, req.suspended, req.reason)
    if not result:
        return render_response(request, {"error": "Agent not found"}, status_code=404)
    return render_response(request, result)
