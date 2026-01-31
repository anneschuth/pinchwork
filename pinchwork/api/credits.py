"""Credit/balance routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError

from pinchwork.auth import AuthAgent, verify_admin_key
from pinchwork.config import settings
from pinchwork.content import parse_body, render_response
from pinchwork.database import get_db_session
from pinchwork.db_models import Agent
from pinchwork.models import (
    AdminGrantRequest,
    AdminGrantResponse,
    AgentStatsResponse,
    CreditBalanceResponse,
    ErrorResponse,
)
from pinchwork.rate_limit import limiter
from pinchwork.services.credits import (
    get_agent_stats,
    get_escrowed_balance,
    get_ledger,
    grant_credits,
)

router = APIRouter()


@router.get(
    "/v1/me/credits",
    response_model=CreditBalanceResponse,
    responses={401: {"model": ErrorResponse}},
)
@limiter.limit(settings.rate_limit_read)
async def my_credits(
    request: Request,
    agent: Agent = AuthAgent,
    session=Depends(get_db_session),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """Get your credit balance, escrowed amount, and transaction ledger."""
    ledger, total = await get_ledger(session, agent.id, offset=offset, limit=limit)
    escrowed = await get_escrowed_balance(session, agent.id)
    return render_response(
        request,
        {"balance": agent.credits, "escrowed": escrowed, "total": total, "ledger": ledger},
    )


@router.get(
    "/v1/me/stats",
    response_model=AgentStatsResponse,
    responses={401: {"model": ErrorResponse}},
)
async def my_stats(
    request: Request,
    agent: Agent = AuthAgent,
    session=Depends(get_db_session),
):
    """Earnings dashboard with approval rate, per-tag breakdown, and 7/30 day stats."""
    stats = await get_agent_stats(session, agent.id)
    return render_response(request, stats)


@router.post(
    "/v1/admin/credits/grant",
    response_model=AdminGrantResponse,
    responses={400: {"model": ErrorResponse}},
)
@limiter.limit(settings.rate_limit_admin)
async def admin_grant(
    request: Request,
    _=Depends(verify_admin_key),
    session=Depends(get_db_session),
):
    body = await parse_body(request)
    try:
        req = AdminGrantRequest(**body)
    except ValidationError:
        return render_response(request, {"error": "Invalid request body"}, status_code=400)

    """Grant credits to an agent. Admin only."""
    await grant_credits(session, req.agent_id, req.amount, req.reason)
    await session.commit()
    return render_response(
        request, {"granted": req.amount, "agent_id": req.agent_id, "reason": req.reason}
    )
