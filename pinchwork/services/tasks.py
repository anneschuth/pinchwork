"""Task lifecycle service — SQLModel, all bug fixes included."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pinchwork.config import settings
from pinchwork.db_models import (
    Agent,
    AgentTrust,
    MatchStatus,
    Rating,
    Report,
    SystemTaskType,
    Task,
    TaskMatch,
    TaskMessage,
    TaskQuestion,
    TaskStatus,
    VerificationStatus,
)
from pinchwork.events import Event, event_bus
from pinchwork.ids import match_id as make_match_id
from pinchwork.ids import message_id as make_message_id
from pinchwork.ids import question_id as make_question_id
from pinchwork.ids import report_id as make_report_id
from pinchwork.ids import task_id as make_task_id
from pinchwork.services.credits import (
    escrow,
    increment_tasks_completed,
    increment_tasks_posted,
    refund,
    release_to_worker,
    release_to_worker_with_fee,
)
from pinchwork.utils import safe_json_loads, status_str

logger = logging.getLogger("pinchwork.tasks")

# Event registry for wait_for_result (Bug #7 fix)
_task_events: dict[str, asyncio.Event] = {}


def _get_event(tid: str) -> asyncio.Event:
    if tid not in _task_events:
        _task_events[tid] = asyncio.Event()
    return _task_events[tid]


def cleanup_task_event(tid: str) -> None:
    _task_events.pop(tid, None)


# ---------------------------------------------------------------------------
# Matching & verification helpers
# ---------------------------------------------------------------------------


async def _get_infra_agents(session: AsyncSession) -> list[Agent]:
    """Return agents that accept system tasks (excluding platform agent)."""
    result = await session.execute(
        select(Agent).where(
            Agent.accepts_system_tasks.is_(True), Agent.id != settings.platform_agent_id
        )
    )
    return list(result.scalars().all())


async def _builtin_match(session: AsyncSession, task: Task) -> None:
    """Built-in tag-overlap matcher when no infra agents exist."""
    result = await session.execute(
        select(Agent).where(
            Agent.id != settings.platform_agent_id,
            Agent.id != task.poster_id,
            Agent.suspended.is_(False),
            Agent.good_at != None,  # noqa: E711
        )
    )
    candidates = list(result.scalars().all())
    if not candidates:
        task.match_status = MatchStatus.broadcast
        session.add(task)
        return

    # Parse task tags
    task_tags: set[str] = set()
    for field in (task.tags, task.extracted_tags):
        parsed = safe_json_loads(field)
        if parsed:
            task_tags.update(t.lower() for t in parsed)

    task_keywords = set(task.need.lower().split()) if task.need else set()

    scored: list[tuple[Agent, float]] = []
    for agent in candidates:
        agent_tags: set[str] = set()
        cap_tags = safe_json_loads(agent.capability_tags)
        if cap_tags:
            agent_tags.update(t.lower() for t in cap_tags)

        # Also parse good_at as keywords
        agent_keywords = set(agent.good_at.lower().split()) if agent.good_at else set()

        tag_overlap = len(task_tags & agent_tags) * 2
        keyword_overlap = len(task_keywords & agent_keywords)
        # F4: reputation factor
        rep_bonus = agent.reputation * 0.5
        score = tag_overlap + keyword_overlap + rep_bonus

        if score > 0:
            scored.append((agent, score))

    if not scored:
        task.match_status = MatchStatus.broadcast
        session.add(task)
        return

    # Sort by score descending, take top 5
    scored.sort(key=lambda x: -x[1])
    top = scored[:5]

    for rank, (agent, _score) in enumerate(top):
        tm = TaskMatch(
            id=make_match_id(),
            task_id=task.id,
            agent_id=agent.id,
            rank=rank,
        )
        session.add(tm)

    task.match_status = MatchStatus.matched
    session.add(task)


async def _maybe_spawn_matching(session: AsyncSession, task: Task) -> None:
    """Create a match_agents system task if any infra agents exist."""
    infra_agents = await _get_infra_agents(session)
    if not infra_agents:
        await _builtin_match(session, task)
        return

    # Build agent list for the matching prompt
    all_agents_result = await session.execute(
        select(Agent).where(Agent.id != settings.platform_agent_id, Agent.good_at != None)  # noqa: E711
    )
    agents_with_skills = all_agents_result.scalars().all()
    agent_list = [{"id": a.id, "good_at": a.good_at} for a in agents_with_skills]

    context_line = f"\nContext: {task.context}\n" if task.context else ""
    tags_line = f"\nTags: {task.tags}\n" if task.tags else ""
    need = (
        f"Match agents for: {task.need}\n{context_line}{tags_line}\n"
        f"Available agents:\n{json.dumps(agent_list)}\n\n"
        'Return JSON: {"ranked_agents": ["agent_id_1", "agent_id_2", ...], '
        '"extracted_tags": ["tag1", "tag2", ...]}\n'
        "extracted_tags: short lowercase keywords describing "
        "the task domain/skills needed (max 20)."
    )

    system_tid = make_task_id()
    system_task = Task(
        id=system_tid,
        poster_id=settings.platform_agent_id,
        need=need,
        max_credits=settings.match_credits,
        is_system=True,
        system_task_type=SystemTaskType.match_agents,
        parent_task_id=task.id,
        expires_at=datetime.now(UTC) + timedelta(hours=settings.task_expire_hours),
    )
    session.add(system_task)

    task.match_status = MatchStatus.pending
    task.match_deadline = datetime.now(UTC) + timedelta(seconds=settings.match_timeout_seconds)
    session.add(task)


async def _maybe_spawn_verification(session: AsyncSession, task: Task) -> None:
    """Create a verify_completion system task if any infra agents exist."""
    infra_agents = await _get_infra_agents(session)
    if not infra_agents:
        return

    context_line = f"Context: {task.context}\n" if task.context else ""
    need = (
        f"Verify completion. Task need: {task.need}\n"
        f"{context_line}"
        f"Delivery: {task.result}\n\n"
        'Return JSON: {"meets_requirements": true/false, "explanation": "..."}'
    )

    system_tid = make_task_id()
    system_task = Task(
        id=system_tid,
        poster_id=settings.platform_agent_id,
        need=need,
        max_credits=settings.verify_credits,
        is_system=True,
        system_task_type=SystemTaskType.verify_completion,
        parent_task_id=task.id,
        expires_at=datetime.now(UTC) + timedelta(hours=settings.task_expire_hours),
    )
    session.add(system_task)

    task.verification_status = VerificationStatus.pending
    task.verification_deadline = datetime.now(UTC) + timedelta(
        seconds=settings.verification_timeout_seconds
    )
    session.add(task)


async def _process_match_result(session: AsyncSession, system_task: Task) -> None:
    """Parse match result and create TaskMatch rows."""
    parent = await session.get(Task, system_task.parent_task_id)
    if not parent:
        return

    result_data = safe_json_loads(system_task.result)
    if not result_data:
        parent.match_status = MatchStatus.broadcast
        session.add(parent)
        return

    ranked_agents = result_data.get("ranked_agents", [])
    if not ranked_agents:
        parent.match_status = MatchStatus.broadcast
        session.add(parent)
        return

    # Validate agent IDs: must exist, not be the poster, and no duplicates
    if not isinstance(ranked_agents, list):
        parent.match_status = MatchStatus.broadcast
        session.add(parent)
        return

    ranked_agents = ranked_agents[:20]  # Cap to prevent abuse
    unique_agents: list[str] = []
    seen: set[str] = set()
    for aid in ranked_agents:
        if not isinstance(aid, str) or aid in seen or aid == parent.poster_id:
            continue
        seen.add(aid)
        unique_agents.append(aid)

    if not unique_agents:
        parent.match_status = MatchStatus.broadcast
        session.add(parent)
        return

    # Verify all agent IDs exist in database
    valid_result = await session.execute(select(Agent.id).where(Agent.id.in_(unique_agents)))
    valid_ids = {row[0] for row in valid_result.fetchall()}

    for rank, aid in enumerate(unique_agents):
        if aid not in valid_ids:
            continue
        tm = TaskMatch(
            id=make_match_id(),
            task_id=parent.id,
            agent_id=aid,
            rank=rank,
        )
        session.add(tm)

    # Save extracted tags from the matching result
    extracted_tags = result_data.get("extracted_tags", [])
    if isinstance(extracted_tags, list) and extracted_tags:
        parent.extracted_tags = json.dumps(extracted_tags[: settings.max_extracted_tags])

    parent.match_status = MatchStatus.matched
    session.add(parent)


async def _process_verify_result(session: AsyncSession, system_task: Task) -> None:
    """Parse verification result and update parent task."""
    parent = await session.get(Task, system_task.parent_task_id)
    if not parent:
        return

    result_data = safe_json_loads(system_task.result)
    if not result_data:
        parent.verification_status = VerificationStatus.failed
        parent.verification_result = json.dumps(
            {"meets_requirements": False, "explanation": "Failed to parse verification result"}
        )
        session.add(parent)
        return

    meets = result_data.get("meets_requirements", False)
    parent.verification_result = system_task.result
    if meets:
        parent.verification_status = VerificationStatus.passed
        # Verification is advisory — poster always has final say.
        # Auto-approve is handled by the background job, not here.
    else:
        parent.verification_status = VerificationStatus.failed

    parent.verification_deadline = None  # Clear stale deadline
    session.add(parent)


async def _maybe_spawn_capability_extraction(session: AsyncSession, agent: Agent) -> None:
    """Create an extract_capabilities system task if any infra agents exist."""
    infra_agents = await _get_infra_agents(session)
    if not infra_agents:
        return

    need = (
        f'Extract capability tags from this agent description: "{agent.good_at}"\n'
        f"Agent ID: {agent.id}\n\n"
        'Return JSON: {"agent_id": "...", "tags": ["tag1", "tag2", ...]}\n'
        "tags: short lowercase keywords describing the agent's capabilities (max 20)."
    )

    system_tid = make_task_id()
    system_task = Task(
        id=system_tid,
        poster_id=settings.platform_agent_id,
        need=need,
        context=json.dumps({"target_agent_id": agent.id}),
        max_credits=settings.capability_extract_credits,
        is_system=True,
        system_task_type=SystemTaskType.extract_capabilities,
        expires_at=datetime.now(UTC) + timedelta(hours=settings.task_expire_hours),
    )
    session.add(system_task)


async def _process_capability_result(session: AsyncSession, system_task: Task) -> None:
    """Parse capability extraction result and save tags to the agent."""
    result_data = safe_json_loads(system_task.result)
    if not result_data:
        return

    agent_id = result_data.get("agent_id")
    tags = result_data.get("tags", [])

    if not isinstance(tags, list):
        return

    # Also try to get agent_id from context if not in result
    if not agent_id and system_task.context:
        ctx = safe_json_loads(system_task.context)
        if ctx:
            agent_id = ctx.get("target_agent_id")

    if not agent_id:
        return

    agent = await session.get(Agent, agent_id)
    if not agent:
        return

    agent.capability_tags = json.dumps(tags[: settings.max_extracted_tags])
    session.add(agent)


async def _finalize_approval_credits(session: AsyncSession, task: Task, fee_percent: float) -> None:
    """Credit-handling part of approval: pay worker with fee, refund remaining, increment stats.

    The caller MUST have already atomically set status to 'approved'.
    """
    credits = task.credits_charged or 0
    remaining = task.max_credits - credits

    await release_to_worker_with_fee(
        session, task.id, task.worker_id, task.poster_id, credits, fee_percent
    )
    if remaining > 0:
        await refund(session, task.id, task.poster_id, remaining)

    await increment_tasks_completed(session, task.worker_id)

    # Pay referral bonus if applicable (first completed task)
    from pinchwork.services.agents import pay_referral_bonus

    await pay_referral_bonus(session, task.worker_id)


async def finalize_task_approval(session: AsyncSession, task: Task, fee_percent: float) -> None:
    """Atomically approve a task and release credits. Used by background jobs."""
    # Atomic status transition to prevent double-payment
    result = await session.execute(
        text("UPDATE tasks SET status = 'approved' WHERE id = :id AND status = 'delivered'"),
        {"id": task.id},
    )
    if result.rowcount == 0:
        return  # Already approved or status changed — skip silently

    await session.refresh(task)
    await _finalize_approval_credits(session, task, fee_percent)


async def finalize_system_task_approval(session: AsyncSession, task: Task) -> None:
    """Atomically approve a system task, paying the worker if present."""
    # Atomic status transition to prevent double-payment
    result = await session.execute(
        text("UPDATE tasks SET status = 'approved' WHERE id = :id AND status = 'delivered'"),
        {"id": task.id},
    )
    if result.rowcount == 0:
        return  # Already approved or status changed — skip silently

    await session.refresh(task)
    credits = task.credits_charged or 0
    if task.worker_id:
        await release_to_worker(session, task.id, task.worker_id, credits)
        await increment_tasks_completed(session, task.worker_id)

        # Pay referral bonus if applicable
        from pinchwork.services.agents import pay_referral_bonus

        await pay_referral_bonus(session, task.worker_id)


# ---------------------------------------------------------------------------
# Shared query helpers
# ---------------------------------------------------------------------------


def _build_conflict_subquery(worker_id: str):
    """Subquery: parent tasks where this agent did system work (conflict rule)."""
    return select(Task.parent_task_id).where(
        Task.is_system == True,  # noqa: E712
        Task.worker_id == worker_id,
        Task.parent_task_id != None,  # noqa: E711
    )


def _apply_tag_filters(query, tags: list[str] | None):
    """Apply tag containment filters to a query."""
    if tags:
        for tag in tags:
            query = query.where(Task.tags.contains(f'"{tag}"'))
    return query


def _load_agent_capability_tags(agent: Agent) -> set[str]:
    """Load and lowercase an agent's capability tags."""
    parsed = safe_json_loads(agent.capability_tags)
    if parsed:
        return {t.lower() for t in parsed}
    return set()


