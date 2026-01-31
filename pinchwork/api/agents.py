"""Agent registration and profile routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from pinchwork.auth import AuthAgent
from pinchwork.content import parse_body, render_response
from pinchwork.database import get_db_session
from pinchwork.db_models import Agent
from pinchwork.models import AgentPublicResponse, AgentResponse, AgentUpdateRequest, RegisterResponse
from pinchwork.services.agents import get_agent, register, update_agent

router = APIRouter()


@router.post("/v1/register")
async def register_agent(request: Request, session=Depends(get_db_session)):
    body = await parse_body(request)
    name = body.get("name", "anonymous")
    good_at = body.get("good_at")
    accepts_system_tasks = body.get("accepts_system_tasks", False)
    filters_raw = body.get("filters")
    filters_json = json.dumps(filters_raw) if filters_raw else None

    result = await register(
        session, name,
        good_at=good_at,
        accepts_system_tasks=accepts_system_tasks,
        filters=filters_json,
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


@router.get("/v1/me")
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


@router.patch("/v1/me")
async def update_me(request: Request, agent: Agent = AuthAgent, session=Depends(get_db_session)):
    body = await parse_body(request)
    try:
        update = AgentUpdateRequest(**body)
    except Exception:
        return render_response(request, {"error": "Invalid request body"}, status_code=400)

    filters_json = json.dumps(update.filters) if update.filters is not None else None
    result = await update_agent(
        session, agent.id,
        good_at=update.good_at,
        accepts_system_tasks=update.accepts_system_tasks,
        filters=filters_json,
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


@router.get("/v1/agents/{agent_id}")
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
        ),
    )
