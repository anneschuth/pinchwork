"""Agent registration and reputation service — SQLModel."""

from __future__ import annotations

import json

from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pinchwork.auth import hash_key, key_fingerprint
from pinchwork.config import settings
from pinchwork.db_models import Agent, Rating, Task, TaskStatus
from pinchwork.ids import agent_id, api_key, referral_code
from pinchwork.services.credits import record_credit


async def register(
    session: AsyncSession,
    name: str,
    good_at: str | None = None,
    accepts_system_tasks: bool = False,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
    referral: str | None = None,
) -> dict:
    """Register a new agent. Returns agent_id and raw API key."""
    aid = agent_id()
    key = api_key()
    kh = hash_key(key)
    fp = key_fingerprint(key)
    ref_code = referral_code()

    # Determine if referral is a valid referral code or free-text source
    referred_by: str | None = None
    referral_source: str | None = None
    if referral:
        # Check if it matches a referral code and the referrer exists
        referrer = await session.execute(select(Agent).where(Agent.referral_code == referral))
        referrer_agent = referrer.scalar_one_or_none()
        if referrer_agent:
            referred_by = referral
        else:
            referral_source = referral

    agent = Agent(
        id=aid,
        name=name,
        key_hash=kh,
        key_fingerprint=fp,
        credits=settings.initial_credits,
        good_at=good_at,
        accepts_system_tasks=accepts_system_tasks,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        referral_code=ref_code,
        referred_by=referred_by,
        referral_source=referral_source,
    )
    session.add(agent)

    await record_credit(session, aid, settings.initial_credits, "signup_bonus")

    if good_at and not accepts_system_tasks:
        from pinchwork.services.tasks import _maybe_spawn_capability_extraction

        await _maybe_spawn_capability_extraction(session, agent)

    await session.commit()

    return {
        "agent_id": aid,
        "api_key": key,
        "credits": settings.initial_credits,
        "referral_code": ref_code,
    }


REFERRAL_BONUS = 10
MAX_REFERRAL_BONUSES_PER_AGENT = 50  # cap to prevent farming


async def pay_referral_bonus(session: AsyncSession, worker_id: str) -> str | None:
    """Pay referral bonus to the referrer when a referred agent completes first task.

    Returns the referrer's agent_id if bonus was paid, None otherwise.
    Guards against: self-referral, duplicate payment (atomic flag), and bonus farming.

    All validation happens BEFORE the atomic flag update to avoid burning the flag
    on failed checks.
    """
    worker = await session.get(Agent, worker_id)
    if not worker or not worker.referred_by or worker.referral_bonus_paid:
        return None

    # Find the referrer by referral code
    referrer_result = await session.execute(
        select(Agent).where(Agent.referral_code == worker.referred_by)
    )
    referrer = referrer_result.scalar_one_or_none()
    if not referrer:
        return None

    # Self-referral protection
    if referrer.id == worker_id:
        return None

    # Cap referral bonuses per agent to prevent farming
    bonus_count = await session.execute(
        select(func.count())
        .select_from(Agent)
        .where(
            Agent.referred_by == referrer.referral_code,
            Agent.referral_bonus_paid == True,  # noqa: E712
        )
    )
    if bonus_count.scalar_one() >= MAX_REFERRAL_BONUSES_PER_AGENT:
        return None

    # Atomic claim: set referral_bonus_paid = True only if still False.
    # This prevents double-payment if two tasks approve concurrently.
    result = await session.execute(
        text(
            "UPDATE agents SET referral_bonus_paid = TRUE"
            " WHERE id = :wid AND referral_bonus_paid = FALSE"
            " RETURNING id"
        ),
        {"wid": worker_id},
    )
    if not result.fetchone():
        return None  # lost the race — another task already claimed it

    # Refresh the worker object so ORM doesn't overwrite our atomic UPDATE
    await session.refresh(worker)

    # Pay the bonus via atomic credit increment
    await session.execute(
        text("UPDATE agents SET credits = credits + :bonus WHERE id = :rid"),
        {"bonus": REFERRAL_BONUS, "rid": referrer.id},
    )
    await session.refresh(referrer)
    await record_credit(session, referrer.id, REFERRAL_BONUS, f"referral_bonus:{worker_id}")

    return referrer.id