# ---------------------------------------------------------------------------
# Core task operations
# ---------------------------------------------------------------------------


async def create_task(
    session: AsyncSession,
    poster_id: str,
    need: str,
    max_credits: int = 50,
    tags: list[str] | None = None,
    context: str | None = None,
    deadline_minutes: int | None = None,
    review_timeout_minutes: int | None = None,
    claim_timeout_minutes: int | None = None,
) -> dict:
    """Create a task and escrow credits atomically in one transaction."""
    tid = make_task_id()
    expires_at = datetime.now(UTC) + timedelta(hours=settings.task_expire_hours)
    tags_json = json.dumps(tags) if tags else None

    deadline = None
    if deadline_minutes is not None:
        deadline = datetime.now(UTC) + timedelta(minutes=deadline_minutes)

    task = Task(
        id=tid,
        poster_id=poster_id,
        need=need,
        context=context,
        max_credits=max_credits,
        tags=tags_json,
        expires_at=expires_at,
        deadline=deadline,
        review_timeout_minutes=review_timeout_minutes,
        claim_timeout_minutes=claim_timeout_minutes,
    )
    session.add(task)
    # Flush so the task row exists for FK on ledger
    await session.flush()

    # Atomic escrow (Bug #1 fix — single UPDATE with balance check)
    await escrow(session, poster_id, tid, max_credits)

    await increment_tasks_posted(session, poster_id)

    # Spawn matching system task
    await _maybe_spawn_matching(session, task)

    await session.commit()

    result = {"id": tid, "status": "posted", "need": need, "max_credits": max_credits}
    if deadline:
        result["deadline"] = deadline.isoformat()
    return result


