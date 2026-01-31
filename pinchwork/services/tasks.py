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
from pinchwork.db_models import Agent, Rating, Report, Task, TaskMatch, TaskStatus
from pinchwork.events import Event, event_bus
from pinchwork.ids import match_id as make_match_id
from pinchwork.ids import report_id as make_report_id
from pinchwork.ids import task_id as make_task_id
from pinchwork.services.credits import escrow, refund, release_to_worker, release_to_worker_with_fee

logger = logging.getLogger("pinchwork.tasks")

# Event registry for wait_for_result (Bug #7 fix)
_task_events: dict[str, asyncio.Event] = {}


def _get_event(tid: str) -> asyncio.Event:
    if tid not in _task_events:
        _task_events[tid] = asyncio.Event()
    return _task_events[tid]


def _cleanup_event(tid: str) -> None:
    _task_events.pop(tid, None)


# ---------------------------------------------------------------------------
# Matching & verification helpers
# ---------------------------------------------------------------------------


async def _maybe_spawn_matching(session: AsyncSession, task: Task) -> None:
    """Create a match_agents system task if any infra agents exist."""
    result = await session.execute(
        select(Agent).where(
            Agent.accepts_system_tasks.is_(True), Agent.id != settings.platform_agent_id
        )
    )
    infra_agents = result.scalars().all()
    if not infra_agents:
        task.match_status = "broadcast"
        session.add(task)
        return

    # Build agent list for the matching prompt
    all_agents_result = await session.execute(
        select(Agent).where(Agent.id != settings.platform_agent_id, Agent.good_at != None)  # noqa: E711
    )
    agents_with_skills = all_agents_result.scalars().all()
    agent_list = [{"id": a.id, "good_at": a.good_at} for a in agents_with_skills]

    context_line = f"\nContext: {task.context}\n" if task.context else ""
    need = (
        f"Match agents for: {task.need}\n{context_line}\n"
        f"Available agents:\n{json.dumps(agent_list)}\n\n"
        'Return JSON: {"ranked_agents": ["agent_id_1", "agent_id_2", ...]}'
    )

    system_tid = make_task_id()
    system_task = Task(
        id=system_tid,
        poster_id=settings.platform_agent_id,
        need=need,
        max_credits=settings.match_credits,
        is_system=True,
        system_task_type="match_agents",
        parent_task_id=task.id,
        expires_at=datetime.now(UTC) + timedelta(hours=settings.task_expire_hours),
    )
    session.add(system_task)

    task.match_status = "pending"
    task.match_deadline = datetime.now(UTC) + timedelta(seconds=settings.match_timeout_seconds)
    session.add(task)


async def _maybe_spawn_verification(session: AsyncSession, task: Task) -> None:
    """Create a verify_completion system task if any infra agents exist."""
    result = await session.execute(
        select(Agent).where(
            Agent.accepts_system_tasks.is_(True), Agent.id != settings.platform_agent_id
        )
    )
    infra_agents = result.scalars().all()
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
        system_task_type="verify_completion",
        parent_task_id=task.id,
        expires_at=datetime.now(UTC) + timedelta(hours=settings.task_expire_hours),
    )
    session.add(system_task)

    task.verification_status = "pending"
    session.add(task)


async def _process_match_result(session: AsyncSession, system_task: Task) -> None:
    """Parse match result and create TaskMatch rows."""
    parent = await session.get(Task, system_task.parent_task_id)
    if not parent:
        return

    try:
        result_data = json.loads(system_task.result)
        ranked_agents = result_data.get("ranked_agents", [])
    except (json.JSONDecodeError, TypeError):
        parent.match_status = "broadcast"
        session.add(parent)
        return

    if not ranked_agents:
        parent.match_status = "broadcast"
        session.add(parent)
        return

    for rank, agent_id in enumerate(ranked_agents):
        tm = TaskMatch(
            id=make_match_id(),
            task_id=parent.id,
            agent_id=agent_id,
            rank=rank,
        )
        session.add(tm)

    parent.match_status = "matched"
    session.add(parent)


