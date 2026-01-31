"""Credit/balance routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from pinchwork.auth import AuthAgent, verify_admin_key
from pinchwork.content import parse_body, render_response
from pinchwork.database import get_db_session
from pinchwork.db_models import Agent
from pinchwork.models import AdminGrantRequest, CreditBalanceResponse, ErrorResponse
from pinchwork.services.credits import get_escrowed_balance, get_ledger, grant_credits

router = APIRouter()


@router.get(
    "/v1/me/credits",
    response_model=CreditBalanceResponse,
    responses={401: {"model": ErrorResponse}},
)
async def my_credits(
    request: Request,
    agent: Agent = AuthAgent,
    session=Depends(get_db_session),
    offset: int = 0,
    limit: int = 50,
):
    ledger, total = await get_ledger(session, agent.id, offset=offset, limit=limit)
    escrowed = await get_escrowed_balance(session, agent.id)
    return render_response(
        request,
        {"balance": agent.credits, "escrowed": escrowed, "total": total, "ledger": ledger},
    )


@router.post("/v1/admin/credits/grant")
async def admin_grant(
    request: Request,
    _=Depends(verify_admin_key),
    session=Depends(get_db_session),
):
    body = await parse_body(request)
    try:
        req = AdminGrantRequest(**body)
    except Exception:
        return render_response(request, {"error": "Invalid request body"}, status_code=400)

    await grant_credits(session, req.agent_id, req.amount, req.reason)
    await session.commit()
    return render_response(
        request, {"granted": req.amount, "agent_id": req.agent_id, "reason": req.reason}
    )
