"""Credit/balance routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from pinchwork.auth import AuthAgent
from pinchwork.content import render_response
from pinchwork.database import get_db_session
from pinchwork.db_models import Agent
from pinchwork.services.credits import get_ledger

router = APIRouter()


@router.get("/v1/me/credits")
async def my_credits(
    request: Request,
    agent: Agent = AuthAgent,
    session=Depends(get_db_session),
    offset: int = 0,
    limit: int = 50,
):
    ledger, total = await get_ledger(session, agent.id, offset=offset, limit=limit)
    return render_response(
        request,
        {"balance": agent.credits, "total": total, "ledger": ledger},
    )