async def get_task(session: AsyncSession, tid: str) -> dict | None:
    task = await session.get(Task, tid)
    if not task:
        return None
    return {
        "id": task.id,
        "poster_id": task.poster_id,
        "worker_id": task.worker_id,
        "need": task.need,
        "context": task.context,
        "result": task.result,
        "status": status_str(task.status),
        "max_credits": task.max_credits,
        "credits_charged": task.credits_charged,
        "tags": task.tags,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "delivered_at": task.delivered_at.isoformat() if task.delivered_at else None,
        "expires_at": task.expires_at.isoformat() if task.expires_at else None,
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "claim_deadline": task.claim_deadline.isoformat() if task.claim_deadline else None,
        "review_timeout_minutes": task.review_timeout_minutes,
        "claim_timeout_minutes": task.claim_timeout_minutes,
    }


def _check_abandon_cooldown(agent: Agent) -> None:
    """Raise 429 if agent has too many recent abandons."""
    if (
        agent.abandon_count or 0
    ) >= settings.max_abandons_before_cooldown and agent.last_abandon_at:
        last = agent.last_abandon_at
        # Ensure timezone-aware comparison (SQLite may strip tzinfo)
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        cooldown_end = last + timedelta(minutes=settings.abandon_cooldown_minutes)
        if datetime.now(UTC) < cooldown_end:
            raise HTTPException(
                status_code=429,
                detail=f"Too many abandons. Cooldown until {cooldown_end.isoformat()}",
            )


def _compute_tag_overlap(task: Task, agent_tags: set[str]) -> int:
    """Count how many of the task's tags overlap with the agent's capability tags."""
    task_tags: set[str] = set()
    for field in (task.tags, task.extracted_tags):
        parsed = safe_json_loads(field)
        if parsed:
            task_tags.update(parsed)
    return len({t.lower() for t in task_tags} & agent_tags)


