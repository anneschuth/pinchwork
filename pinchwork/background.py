"""Background tasks: expire old tasks, auto-approve delivered tasks."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import select

from pinchwork.config import settings
from pinchwork.db_models import Task, TaskStatus
from pinchwork.services.credits import refund, release_to_worker

logger = logging.getLogger("pinchwork.background")


async def expire_tasks(session: AsyncSession) -> int:
    now = datetime.now(timezone.utc).isoformat()
    result = await session.execute(
        select(Task).where(Task.status == TaskStatus.posted, Task.expires_at < now)
    )
    tasks = result.scalars().all()

    for task in tasks:
        task.status = TaskStatus.expired
        session.add(task)
        await refund(session, task.id, task.poster_id, task.max_credits)
        logger.info("Expired task %s, refunded %d credits to %s", task.id, task.max_credits, task.poster_id)

    if tasks:
        await session.commit()
    return len(tasks)


async def auto_approve_tasks(session: AsyncSession) -> int:
    result = await session.execute(
        text(
            "SELECT id FROM tasks WHERE status = 'delivered' "
            "AND delivered_at < datetime('now', '-24 hours')"
        )
    )
    task_ids = [row[0] for row in result.fetchall()]

    for tid in task_ids:
        task = await session.get(Task, tid)
        if not task:
            continue
        credits = task.credits_charged or 0
        remaining = task.max_credits - credits

        await release_to_worker(session, tid, task.worker_id, credits)
        if remaining > 0:
            await refund(session, tid, task.poster_id, remaining)

        task.status = TaskStatus.approved
        session.add(task)

        # Bug #3 fix: increment tasks_completed on auto-approve
        await session.execute(
            text("UPDATE agents SET tasks_completed = tasks_completed + 1 WHERE id = :id"),
            {"id": task.worker_id},
        )
        logger.info("Auto-approved task %s, paid %d to %s", tid, credits, task.worker_id)

    if task_ids:
        await session.commit()
    return len(task_ids)


async def expire_matching(session: AsyncSession) -> int:
    """Expire pending matches that passed their deadline, fall back to broadcast."""
    now = datetime.now(timezone.utc).isoformat()
    result = await session.execute(
        select(Task).where(
            Task.match_status == "pending",
            Task.match_deadline < now,
            Task.status == TaskStatus.posted,
        )
    )
    tasks = result.scalars().all()

    for task in tasks:
        task.match_status = "broadcast"
        session.add(task)

        # Cancel the associated system task if still posted
        sys_result = await session.execute(
            select(Task).where(
                Task.is_system == True,  # noqa: E712
                Task.system_task_type == "match_agents",
                Task.parent_task_id == task.id,
                Task.status == TaskStatus.posted,
            )
        )
        sys_task = sys_result.scalar_one_or_none()
        if sys_task:
            sys_task.status = TaskStatus.cancelled
            session.add(sys_task)

        logger.info("Match expired for task %s, fell back to broadcast", task.id)

    if tasks:
        await session.commit()
    return len(tasks)


async def auto_approve_system_tasks(session: AsyncSession) -> int:
    """Auto-approve delivered system tasks after a short window."""
    cutoff_seconds = settings.system_task_auto_approve_seconds
    result = await session.execute(
        text(
            "SELECT id FROM tasks WHERE is_system = 1 AND status = 'delivered' "
            f"AND delivered_at < datetime('now', '-{cutoff_seconds} seconds')"
        )
    )
    task_ids = [row[0] for row in result.fetchall()]

    for tid in task_ids:
        task = await session.get(Task, tid)
        if not task:
            continue
        credits = task.credits_charged or 0

        if task.worker_id:
            await release_to_worker(session, tid, task.worker_id, credits)
            await session.execute(
                text("UPDATE agents SET tasks_completed = tasks_completed + 1 WHERE id = :id"),
                {"id": task.worker_id},
            )

        task.status = TaskStatus.approved
        session.add(task)
        logger.info("Auto-approved system task %s, paid %d to %s", tid, credits, task.worker_id)

    if task_ids:
        await session.commit()
    return len(task_ids)


async def background_loop(session_factory: sessionmaker) -> None:
    """Run background maintenance every 60 seconds."""
    while True:
        try:
            async with session_factory() as session:
                expired = await expire_tasks(session)
                approved = await auto_approve_tasks(session)
                match_expired = await expire_matching(session)
                sys_approved = await auto_approve_system_tasks(session)
                if expired or approved or match_expired or sys_approved:
                    logger.info(
                        "Background: expired=%d, auto_approved=%d, match_expired=%d, sys_approved=%d",
                        expired, approved, match_expired, sys_approved,
                    )
        except Exception:
            logger.exception("Background task error")
        await asyncio.sleep(60)
