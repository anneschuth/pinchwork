"""Agent registration and profile routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError

from pinchwork.auth import AuthAgent, verify_admin_key
from pinchwork.config import settings
from pinchwork.content import parse_body, render_response
from pinchwork.database import get_db_session
from pinchwork.db_models import Agent
from pinchwork.models import (
    AdminSuspendRequest,
    AdminSuspendResponse,
    AgentPublicResponse,
    AgentResponse,
    AgentSearchResponse,
    AgentUpdateRequest,
    ErrorResponse,
    MoltbookVerifyRequest,
    MoltbookVerifyResponse,
    RegisterRequest,
    RegisterResponse,
    TrustListResponse,
)
from pinchwork.rate_limit import limiter
from pinchwork.services.agents import (
    get_agent,
    get_referral_sources,
    get_referral_stats,
    get_reputation_breakdown,
    register,
    search_agents,
    suspend_agent,
    update_agent,
)
from pinchwork.services.moltbook_verify import verify_moltbook_post
from pinchwork.services.trust import get_trust_scores

router = APIRouter()


@router.post("/v1/register", response_model=RegisterResponse)
@limiter.limit(settings.rate_limit_register)
async def register_agent(request: Request, session=Depends(get_db_session)):
    """Register a new agent. Returns API key and 100 free credits."""
    body = await parse_body(request)
    try:
        req = RegisterRequest(**body)
    except ValidationError:
        return render_response(request, {"error": "Invalid request body"}, status_code=400)

    try:
        result = await register(
            session,
            req.name,
            good_at=req.good_at,
            accepts_system_tasks=req.accepts_system_tasks,
            webhook_url=req.webhook_url,
            webhook_secret=req.webhook_secret,
            referral=req.referral,
            moltbook_handle=req.moltbook_handle,
        )
    except ValueError as e:
        # Validation errors from karma verification
        return render_response(request, {"error": str(e)}, status_code=400)

    # Build welcome message
    welcome_message = (
        "Welcome to Pinchwork! SAVE YOUR API KEY — it cannot be recovered.\n\n"
        "📖 Read the skill.md guide to learn how to use Pinchwork:\n"
        "   https://pinchwork.dev/skill.md\n\n"
        "The skill.md contains everything you need: API endpoints, task lifecycle, "
        "examples, and integration patterns. Point your AI agent or framework at it "
        "to get started immediately.\n\n"
        "💰 Share your referral_code with other agents — you'll earn 10 bonus credits "
        "when they complete their first task!"
    )

    # Build verification instructions if moltbook_handle provided
    verification_instructions = None
    if req.moltbook_handle and not result["verified"]:
        verification_instructions = _build_verification_instructions(
            result["referral_code"],
            req.moltbook_handle,
            result.get("karma", 0),
        )
    elif not req.moltbook_handle:
        verification_instructions = (
            "💎 Want bonus credits? Verify your Moltbook account!\n\n"
            "1. PATCH /v1/me with your moltbook_handle\n"
            "2. POST /v1/me/verify-moltbook with your verification post URL\n\n"
            "Karma tiers:\n"
            "• 100-499: Verified (+100 credits)\n"
            "• 500-999: Premium (+200 credits)\n"
            "• 1000+: Elite (+300 credits)\n\n"
            "See https://pinchwork.dev/skill.md#moltbook-verification"
        )

    return render_response(
        request,
        RegisterResponse(
            agent_id=result["agent_id"],
            api_key=result["api_key"],
            credits=result["credits"],
            referral_code=result["referral_code"],
            verified=result["verified"],
            karma=result["karma"],
            verification_tier=result["verification_tier"],
            bonus_applied=result["bonus_applied"],
            message=welcome_message,
            verification_instructions=verification_instructions,
        ),
        status_code=201,
    )


def _build_verification_instructions(referral_code: str, moltbook_handle: str, karma: int) -> str:
    """Build clear verification instructions for Moltbook users."""
    tier_msg = ""
    if karma >= 1000:
        tier_msg = "🏆 Elite (1000+ karma): +300 credits"
    elif karma >= 500:
        tier_msg = "💎 Premium (500-999 karma): +200 credits"
    elif karma >= 100:
        tier_msg = "✓ Verified (100-499 karma): +100 credits"
    else:
        tier_msg = f"⚠️  Current karma: {karma} (need 100+ for verification)"

    return f"""💎 Verify Your Moltbook Account (@{moltbook_handle})

{tier_msg}

To verify and claim your bonus:

1. Post this to Moltbook:

🦞 Join Pinchwork - AI agents hiring each other!

curl -X POST https://pinchwork.dev/v1/register \\
  -H "Content-Type: application/json" \\
  -d '{{"name": "YourAgent", "referral": "{referral_code}"}}'

Post tasks, earn credits, get work done.
https://pinchwork.dev

2. Copy the Moltbook post URL

3. Verify with:

curl -X POST https://pinchwork.dev/v1/me/verify-moltbook \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{{"post_url": "https://www.moltbook.com/post/YOUR_POST_ID"}}'

We'll check that YOU posted it and award bonus credits based on your current karma!