async def pickup_task(
    session: AsyncSession,
    worker_id: str,
    tags: list[str] | None = None,
    search: str | None = None,
) -> dict | None:
    """Atomically claim the next available task with priority phases.

    For infra agents: system tasks first, then regular tasks.
    For all agents: matched tasks first, then broadcast + pending (FIFO).
    Conflict rule: agents cannot pick up tasks they did system work for.
    """
    # Check if this agent is an infra agent
    agent = await session.get(Agent, worker_id)
    if not agent:
        return None

    _check_abandon_cooldown(agent)

    # Phase 0: Infra agents try system tasks first
    if agent.accepts_system_tasks:
        task = await _try_pickup_system_task(session, worker_id)
        if task:
            return task

    conflict_subquery = _build_conflict_subquery(worker_id)

    # Phase 1: Matched tasks (tasks where this agent has a TaskMatch row)
    matched_subquery = select(TaskMatch.task_id).where(TaskMatch.agent_id == worker_id)
    query = select(Task).where(
        Task.status == TaskStatus.posted,
        Task.poster_id != worker_id,
        Task.is_system == False,  # noqa: E712
        Task.match_status == MatchStatus.matched,
        Task.id.in_(matched_subquery),
        Task.id.not_in(conflict_subquery),
    )

    query = _apply_tag_filters(query, tags)
    query = _apply_search_filter(query, search)

    # Order by rank (join with TaskMatch)
    query = query.limit(10)
    result = await session.execute(query)
    matched_tasks = result.scalars().all()

    if matched_tasks:
        # Sort by match rank
        rank_result = await session.execute(
            select(TaskMatch.task_id, TaskMatch.rank).where(
                TaskMatch.agent_id == worker_id,
                TaskMatch.task_id.in_([t.id for t in matched_tasks]),
            )
        )
        rank_map = {row[0]: row[1] for row in rank_result.fetchall()}
        matched_tasks.sort(key=lambda t: rank_map.get(t.id, 999))

        for t in matched_tasks:
            claimed = await _try_claim(session, t, worker_id)
            if claimed:
                return claimed

    agent_tags = _load_agent_capability_tags(agent)

    # Phase 2: Broadcast + pending tasks (scored by tag overlap, poster rep, trust)
    query2 = (
        select(Task)
        .where(
            Task.status == TaskStatus.posted,
            Task.poster_id != worker_id,
            Task.is_system == False,  # noqa: E712
            Task.match_status.in_([MatchStatus.broadcast, MatchStatus.pending]),
            Task.id.not_in(conflict_subquery),
        )
        .order_by(Task.created_at.asc())
    )

    query2 = _apply_tag_filters(query2, tags)
    query2 = _apply_search_filter(query2, search)

    query2 = query2.limit(20)
    result2 = await session.execute(query2)
    broadcast_tasks = list(result2.scalars().all())

    if broadcast_tasks:
        # Batch-fetch poster reputations
        poster_ids = list({t.poster_id for t in broadcast_tasks})
        rep_result = await session.execute(
            select(Agent.id, Agent.reputation).where(Agent.id.in_(poster_ids))
        )
        rep_map = {row[0]: row[1] for row in rep_result.fetchall()}

        # Batch-fetch trust scores (poster→worker)
        trust_result = await session.execute(
            select(AgentTrust.truster_id, AgentTrust.score).where(
                AgentTrust.truster_id.in_(poster_ids),
                AgentTrust.trusted_id == worker_id,
            )
        )
        trust_map = {row[0]: row[1] for row in trust_result.fetchall()}

        def _sort_key(t: Task):
            tag_score = -_compute_tag_overlap(t, agent_tags) if agent_tags else 0
            poster_rep = -(rep_map.get(t.poster_id, 0.0))
            trust_score = -(trust_map.get(t.poster_id, 0.5))
            return (tag_score, poster_rep, trust_score, t.created_at)

        broadcast_tasks.sort(key=_sort_key)

        for t in broadcast_tasks:
            claimed = await _try_claim(session, t, worker_id)
            if claimed:
                return claimed

    return None


async def _try_pickup_system_task(session: AsyncSession, worker_id: str) -> dict | None:
    """Try to pick up a system task for infra agents."""
    query = (
        select(Task)
        .where(
            Task.is_system == True,  # noqa: E712
            Task.status == TaskStatus.posted,
            Task.poster_id != worker_id,
        )
        .order_by(Task.created_at.asc())
        .limit(1)
    )
    result = await session.execute(query)
    task = result.scalar_one_or_none()
    if not task:
        return None
    return await _try_claim(session, task, worker_id)


async def _try_claim(session: AsyncSession, task: Task, worker_id: str) -> dict | None:
    """Atomically claim a task. Returns pickup dict or None if lost race."""
    now = datetime.now(UTC)
    claim_result = await session.execute(
        text(
            "UPDATE tasks SET status = 'claimed', worker_id = :worker_id, "
            "claimed_at = :now WHERE id = :id AND status = 'posted'"
        ),
        {"worker_id": worker_id, "now": now, "id": task.id},
    )
    if claim_result.rowcount == 0:
        return None

    # Set claim_deadline for non-system tasks
    if not task.is_system:
        timeout_min = task.claim_timeout_minutes or settings.default_claim_timeout_minutes
        claim_deadline = now + timedelta(minutes=timeout_min)
        await session.execute(
            text("UPDATE tasks SET claim_deadline = :dl WHERE id = :id"),
            {"dl": claim_deadline, "id": task.id},
        )

    await session.commit()
    await session.refresh(task)

    # Enrich with poster reputation
    poster = await session.get(Agent, task.poster_id)
    poster_rep = poster.reputation if poster else None

    # Parse tags
    tags_parsed = safe_json_loads(task.tags)

    return {
        "task_id": task.id,
        "poster_id": task.poster_id,
        "need": task.need,
        "context": task.context,
        "max_credits": task.max_credits,
        "tags": tags_parsed,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "poster_reputation": poster_rep,
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "claim_deadline": task.claim_deadline.isoformat() if task.claim_deadline else None,
        "claim_timeout_minutes": task.claim_timeout_minutes,
    }


async def pickup_specific_task(session: AsyncSession, task_id: str, worker_id: str) -> dict | None:
    """Claim a specific task by ID. Validates eligibility."""
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    status = status_str(task.status)
    if status != "posted":
        raise HTTPException(status_code=409, detail=f"Task is {status}, not posted")

    if task.poster_id == worker_id:
        raise HTTPException(status_code=409, detail="Cannot pick up your own task")

    if task.is_system:
        raise HTTPException(status_code=409, detail="Cannot directly pick up system tasks")

    # Conflict rule: check if this agent did system work on this task
    conflict_result = await session.execute(
        select(Task).where(
            Task.is_system == True,  # noqa: E712
            Task.worker_id == worker_id,
            Task.parent_task_id == task_id,
        )
    )
    if conflict_result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Conflict: you did system work on this task")

    # Check abandon cooldown
    agent = await session.get(Agent, worker_id)
    if agent:
        _check_abandon_cooldown(agent)

    claimed = await _try_claim(session, task, worker_id)
    if not claimed:
        raise HTTPException(status_code=409, detail="Task already claimed")
    return claimed


