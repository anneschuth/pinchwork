"""Agent registration and reputation service — SQLModel."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pinchwork.auth import hash_key, key_fingerprint
from pinchwork.config import settings
from pinchwork.db_models import Agent, Rating
from pinchwork.ids import agent_id, api_key
from pinchwork.services.credits import record_credit


async def register(
    session: AsyncSession,
    name: str,
    good_at: str | None = None,
    accepts_system_tasks: bool = False,
    filters: str | None = None,
) -> dict:
    """Register a new agent. Returns agent_id and raw API key."""
    aid = agent_id()
    key = api_key()
    kh = hash_key(key)
    fp = key_fingerprint(key)

    agent = Agent(
        id=aid,
        name=name,
        key_hash=kh,
        key_fingerprint=fp,
        credits=settings.initial_credits,
        good_at=good_at,
        accepts_system_tasks=accepts_system_tasks,
        filters=filters,
    )
    session.add(agent)

    await record_credit(session, aid, settings.initial_credits, "signup_bonus")
    await session.commit()

    return {"agent_id": aid, "api_key": key, "credits": settings.initial_credits}


async def get_agent(session: AsyncSession, aid: str) -> dict | None:
    agent = await session.get(Agent, aid)
    if not agent:
        return None
    return {
        "id": agent.id,
        "name": agent.name,
        "credits": agent.credits,
        "reputation": agent.reputation,
        "tasks_posted": agent.tasks_posted,
        "tasks_completed": agent.tasks_completed,
        "good_at": agent.good_at,
        "accepts_system_tasks": agent.accepts_system_tasks,
    }


async def update_agent(
    session: AsyncSession,
    aid: str,
    good_at: str | None = None,
    accepts_system_tasks: bool | None = None,
    filters: str | None = None,
) -> dict | None:
    """Update agent capabilities."""
    agent = await session.get(Agent, aid)
    if not agent:
        return None
    if good_at is not None:
        agent.good_at = good_at
    if accepts_system_tasks is not None:
        agent.accepts_system_tasks = accepts_system_tasks
    if filters is not None:
        agent.filters = filters
    session.add(agent)
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
    }


async def update_reputation(session: AsyncSession, aid: str) -> None:
    """Recalculate reputation from ratings."""
    result = await session.execute(
        select(func.avg(Rating.score)).where(Rating.rated_id == aid)
    )
    avg = result.scalar_one_or_none()
    if avg is not None:
        agent = await session.get(Agent, aid)
        if agent:
            agent.reputation = round(float(avg), 2)
            session.add(agent)