async def _process_verify_result(session: AsyncSession, system_task: Task) -> None:
    """Parse verification result and update parent task."""
    parent = await session.get(Task, system_task.parent_task_id)
    if not parent:
        return

    try:
        result_data = json.loads(system_task.result)
        meets = result_data.get("meets_requirements", False)
    except (json.JSONDecodeError, TypeError):
        parent.verification_status = "failed"
        parent.verification_result = json.dumps(
            {"meets_requirements": False, "explanation": "Failed to parse verification result"}
        )
        session.add(parent)
        return

    parent.verification_result = system_task.result
    if meets:
        parent.verification_status = "passed"
        # Auto-approve if still in delivered state
        status = parent.status.value if isinstance(parent.status, TaskStatus) else parent.status
        if status == "delivered":
            credits = parent.credits_charged or 0
            remaining = parent.max_credits - credits

            await release_to_worker_with_fee(
                session, parent.id, parent.worker_id, parent.poster_id,
                credits, settings.platform_fee_percent,
            )
            if remaining > 0:
                await refund(session, parent.id, parent.poster_id, remaining)

            parent.status = TaskStatus.approved
            await session.execute(
                text("UPDATE agents SET tasks_completed = tasks_completed + 1 WHERE id = :id"),
                {"id": parent.worker_id},
            )
    else:
        parent.verification_status = "failed"

    session.add(parent)


async def _auto_approve_system_task(session: AsyncSession, system_task: Task) -> None:
    """Auto-approve a system task immediately (platform is both poster and approver)."""
    credits = system_task.credits_charged or 0
    if system_task.worker_id:
        await release_to_worker(session, system_task.id, system_task.worker_id, credits)
        remaining = system_task.max_credits - credits
        if remaining > 0:
            # No refund needed for system tasks (no escrow was taken)
            pass
        await session.execute(
            text("UPDATE agents SET tasks_completed = tasks_completed + 1 WHERE id = :id"),
            {"id": system_task.worker_id},
        )

    system_task.status = TaskStatus.approved
    session.add(system_task)


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
) -> dict:
    """Create a task and escrow credits atomically in one transaction."""
    tid = make_task_id()
    expires_at = datetime.now(UTC) + timedelta(hours=settings.task_expire_hours)
    tags_json = json.dumps(tags) if tags else None

    task = Task(
        id=tid,
        poster_id=poster_id,
        need=need,
        context=context,
        max_credits=max_credits,
        tags=tags_json,
        expires_at=expires_at,
    )
    session.add(task)
    # Flush so the task row exists for FK on ledger
    await session.flush()

    # Atomic escrow (Bug #1 fix — single UPDATE with balance check)
    await escrow(session, poster_id, tid, max_credits)

    await session.execute(
        text("UPDATE agents SET tasks_posted = tasks_posted + 1 WHERE id = :id"),
        {"id": poster_id},
    )

    # Spawn matching system task
    await _maybe_spawn_matching(session, task)

    await session.commit()

    return {"id": tid, "status": "posted", "need": need, "max_credits": max_credits}


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
        "status": task.status.value if isinstance(task.status, TaskStatus) else task.status,
        "max_credits": task.max_credits,
        "credits_charged": task.credits_charged,
        "tags": task.tags,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "delivered_at": task.delivered_at.isoformat() if task.delivered_at else None,
        "expires_at": task.expires_at.isoformat() if task.expires_at else None,
    }


def _check_abandon_cooldown(agent: Agent) -> None:
    """Raise 429 if agent has too many recent abandons."""
    if (
        (agent.abandon_count or 0) >= settings.max_abandons_before_cooldown
        and agent.last_abandon_at
    ):
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