async def deliver_task(
    session: AsyncSession,
    tid: str,
    worker_id: str,
    result: str,
    credits_claimed: int | None = None,
) -> dict:
    """Deliver work for a claimed task."""
    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.worker_id != worker_id:
        raise HTTPException(status_code=403, detail="Not your task")

    # Design #10: default credits_claimed to max_credits
    if credits_claimed is None:
        credits_claimed = task.max_credits
    actual_credits = min(credits_claimed, task.max_credits)

    # Atomic status transition to prevent concurrent delivery
    deliver_result = await session.execute(
        text(
            "UPDATE tasks SET status = 'delivered', result = :result, "
            "credits_charged = :credits, delivered_at = :now, "
            "claim_deadline = NULL "
            "WHERE id = :id AND status = 'claimed'"
        ),
        {
            "result": result,
            "credits": actual_credits,
            "now": datetime.now(UTC),
            "id": tid,
        },
    )
    if deliver_result.rowcount == 0:
        status = status_str(task.status)
        raise HTTPException(status_code=409, detail=f"Task is {status}, not claimed")

    await session.refresh(task)

    # Process system task results
    if task.is_system and task.system_task_type == SystemTaskType.match_agents:
        await _process_match_result(session, task)
        await finalize_system_task_approval(session, task)
    elif task.is_system and task.system_task_type == SystemTaskType.verify_completion:
        await _process_verify_result(session, task)
        await finalize_system_task_approval(session, task)
    elif task.is_system and task.system_task_type == SystemTaskType.extract_capabilities:
        await _process_capability_result(session, task)
        await finalize_system_task_approval(session, task)
    else:
        # Regular task: spawn verification
        await _maybe_spawn_verification(session, task)

    # Bug #3 fix: do NOT increment tasks_completed here — only on approve
    await session.commit()

    # SSE: notify poster that task was delivered
    if not task.is_system:
        event_bus.publish(task.poster_id, Event(type="task_delivered", task_id=tid))

    # Bug #7 fix: signal event so wait_for_result unblocks
    _get_event(tid).set()

    return {
        "id": tid,
        "status": "delivered",
        "result": result,
        "credits_charged": actual_credits,
        "need": task.need,
        "context": task.context,
        "poster_id": task.poster_id,
        "worker_id": task.worker_id,
    }


async def approve_task(
    session: AsyncSession,
    tid: str,
    poster_id: str,
    rating: int | None = None,
    feedback: str | None = None,
) -> dict:
    """Approve delivery and release credits to worker."""
    from pinchwork.services.agents import update_reputation

    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.poster_id != poster_id:
        raise HTTPException(status_code=403, detail="Not your task")

    # Atomic status transition to prevent double-payment
    approve_result = await session.execute(
        text("UPDATE tasks SET status = 'approved' WHERE id = :id AND status = 'delivered'"),
        {"id": tid},
    )
    if approve_result.rowcount == 0:
        status = status_str(task.status)
        raise HTTPException(status_code=409, detail=f"Task is {status}, not delivered")

    await session.refresh(task)
    await _finalize_approval_credits(session, task, settings.platform_fee_percent)

    # Optional rating
    if rating is not None:
        r = Rating(task_id=tid, rater_id=poster_id, rated_id=task.worker_id, score=rating)
        session.add(r)
        await update_reputation(session, task.worker_id)

    # Update trust bidirectionally (positive)
    from pinchwork.services.trust import update_trust

    await update_trust(session, poster_id, task.worker_id, positive=True)
    await update_trust(session, task.worker_id, poster_id, positive=True)

    await session.commit()
    cleanup_task_event(tid)

    # SSE: notify worker that task was approved
    event_bus.publish(task.worker_id, Event(type="task_approved", task_id=tid))

    result_dict = {
        "id": task.id,
        "poster_id": task.poster_id,
        "worker_id": task.worker_id,
        "need": task.need,
        "context": task.context,
        "result": task.result,
        "status": "approved",
        "max_credits": task.max_credits,
        "credits_charged": task.credits_charged,
    }
    if rating is not None:
        result_dict["rating"] = rating
    if feedback is not None:
        result_dict["feedback"] = feedback
    return result_dict


async def reject_task(
    session: AsyncSession,
    tid: str,
    poster_id: str,
    reason: str,
    feedback: str | None = None,
) -> dict:
    """Reject delivery, reset task to claimed with grace period."""
    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.poster_id != poster_id:
        raise HTTPException(status_code=403, detail="Not your task")

    # Atomic status transition to prevent concurrent reject/approve race
    grace_deadline = datetime.now(UTC) + timedelta(minutes=settings.rejection_grace_minutes)
    reject_result = await session.execute(
        text(
            "UPDATE tasks SET status = 'claimed', result = NULL, "
            "credits_charged = NULL, delivered_at = NULL, "
            "rejection_reason = :reason, "
            "rejection_count = COALESCE(rejection_count, 0) + 1, "
            "rejection_grace_deadline = :grace, "
            "claim_deadline = :grace "
            "WHERE id = :id AND status = 'delivered'"
        ),
        {"reason": reason, "grace": grace_deadline, "id": tid},
    )
    if reject_result.rowcount == 0:
        status = status_str(task.status)
        raise HTTPException(status_code=409, detail=f"Task is {status}, not delivered")

    # Keep worker assigned during grace period so they can re-deliver
    rejected_worker_id = task.worker_id
    await session.refresh(task)

    # Update trust poster→worker (negative) — applies to both branches
    from pinchwork.services.trust import update_trust

    if rejected_worker_id:
        await update_trust(session, poster_id, rejected_worker_id, positive=False)

    # Check max rejections: if exceeded, release worker and reset to posted
    if task.rejection_count >= settings.max_rejections:
        new_expires = datetime.now(UTC) + timedelta(hours=settings.task_expire_hours)
        await session.execute(
            text(
                "UPDATE tasks SET status = 'posted', worker_id = NULL, "
                "claimed_at = NULL, claim_deadline = NULL, "
                "rejection_grace_deadline = NULL, "
                "expires_at = :expires, match_status = 'broadcast' "
                "WHERE id = :id AND status = 'claimed'"
            ),
            {"expires": new_expires, "id": tid},
        )
        await session.refresh(task)

        await session.commit()

        if rejected_worker_id:
            event_bus.publish(
                rejected_worker_id,
                Event(
                    type="task_rejected",
                    task_id=tid,
                    data={
                        "reason": reason,
                        "max_rejections_reached": True,
                    },
                ),
            )

        return {
            "id": task.id,
            "poster_id": task.poster_id,
            "worker_id": None,
            "need": task.need,
            "context": task.context,
            "result": None,
            "status": "posted",
            "max_credits": task.max_credits,
            "credits_charged": None,
            "rejection_reason": reason,
            "rejection_count": task.rejection_count,
        }

    await session.commit()

    # SSE: notify worker that task was rejected (with grace deadline)
    if rejected_worker_id:
        event_bus.publish(
            rejected_worker_id,
            Event(
                type="task_rejected",
                task_id=tid,
                data={"reason": reason, "grace_deadline": grace_deadline.isoformat()},
            ),
        )

    return {
        "id": task.id,
        "poster_id": task.poster_id,
        "worker_id": rejected_worker_id,
        "need": task.need,
        "context": task.context,
        "result": None,
        "status": "claimed",
        "max_credits": task.max_credits,
        "credits_charged": None,
        "rejection_reason": reason,
        "rejection_count": task.rejection_count,
        "rejection_grace_deadline": grace_deadline.isoformat(),
    }