async def get_referral_stats(session: AsyncSession, agent_id: str) -> dict:
    """Get referral stats for an agent."""
    agent = await session.get(Agent, agent_id)
    if not agent:
        return {
            "referral_code": None,
            "total_referrals": 0,
            "bonuses_earned": 0,
            "bonus_credits_earned": 0,
            "max_bonuses": MAX_REFERRAL_BONUSES_PER_AGENT,
        }

    # Count agents referred by this agent's code
    result = await session.execute(
        select(func.count()).select_from(Agent).where(Agent.referred_by == agent.referral_code)
    )
    total_referrals = result.scalar_one()

    # Count bonus payments
    result = await session.execute(
        select(func.count())
        .select_from(Agent)
        .where(Agent.referred_by == agent.referral_code, Agent.referral_bonus_paid == True)  # noqa: E712
    )
    bonuses_paid = result.scalar_one()

    return {
        "referral_code": agent.referral_code,
        "total_referrals": total_referrals,
        "bonuses_earned": bonuses_paid,
        "bonus_credits_earned": bonuses_paid * REFERRAL_BONUS,
        "max_bonuses": MAX_REFERRAL_BONUSES_PER_AGENT,
    }


async def get_referral_sources(session: AsyncSession) -> dict:
    """Admin: get aggregated referral source analytics."""
    # Count by referral_source (free text)
    sources = await session.execute(
        select(Agent.referral_source, func.count())
        .where(Agent.referral_source.isnot(None))
        .group_by(Agent.referral_source)
        .order_by(func.count().desc())
    )
    source_counts = [{"source": row[0], "count": row[1]} for row in sources.all()]

    # Count by referred_by (referral codes)
    codes = await session.execute(
        select(Agent.referred_by, func.count())
        .where(Agent.referred_by.isnot(None))
        .group_by(Agent.referred_by)
        .order_by(func.count().desc())
    )
    code_counts = [{"referral_code": row[0], "count": row[1]} for row in codes.all()]

    # Totals
    total = await session.execute(select(func.count()).select_from(Agent))
    total_agents = total.scalar_one()
    referred = await session.execute(
        select(func.count()).select_from(Agent).where(Agent.referred_by.isnot(None))
    )
    total_referred = referred.scalar_one()
    sourced = await session.execute(
        select(func.count()).select_from(Agent).where(Agent.referral_source.isnot(None))
    )
    total_sourced = sourced.scalar_one()

    return {
        "total_agents": total_agents,
        "referred_by_code": total_referred,
        "reported_source": total_sourced,
        "no_referral_info": total_agents - total_referred - total_sourced,
        "top_sources": source_counts[:20],
        "top_referrers": code_counts[:20],
    }


async def get_agent(session: AsyncSession, aid: str) -> dict | None:
    agent = await session.get(Agent, aid)
    if not agent:
        return None

    # Count ratings received
    count_result = await session.execute(
        select(func.count()).select_from(Rating).where(Rating.rated_id == aid)
    )
    rating_count = count_result.scalar_one()

    cap_tags = json.loads(agent.capability_tags) if agent.capability_tags else None

    return {
        "id": agent.id,
        "name": agent.name,
        "credits": agent.credits,
        "reputation": agent.reputation,
        "tasks_posted": agent.tasks_posted,
        "tasks_completed": agent.tasks_completed,
        "good_at": agent.good_at,
        "accepts_system_tasks": agent.accepts_system_tasks,
        "rating_count": rating_count,
        "capability_tags": cap_tags,
    }


async def update_agent(
    session: AsyncSession,
    aid: str,
    good_at: str | None = None,
    accepts_system_tasks: bool | None = None,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
) -> dict | None:
    """Update agent capabilities."""
    agent = await session.get(Agent, aid)
    if not agent:
        return None
    if good_at is not None:
        agent.good_at = good_at
    if accepts_system_tasks is not None:
        agent.accepts_system_tasks = accepts_system_tasks
    if webhook_url is not None:
        agent.webhook_url = webhook_url
    if webhook_secret is not None:
        agent.webhook_secret = webhook_secret
    session.add(agent)

    if good_at is not None and not agent.accepts_system_tasks:
        from pinchwork.services.tasks import _maybe_spawn_capability_extraction

        await _maybe_spawn_capability_extraction(session, agent)

    await session.commit()
    return {
        "id": agent.id,
        "name": agent.name,
        "credits": agent.credits,
        "reputation": agent.reputation,
        "tasks_posted": agent.tasks_posted,
        "tasks_completed": agent.tasks_completed,
        "good_at": agent.good_at,
        "accepts_system_tasks": agent.accepts_system_tasks,
        "webhook_url": agent.webhook_url,
    }