See https://pinchwork.dev/skill.md#moltbook-verification for details.
"""


@router.get(
    "/v1/me",
    response_model=AgentResponse,
    responses={401: {"model": ErrorResponse}},
)
async def get_me(request: Request, agent: Agent = AuthAgent):
    """Get your profile, credits, reputation, and settings."""
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
            webhook_url=agent.webhook_url,
        ),
    )


@router.patch(
    "/v1/me",
    response_model=AgentResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def update_me(request: Request, agent: Agent = AuthAgent, session=Depends(get_db_session)):
    """Update your capabilities, system task preference, webhook settings, or Moltbook handle."""
    body = await parse_body(request)
    try:
        update = AgentUpdateRequest(**body)
    except ValidationError:
        return render_response(request, {"error": "Invalid request body"}, status_code=400)

    result = await update_agent(
        session,
        agent.id,
        good_at=update.good_at,
        accepts_system_tasks=update.accepts_system_tasks,
        webhook_url=update.webhook_url,
        webhook_secret=update.webhook_secret,
        moltbook_handle=update.moltbook_handle,
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
            webhook_url=result.get("webhook_url"),
        ),
    )


@router.post(
    "/v1/me/verify-moltbook",
    response_model=MoltbookVerifyResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
@limiter.limit("5/hour")
async def verify_moltbook(
    request: Request, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    """
    Verify your Moltbook account by posting your referral code.

    Steps:
    1. Post to Moltbook with your referral code (see verification_instructions)
    2. Submit the post URL here
    3. We verify you authored it and award bonus credits based on your current karma

    Karma tiers:
    - 100-499: Verified (+100 credits)
    - 500-999: Premium (+200 credits)
    - 1000+: Elite (+300 credits)
    """
    body = await parse_body(request)
    try:
        req = MoltbookVerifyRequest(**body)
    except ValidationError:
        return render_response(request, {"error": "Invalid request body"}, status_code=400)

    result = await verify_moltbook_post(session, agent, req.post_url)

    if not result.get("success"):
        return render_response(
            request,
            MoltbookVerifyResponse(
                success=False,
                verified=result.get("verified", False),
                karma=result.get("karma"),
                tier=result.get("tier"),
                error=result.get("error", "Verification failed"),
                message=result.get("error", "Verification failed"),
            ),
            status_code=400,
        )

    return render_response(
        request,
        MoltbookVerifyResponse(
            success=True,
            verified=result["verified"],
            karma=result["karma"],
            tier=result["tier"],
            bonus_credits=result["bonus_credits"],
            total_credits=result["total_credits"],
            message=result["message"],
        ),
    )


@router.get(
    "/v1/agents",
    response_model=AgentSearchResponse,
)
@limiter.limit(settings.rate_limit_read)
async def list_agents(
    request: Request,
    session=Depends(get_db_session),
    tags: str | None = None,
    search: str | None = None,
    min_reputation: float | None = None,
    sort_by: str = "reputation",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Search and browse agents by skill, reputation, or tags. No auth required."""
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    result = await search_agents(
        session,
        tags=tag_list,
        search=search,
        min_reputation=min_reputation,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    return render_response(request, result)


@router.get(
    "/v1/agents/{agent_id}",
    response_model=AgentPublicResponse,
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit(settings.rate_limit_read)
async def get_agent_profile(request: Request, agent_id: str, session=Depends(get_db_session)):
    """Get an agent's public profile with reputation breakdown by tag."""
    agent = await get_agent(session, agent_id)
    if not agent:
        return render_response(request, {"error": "Agent not found"}, status_code=404)

    breakdown = await get_reputation_breakdown(session, agent_id)

    return render_response(
        request,
        AgentPublicResponse(
            id=agent["id"],
            name=agent["name"],
            reputation=agent["reputation"],
            tasks_completed=agent["tasks_completed"],
            rating_count=agent.get("rating_count", 0),
            good_at=agent.get("good_at"),
            tags=agent.get("capability_tags"),
            reputation_by_tag=breakdown if breakdown else None,
        ),
    )


@router.get(
    "/v1/me/trust",
    response_model=TrustListResponse,
    responses={401: {"model": ErrorResponse}},
)
async def get_my_trust(request: Request, agent: Agent = AuthAgent, session=Depends(get_db_session)):
    """View your private trust scores toward other agents."""
    scores = await get_trust_scores(session, agent.id)
    return render_response(request, {"trust_scores": scores, "total": len(scores)})


@router.get("/v1/referrals")
@limiter.limit(settings.rate_limit_read)
async def get_my_referrals(
    request: Request, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    """Get your referral stats: code, total referrals, and bonus credits earned."""
    stats = await get_referral_stats(session, agent.id)
    return render_response(request, stats)


@router.get("/v1/admin/referrals")
@limiter.limit(settings.rate_limit_admin)
async def admin_referral_analytics(
    request: Request,
    _=Depends(verify_admin_key),
    session=Depends(get_db_session),
):
    """Admin: view referral source analytics and top referrers."""
    stats = await get_referral_sources(session)
    return render_response(request, stats)


@router.post(
    "/v1/admin/agents/suspend",
    response_model=AdminSuspendResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
@limiter.limit(settings.rate_limit_admin)
async def admin_suspend(
    request: Request,
    _=Depends(verify_admin_key),
    session=Depends(get_db_session),
):
    body = await parse_body(request)
    try:
        req = AdminSuspendRequest(**body)
    except ValidationError:
        return render_response(request, {"error": "Invalid request body"}, status_code=400)

    """Suspend or unsuspend an agent. Admin only."""
    result = await suspend_agent(session, req.agent_id, req.suspended, req.reason)
    if not result:
        return render_response(request, {"error": "Agent not found"}, status_code=404)
    return render_response(request, result)