async def pickup_task(
    session: AsyncSession, worker_id: str, tags: list[str] | None = None
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

    # Conflict rule: exclude tasks where this agent did system work
    # (i.e., tasks whose parent_task_id points to a task where worker_id = me)
    conflict_subquery = select(Task.parent_task_id).where(
        Task.is_system == True,  # noqa: E712
        Task.worker_id == worker_id,
        Task.parent_task_id != None,  # noqa: E711
    )

    # Phase 1: Matched tasks (tasks where this agent has a TaskMatch row)
    matched_subquery = select(TaskMatch.task_id).where(TaskMatch.agent_id == worker_id)
    query = select(Task).where(
        Task.status == TaskStatus.posted,
        Task.poster_id != worker_id,
        Task.is_system == False,  # noqa: E712
        Task.match_status == "matched",
        Task.id.in_(matched_subquery),
        Task.id.not_in(conflict_subquery),
    )

    if tags:
        for tag in tags:
            query = query.where(Task.tags.contains(f'"{tag}"'))

    # Order by rank (join with TaskMatch)
    query = query.limit(10)
    result = await session.execute(query)
    matched_tasks = result.scalars().all()

    if matched_tasks:
        # Sort by match rank
        for t in matched_tasks:
            claimed = await _try_claim(session, t, worker_id)
            if claimed:
                return claimed

    # Phase 2: Broadcast + pending tasks (FIFO)
    query2 = (
        select(Task)
        .where(
            Task.status == TaskStatus.posted,
            Task.poster_id != worker_id,
            Task.is_system == False,  # noqa: E712
            Task.match_status.in_(["broadcast", "pending"]),
            Task.id.not_in(conflict_subquery),
        )
        .order_by(Task.created_at.asc())
    )

    if tags:
        for tag in tags:
            query2 = query2.where(Task.tags.contains(f'"{tag}"'))

    query2 = query2.limit(1)
    result2 = await session.execute(query2)
    task2 = result2.scalar_one_or_none()

    if task2:
        return await _try_claim(session, task2, worker_id)

    # Phase 3: Tasks with no match_status (backwards compat / non-system tasks)
    query3 = (
        select(Task)
        .where(
            Task.status == TaskStatus.posted,
            Task.poster_id != worker_id,
            Task.is_system == False,  # noqa: E712
            Task.match_status == None,  # noqa: E711
            Task.id.not_in(conflict_subquery),
        )
        .order_by(Task.created_at.asc())
        .limit(1)
    )

    if tags:
        for tag in tags:
            query3 = query3.where(Task.tags.contains(f'"{tag}"'))

    result3 = await session.execute(query3)
    task3 = result3.scalar_one_or_none()

    if task3:
        return await _try_claim(session, task3, worker_id)

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
    claim_result = await session.execute(
        text(
            "UPDATE tasks SET status = 'claimed', worker_id = :worker_id, "
            "claimed_at = :now WHERE id = :id AND status = 'posted'"
        ),
        {"worker_id": worker_id, "now": datetime.now(UTC).isoformat(), "id": task.id},
    )
    if claim_result.rowcount == 0:
        return None

    await session.commit()
    await session.refresh(task)

    return {
        "task_id": task.id,
        "poster_id": task.poster_id,
        "need": task.need,
        "context": task.context,
        "max_credits": task.max_credits,
    }


async def pickup_specific_task(
    session: AsyncSession, task_id: str, worker_id: str
) -> dict | None:
    """Claim a specific task by ID. Validates eligibility."""
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    status = task.status.value if isinstance(task.status, TaskStatus) else task.status
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
        raise HTTPException(
            status_code=409, detail="Conflict: you did system work on this task"
        )

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
    status = task.status.value if isinstance(task.status, TaskStatus) else task.status
    if status != "claimed":
        raise HTTPException(status_code=409, detail=f"Task is {status}, not claimed")
    if task.worker_id != worker_id:
        raise HTTPException(status_code=403, detail="Not your task")

    # Design #10: default credits_claimed to max_credits
    if credits_claimed is None:
        credits_claimed = task.max_credits
    actual_credits = min(credits_claimed, task.max_credits)

    task.status = TaskStatus.delivered
    task.result = result
    task.credits_charged = actual_credits
    task.delivered_at = datetime.now(UTC)
    session.add(task)

    # Process system task results
    if task.is_system and task.system_task_type == "match_agents":
        await _process_match_result(session, task)
        await _auto_approve_system_task(session, task)
    elif task.is_system and task.system_task_type == "verify_completion":
        await _process_verify_result(session, task)
        await _auto_approve_system_task(session, task)
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
    status = task.status.value if isinstance(task.status, TaskStatus) else task.status
    if status != "delivered":
        raise HTTPException(status_code=409, detail=f"Task is {status}, not delivered")
    if task.poster_id != poster_id:
        raise HTTPException(status_code=403, detail="Not your task")

    credits = task.credits_charged or 0
    remaining = task.max_credits - credits

    await release_to_worker_with_fee(
        session, tid, task.worker_id, poster_id, credits, settings.platform_fee_percent,
    )
    if remaining > 0:
        await refund(session, tid, poster_id, remaining)

    task.status = TaskStatus.approved
    session.add(task)

    # Bug #3 fix: increment tasks_completed on approve, not deliver
    await session.execute(
        text("UPDATE agents SET tasks_completed = tasks_completed + 1 WHERE id = :id"),
        {"id": task.worker_id},
    )

    # Optional rating
    if rating is not None:
        r = Rating(task_id=tid, rater_id=poster_id, rated_id=task.worker_id, score=rating)
        session.add(r)
        await update_reputation(session, task.worker_id)

    await session.commit()
    _cleanup_event(tid)

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


async def reject_task(session: AsyncSession, tid: str, poster_id: str) -> dict:
    """Reject delivery, reset task to posted with fresh expiry."""
    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    status = task.status.value if isinstance(task.status, TaskStatus) else task.status
    if status != "delivered":
        raise HTTPException(status_code=409, detail=f"Task is {status}, not delivered")
    if task.poster_id != poster_id:
        raise HTTPException(status_code=403, detail="Not your task")

    # Capture worker_id before clearing for SSE notification
    rejected_worker_id = task.worker_id

    # Bug #2 fix: reset expires_at to fresh window
    task.status = TaskStatus.posted
    task.worker_id = None
    task.result = None
    task.credits_charged = None
    task.delivered_at = None
    task.claimed_at = None
    task.expires_at = datetime.now(UTC) + timedelta(hours=settings.task_expire_hours)
    session.add(task)
    await session.commit()

    # SSE: notify worker that task was rejected
    if rejected_worker_id:
        event_bus.publish(rejected_worker_id, Event(type="task_rejected", task_id=tid))

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
    }