async def suspend_agent(
    session: AsyncSession, agent_id: str, suspended: bool, reason: str | None = None
) -> dict | None:
    agent = await session.get(Agent, agent_id)
    if not agent:
        return None
    agent.suspended = suspended
    agent.suspend_reason = reason if suspended else None
    session.add(agent)
    await session.commit()
    return {"id": agent.id, "suspended": agent.suspended, "reason": agent.suspend_reason}


async def update_reputation(session: AsyncSession, aid: str) -> None:
    """Recalculate reputation from ratings."""
    result = await session.execute(select(func.avg(Rating.score)).where(Rating.rated_id == aid))
    avg = result.scalar_one_or_none()
    if avg is not None:
        agent = await session.get(Agent, aid)
        if agent:
            agent.reputation = round(float(avg), 2)
            session.add(agent)


async def get_reputation_breakdown(session: AsyncSession, aid: str) -> list[dict]:
    """Get per-tag reputation breakdown for an agent."""
    # Get all approved tasks where this agent was the worker
    tasks_result = await session.execute(
        select(Task.id, Task.tags).where(
            Task.worker_id == aid,
            Task.status == TaskStatus.approved,
            Task.tags.isnot(None),
        )
    )
    task_rows = tasks_result.fetchall()
    task_tag_map: dict[str, list[str]] = {}
    for task_id_val, tags_json in task_rows:
        tags = json.loads(tags_json) if tags_json else []
        task_tag_map[task_id_val] = tags

    if not task_tag_map:
        return []

    # Get ratings for these tasks
    ratings_result = await session.execute(
        select(Rating.task_id, Rating.score).where(
            Rating.rated_id == aid,
            Rating.task_id.in_(list(task_tag_map.keys())),
        )
    )

    tag_scores: dict[str, list[int]] = {}
    for task_id_val, score in ratings_result.fetchall():
        for tag in task_tag_map.get(task_id_val, []):
            tag_scores.setdefault(tag, []).append(score)

    return [
        {
            "tag": tag,
            "avg_rating": round(sum(scores) / len(scores), 2),
            "count": len(scores),
        }
        for tag, scores in sorted(tag_scores.items(), key=lambda x: -sum(x[1]) / len(x[1]))
    ]


_VALID_SORT_BY = {"reputation", "tasks_completed"}


async def search_agents(
    session: AsyncSession,
    tags: list[str] | None = None,
    search: str | None = None,
    min_reputation: float | None = None,
    sort_by: str = "reputation",
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Search and filter agents for discovery."""
    if sort_by not in _VALID_SORT_BY:
        sort_by = "reputation"

    query = select(Agent).where(
        Agent.suspended.is_(False),
        Agent.id != settings.platform_agent_id,
    )

    if search:
        term = f"%{search}%"
        query = query.where(Agent.good_at.ilike(term))

    if min_reputation is not None:
        query = query.where(Agent.reputation >= min_reputation)

    if tags:
        # Filter by capability_tags containing any of the requested tags
        for tag in tags:
            query = query.where(Agent.capability_tags.contains(f'"{tag}"'))

    # Count total before pagination
    from sqlalchemy import select as sa_select

    count_query = sa_select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar_one()

    # Sort
    if sort_by == "tasks_completed":
        query = query.order_by(Agent.tasks_completed.desc())
    else:
        query = query.order_by(Agent.reputation.desc())

    query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    agents = result.scalars().all()

    # Get rating counts
    agent_ids = [a.id for a in agents]
    rating_counts: dict[str, int] = {}
    if agent_ids:
        rc_result = await session.execute(
            select(Rating.rated_id, func.count())
            .where(Rating.rated_id.in_(agent_ids))
            .group_by(Rating.rated_id)
        )
        rating_counts = {row[0]: row[1] for row in rc_result.fetchall()}

    agent_list = []
    for a in agents:
        cap_tags = json.loads(a.capability_tags) if a.capability_tags else None
        agent_list.append(
            {
                "id": a.id,
                "name": a.name,
                "reputation": a.reputation,
                "tasks_completed": a.tasks_completed,
                "rating_count": rating_counts.get(a.id, 0),
                "good_at": a.good_at,
                "tags": cap_tags,
            }
        )

    return {"agents": agent_list, "total": total}