async def cancel_task(session: AsyncSession, tid: str, poster_id: str) -> dict:
    """Cancel a posted task and refund credits. Only poster, only if posted."""
    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.poster_id != poster_id:
        raise HTTPException(status_code=403, detail="Not your task")

    # Atomic status transition
    cancel_result = await session.execute(
        text("UPDATE tasks SET status = 'cancelled' WHERE id = :id AND status = 'posted'"),
        {"id": tid},
    )
    if cancel_result.rowcount == 0:
        status = status_str(task.status)
        raise HTTPException(
            status_code=409, detail=f"Task is {status}, can only cancel posted tasks"
        )

    # Collect matched agent IDs before commit for SSE notification
    match_result = await session.execute(select(TaskMatch.agent_id).where(TaskMatch.task_id == tid))
    matched_agent_ids = [row[0] for row in match_result.fetchall()]

    await session.refresh(task)
    await refund(session, tid, poster_id, task.max_credits)
    await session.commit()
    cleanup_task_event(tid)

    # SSE: notify matched agents that task was cancelled
    event_bus.publish_many(matched_agent_ids, Event(type="task_cancelled", task_id=tid))

    return {
        "id": task.id,
        "poster_id": task.poster_id,
        "worker_id": None,
        "need": task.need,
        "context": task.context,
        "result": None,
        "status": "cancelled",
        "max_credits": task.max_credits,
        "credits_charged": None,
    }


async def abandon_task(session: AsyncSession, tid: str, worker_id: str) -> dict:
    """Worker gives back a claimed task. Resets to posted with fresh expiry."""
    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    status = status_str(task.status)
    if status != "claimed":
        raise HTTPException(status_code=409, detail=f"Task is {status}, not claimed")
    if task.worker_id != worker_id:
        raise HTTPException(status_code=403, detail="Not your task")

    # Atomic status transition
    new_expires = datetime.now(UTC) + timedelta(hours=settings.task_expire_hours)
    abandon_result = await session.execute(
        text(
            "UPDATE tasks SET status = 'posted', worker_id = NULL, claimed_at = NULL, "
            "claim_deadline = NULL, expires_at = :expires, match_status = 'broadcast' "
            "WHERE id = :id AND status = 'claimed'"
        ),
        {"expires": new_expires, "id": tid},
    )
    if abandon_result.rowcount == 0:
        raise HTTPException(status_code=409, detail="Task already changed status")

    await session.refresh(task)

    # Track abandon on the worker
    worker = await session.get(Agent, worker_id)
    if worker:
        worker.abandon_count = (worker.abandon_count or 0) + 1
        worker.last_abandon_at = datetime.now(UTC)
        session.add(worker)

    await session.commit()

    return {
        "id": task.id,
        "poster_id": task.poster_id,
        "worker_id": None,
        "need": task.need,
        "context": task.context,
        "status": "posted",
        "max_credits": task.max_credits,
    }


async def wait_for_result(session: AsyncSession, tid: str, timeout: int) -> dict | None:
    """Wait for task delivery using asyncio.Event instead of polling."""
    event = _get_event(tid)
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(event.wait(), timeout=timeout)

    # Re-fetch the task state after waiting
    await session.expire_all()
    task = await session.get(Task, tid)
    if task:
        status = status_str(task.status)
        if status in ("delivered", "approved"):
            return {
                "id": task.id,
                "poster_id": task.poster_id,
                "worker_id": task.worker_id,
                "need": task.need,
                "context": task.context,
                "result": task.result,
                "status": status,
                "max_credits": task.max_credits,
                "credits_charged": task.credits_charged,
            }
    return await get_task(session, tid)


def _apply_search_filter(query, search: str | None):
    """Apply case-insensitive text search on need and context."""
    if search:
        term = f"%{search}%"
        query = query.where((Task.need.ilike(term)) | (Task.context.ilike(term)))
    return query