async def cancel_task(session: AsyncSession, tid: str, poster_id: str) -> dict:
    """Cancel a posted task and refund credits. Only poster, only if posted."""
    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    status = task.status.value if isinstance(task.status, TaskStatus) else task.status
    if status != "posted":
        raise HTTPException(
            status_code=409, detail=f"Task is {status}, can only cancel posted tasks"
        )
    if task.poster_id != poster_id:
        raise HTTPException(status_code=403, detail="Not your task")

    # Collect matched agent IDs before commit for SSE notification
    match_result = await session.execute(
        select(TaskMatch.agent_id).where(TaskMatch.task_id == tid)
    )
    matched_agent_ids = [row[0] for row in match_result.fetchall()]

    task.status = TaskStatus.cancelled
    session.add(task)

    await refund(session, tid, poster_id, task.max_credits)
    await session.commit()
    _cleanup_event(tid)

    # SSE: notify matched agents that task was cancelled
    event_bus.publish_many(
        matched_agent_ids, Event(type="task_cancelled", task_id=tid)
    )

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
    status = task.status.value if isinstance(task.status, TaskStatus) else task.status
    if status != "claimed":
        raise HTTPException(status_code=409, detail=f"Task is {status}, not claimed")
    if task.worker_id != worker_id:
        raise HTTPException(status_code=403, detail="Not your task")

    task.status = TaskStatus.posted
    task.worker_id = None
    task.claimed_at = None
    task.expires_at = datetime.now(UTC) + timedelta(hours=settings.task_expire_hours)
    task.match_status = "broadcast"
    session.add(task)

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
        status = task.status.value if isinstance(task.status, TaskStatus) else task.status
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


async def list_available_tasks(
    session: AsyncSession,
    worker_id: str,
    tags: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """List available tasks without claiming. Same priority as pickup."""
    agent = await session.get(Agent, worker_id)
    if not agent:
        return {"tasks": [], "total": 0}

    # Conflict rule: exclude tasks where this agent did system work
    conflict_subquery = select(Task.parent_task_id).where(
        Task.is_system == True,  # noqa: E712
        Task.worker_id == worker_id,
        Task.parent_task_id != None,  # noqa: E711
    )

    # Phase 1: Matched tasks
    matched_subquery = select(TaskMatch.task_id).where(TaskMatch.agent_id == worker_id)
    q_matched = select(Task).where(
        Task.status == TaskStatus.posted,
        Task.poster_id != worker_id,
        Task.is_system == False,  # noqa: E712
        Task.match_status == "matched",
        Task.id.in_(matched_subquery),
        Task.id.not_in(conflict_subquery),
    )

    # Phase 2: Broadcast + pending tasks
    q_broadcast = select(Task).where(
        Task.status == TaskStatus.posted,
        Task.poster_id != worker_id,
        Task.is_system == False,  # noqa: E712
        Task.match_status.in_(["broadcast", "pending"]),
        Task.id.not_in(conflict_subquery),
    )

    # Phase 3: Tasks with no match_status (backwards compat)
    q_none = select(Task).where(
        Task.status == TaskStatus.posted,
        Task.poster_id != worker_id,
        Task.is_system == False,  # noqa: E712
        Task.match_status == None,  # noqa: E711
        Task.id.not_in(conflict_subquery),
    )

    # Apply tag filters
    for q_ref in [q_matched, q_broadcast, q_none]:
        if tags:
            for tag in tags:
                q_ref = q_ref.where(Task.tags.contains(f'"{tag}"'))

    # Gather all tasks in priority order
    if tags:
        # Rebuild with tags applied
        q_matched_filtered = q_matched
        q_broadcast_filtered = q_broadcast
        q_none_filtered = q_none
        for tag in tags:
            q_matched_filtered = q_matched_filtered.where(Task.tags.contains(f'"{tag}"'))
            q_broadcast_filtered = q_broadcast_filtered.where(Task.tags.contains(f'"{tag}"'))
            q_none_filtered = q_none_filtered.where(Task.tags.contains(f'"{tag}"'))
        r1 = await session.execute(q_matched_filtered)
        r2 = await session.execute(q_broadcast_filtered.order_by(Task.created_at.asc()))
        r3 = await session.execute(q_none_filtered.order_by(Task.created_at.asc()))
    else:
        r1 = await session.execute(q_matched)
        r2 = await session.execute(q_broadcast.order_by(Task.created_at.asc()))
        r3 = await session.execute(q_none.order_by(Task.created_at.asc()))

    all_tasks = list(r1.scalars().all()) + list(r2.scalars().all()) + list(r3.scalars().all())
    total = len(all_tasks)
    page = all_tasks[offset : offset + limit]

    def _task_to_dict(t: Task) -> dict:
        tags_parsed = json.loads(t.tags) if t.tags else None
        return {
            "task_id": t.id,
            "need": t.need,
            "context": t.context,
            "max_credits": t.max_credits,
            "tags": tags_parsed,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "poster_id": t.poster_id,
        }

    return {"tasks": [_task_to_dict(t) for t in page], "total": total}


async def list_my_tasks(
    session: AsyncSession,
    agent_id: str,
    role: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """List tasks where this agent is poster and/or worker."""
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
        s = t.status.value if isinstance(t.status, TaskStatus) else t.status
        return {
            "task_id": t.id,
            "status": s,
            "need": t.need,
            "context": t.context,
            "result": t.result,
            "credits_charged": t.credits_charged,
            "poster_id": t.poster_id,
            "worker_id": t.worker_id,
        }

    return {"tasks": [_task_to_response(t) for t in page], "total": total}


async def create_report(
    session: AsyncSession, task_id: str, reporter_id: str, reason: str
) -> dict:
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

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
    status = task.status.value if isinstance(task.status, TaskStatus) else task.status
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
    await session.commit()

    result = {"task_id": task_id, "rated_id": task.poster_id, "rating": rating}
    if feedback:
        result["feedback"] = feedback
    return result