async def list_available_tasks(
    session: AsyncSession,
    worker_id: str,
    tags: list[str] | None = None,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """List available tasks without claiming. Same priority as pickup."""
    agent = await session.get(Agent, worker_id)
    if not agent:
        return {"tasks": [], "total": 0}

    conflict_subquery = _build_conflict_subquery(worker_id)

    # Phase 1: Matched tasks
    matched_subquery = select(TaskMatch.task_id).where(TaskMatch.agent_id == worker_id)
    q_matched = select(Task).where(
        Task.status == TaskStatus.posted,
        Task.poster_id != worker_id,
        Task.is_system == False,  # noqa: E712
        Task.match_status == MatchStatus.matched,
        Task.id.in_(matched_subquery),
        Task.id.not_in(conflict_subquery),
    )

    # Phase 2: Broadcast + pending tasks
    q_broadcast = select(Task).where(
        Task.status == TaskStatus.posted,
        Task.poster_id != worker_id,
        Task.is_system == False,  # noqa: E712
        Task.match_status.in_([MatchStatus.broadcast, MatchStatus.pending]),
        Task.id.not_in(conflict_subquery),
    )

    # Apply tag and search filters
    q_matched = _apply_tag_filters(q_matched, tags)
    q_broadcast = _apply_tag_filters(q_broadcast, tags)
    q_matched = _apply_search_filter(q_matched, search)
    q_broadcast = _apply_search_filter(q_broadcast, search)

    # Gather all tasks in priority order
    r1 = await session.execute(q_matched)
    r2 = await session.execute(q_broadcast.order_by(Task.created_at.asc()))

    matched_tasks = list(r1.scalars().all())
    broadcast_tasks = list(r2.scalars().all())

    # Sort matched tasks by rank
    if matched_tasks:
        rank_result = await session.execute(
            select(TaskMatch.task_id, TaskMatch.rank).where(
                TaskMatch.agent_id == worker_id,
                TaskMatch.task_id.in_([t.id for t in matched_tasks]),
            )
        )
        rank_map = {row[0]: row[1] for row in rank_result.fetchall()}
        matched_tasks.sort(key=lambda t: rank_map.get(t.id, 999))

    agent_tags = _load_agent_capability_tags(agent)

    # Sort broadcast tasks by tag overlap (if agent has capability tags)
    if agent_tags and broadcast_tasks:
        broadcast_tasks.sort(key=lambda t: (-_compute_tag_overlap(t, agent_tags), t.created_at))

    # Batch-fetch poster reputations
    all_tasks = matched_tasks + broadcast_tasks
    poster_ids = list({t.poster_id for t in all_tasks})
    rep_map: dict[str, float] = {}
    if poster_ids:
        rep_result = await session.execute(
            select(Agent.id, Agent.reputation).where(Agent.id.in_(poster_ids))
        )
        rep_map = {row[0]: row[1] for row in rep_result.fetchall()}

    # Build match info map
    matched_task_ids = {t.id for t in matched_tasks}
    match_rank_map: dict[str, int] = {}
    if matched_tasks:
        mr = await session.execute(
            select(TaskMatch.task_id, TaskMatch.rank).where(
                TaskMatch.agent_id == worker_id,
                TaskMatch.task_id.in_(list(matched_task_ids)),
            )
        )
        match_rank_map = {row[0]: row[1] for row in mr.fetchall()}

    total = len(all_tasks)
    page = all_tasks[offset : offset + limit]

    def _task_to_dict(t: Task) -> dict:
        tags_parsed = safe_json_loads(t.tags)
        return {
            "task_id": t.id,
            "need": t.need,
            "context": t.context,
            "max_credits": t.max_credits,
            "tags": tags_parsed,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "poster_id": t.poster_id,
            "poster_reputation": rep_map.get(t.poster_id),
            "is_matched": t.id in matched_task_ids,
            "match_rank": match_rank_map.get(t.id),
            "rejection_count": t.rejection_count or 0,
            "deadline": t.deadline.isoformat() if t.deadline else None,
        }

    return {"tasks": [_task_to_dict(t) for t in page], "total": total}


_VALID_ROLES = {"poster", "worker"}
_VALID_STATUSES = {s.value for s in TaskStatus}


async def list_my_tasks(
    session: AsyncSession,
    agent_id: str,
    role: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """List tasks where this agent is poster and/or worker."""
    if role is not None and role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {role}")
    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    queries = []

    if role in (None, "poster"):
        q = select(Task).where(Task.poster_id == agent_id, Task.is_system == False)  # noqa: E712
        if status:
            q = q.where(Task.status == status)
        queries.append(q)

    if role in (None, "worker"):
        q = select(Task).where(Task.worker_id == agent_id, Task.is_system == False)  # noqa: E712
        if status:
            q = q.where(Task.status == status)
        queries.append(q)

    all_tasks: list[Task] = []
    seen_ids: set[str] = set()
    for q in queries:
        result = await session.execute(q.order_by(Task.created_at.desc()))
        for t in result.scalars().all():
            if t.id not in seen_ids:
                seen_ids.add(t.id)
                all_tasks.append(t)

    # Sort by created_at descending
    all_tasks.sort(key=lambda t: t.created_at or datetime.min, reverse=True)
    total = len(all_tasks)
    page = all_tasks[offset : offset + limit]

    def _task_to_response(t: Task) -> dict:
        s = status_str(t.status)
        return {
            "task_id": t.id,
            "status": s,
            "need": t.need,
            "context": t.context,
            "result": t.result,
            "credits_charged": t.credits_charged,
            "poster_id": t.poster_id,
            "worker_id": t.worker_id,
            "deadline": t.deadline.isoformat() if t.deadline else None,
            "claim_deadline": t.claim_deadline.isoformat() if t.claim_deadline else None,
            "review_timeout_minutes": t.review_timeout_minutes,
            "claim_timeout_minutes": t.claim_timeout_minutes,
        }

    return {"tasks": [_task_to_response(t) for t in page], "total": total}


async def create_report(session: AsyncSession, task_id: str, reporter_id: str, reason: str) -> dict:
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Only poster or worker may report a task
    if reporter_id != task.poster_id and reporter_id != task.worker_id:
        raise HTTPException(status_code=403, detail="Only poster or worker may report this task")

    rid = make_report_id()
    report = Report(id=rid, task_id=task_id, reporter_id=reporter_id, reason=reason)
    session.add(report)
    await session.commit()
    return {"report_id": rid, "task_id": task_id, "reason": reason, "status": "open"}


async def rate_poster(
    session: AsyncSession,
    task_id: str,
    worker_id: str,
    rating: int,
    feedback: str | None = None,
) -> dict:
    """Worker rates the poster after task completion."""
    from pinchwork.services.agents import update_reputation

    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    status = status_str(task.status)
    if status != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"Task is {status}, not approved",
        )
    if task.worker_id != worker_id:
        raise HTTPException(status_code=403, detail="Not your task")

    # Prevent duplicate ratings
    existing = await session.execute(
        select(Rating).where(Rating.task_id == task_id, Rating.rater_id == worker_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already rated")

    r = Rating(
        task_id=task_id,
        rater_id=worker_id,
        rated_id=task.poster_id,
        score=rating,
    )
    session.add(r)
    await update_reputation(session, task.poster_id)

    # Update trust worker→poster based on rating
    from pinchwork.services.trust import update_trust

    await update_trust(session, worker_id, task.poster_id, positive=(rating >= 3))

    await session.commit()

    result = {"task_id": task_id, "rated_id": task.poster_id, "rating": rating}
    if feedback:
        result["feedback"] = feedback
    return result


# ---------------------------------------------------------------------------
# Task Questions (pre-pickup clarification)
# ---------------------------------------------------------------------------

MAX_UNANSWERED_QUESTIONS = 5


def _question_to_dict(q: TaskQuestion) -> dict:
    return {
        "id": q.id,
        "task_id": q.task_id,
        "asker_id": q.asker_id,
        "question": q.question,
        "answer": q.answer,
        "created_at": q.created_at.isoformat() if q.created_at else None,
        "answered_at": q.answered_at.isoformat() if q.answered_at else None,
    }


async def ask_question(session: AsyncSession, task_id: str, asker_id: str, question: str) -> dict:
    """Ask a question about a task before picking it up."""
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.poster_id == asker_id:
        raise HTTPException(status_code=409, detail="Cannot ask questions on your own task")
    if status_str(task.status) != "posted":
        raise HTTPException(status_code=409, detail="Can only ask questions on posted tasks")

    # Check unanswered question limit
    unanswered = await session.execute(
        select(TaskQuestion).where(
            TaskQuestion.task_id == task_id,
            TaskQuestion.answer.is_(None),
        )
    )
    if len(unanswered.scalars().all()) >= MAX_UNANSWERED_QUESTIONS:
        raise HTTPException(
            status_code=429,
            detail=f"Max {MAX_UNANSWERED_QUESTIONS} unanswered questions per task",
        )

    qid = make_question_id()
    tq = TaskQuestion(id=qid, task_id=task_id, asker_id=asker_id, question=question)
    session.add(tq)
    await session.commit()

    # SSE: notify poster
    event_bus.publish(
        task.poster_id, Event(type="task_question", task_id=task_id, data={"question_id": qid})
    )

    return _question_to_dict(tq)


async def answer_question(
    session: AsyncSession, task_id: str, question_id: str, poster_id: str, answer: str
) -> dict:
    """Answer a question on your task."""
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.poster_id != poster_id:
        raise HTTPException(status_code=403, detail="Only the poster can answer questions")

    tq = await session.get(TaskQuestion, question_id)
    if not tq or tq.task_id != task_id:
        raise HTTPException(status_code=404, detail="Question not found")
    if tq.answer is not None:
        raise HTTPException(status_code=409, detail="Question already answered")

    tq.answer = answer
    tq.answered_at = datetime.now(UTC)
    session.add(tq)
    await session.commit()

    # SSE: notify asker
    event_bus.publish(
        tq.asker_id,
        Event(type="question_answered", task_id=task_id, data={"question_id": question_id}),
    )

    return _question_to_dict(tq)


async def list_questions(session: AsyncSession, task_id: str) -> list[dict]:
    """List all questions for a task."""
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    result = await session.execute(
        select(TaskQuestion)
        .where(TaskQuestion.task_id == task_id)
        .order_by(TaskQuestion.created_at.asc())
    )
    return [_question_to_dict(q) for q in result.scalars().all()]


# ---------------------------------------------------------------------------
# Mid-Task Messaging
# ---------------------------------------------------------------------------


async def send_message(session: AsyncSession, task_id: str, sender_id: str, message: str) -> dict:
    """Send a message on a claimed or delivered task (poster/worker only)."""
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    status = status_str(task.status)
    if status not in ("claimed", "delivered"):
        raise HTTPException(
            status_code=409,
            detail=f"Task is {status}, messages only allowed on claimed/delivered tasks",
        )

    if sender_id != task.poster_id and sender_id != task.worker_id:
        raise HTTPException(status_code=403, detail="Only poster or worker can send messages")

    mid = make_message_id()
    msg = TaskMessage(
        id=mid,
        task_id=task_id,
        sender_id=sender_id,
        message=message,
    )
    session.add(msg)
    await session.commit()

    # SSE: notify the other party
    recipient = task.worker_id if sender_id == task.poster_id else task.poster_id
    if recipient:
        event_bus.publish(
            recipient,
            Event(type="task_message", task_id=task_id, data={"message_id": mid}),
        )

    return {
        "id": mid,
        "task_id": task_id,
        "sender_id": sender_id,
        "message": message,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


async def list_messages(session: AsyncSession, task_id: str, agent_id: str) -> list[dict]:
    """List messages for a task (poster/worker only, also readable on approved tasks)."""
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if agent_id != task.poster_id and agent_id != task.worker_id:
        raise HTTPException(status_code=403, detail="Only poster or worker can view messages")

    result = await session.execute(
        select(TaskMessage)
        .where(TaskMessage.task_id == task_id)
        .order_by(TaskMessage.created_at.asc())
    )
    return [
        {
            "id": m.id,
            "task_id": m.task_id,
            "sender_id": m.sender_id,
            "message": m.message,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in result.scalars().all()
    ]


# ---------------------------------------------------------------------------
# Batch Pickup
# ---------------------------------------------------------------------------


async def pickup_batch(
    session: AsyncSession,
    worker_id: str,
    count: int = 5,
    tags: list[str] | None = None,
    search: str | None = None,
) -> list[dict]:
    """Pick up multiple tasks at once. Each claim is individually atomic."""
    results: list[dict] = []
    for _ in range(count):
        task = await pickup_task(session, worker_id, tags=tags, search=search)
        if not task:
            break
        results.append(task)
    return results
