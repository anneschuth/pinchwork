"""Credit escrow and ledger service — SQLModel."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pinchwork.db_models import Agent, CreditLedger
from pinchwork.ids import ledger_id


async def record_credit(
    session: AsyncSession,
    agent_id: str,
    amount: int,
    reason: str,
    task_id: str | None = None,
) -> None:
    entry = CreditLedger(id=ledger_id(), agent_id=agent_id, amount=amount, reason=reason, task_id=task_id)
    session.add(entry)


async def escrow(session: AsyncSession, poster_id: str, task_id: str, amount: int, *, is_system: bool = False) -> None:
    """Atomic escrow: single UPDATE with balance check to prevent race conditions.

    System tasks skip escrow entirely (platform agent has infinite credits).
    """
    if is_system:
        return

    result = await session.execute(
        text(
            "UPDATE agents SET credits = credits - :amount "
            "WHERE id = :id AND credits >= :amount"
        ),
        {"amount": amount, "id": poster_id},
    )
    if result.rowcount == 0:
        # Fetch current balance for error message
        agent = await session.get(Agent, poster_id)
        have = agent.credits if agent else 0
        raise HTTPException(status_code=402, detail=f"Insufficient credits. Have {have}, need {amount}")

    await record_credit(session, poster_id, -amount, "escrow", task_id)


async def release_to_worker(
    session: AsyncSession, task_id: str, worker_id: str, amount: int
) -> None:
    await session.execute(
        text("UPDATE agents SET credits = credits + :amount WHERE id = :id"),
        {"amount": amount, "id": worker_id},
    )
    await record_credit(session, worker_id, amount, "payment", task_id)


async def refund(session: AsyncSession, task_id: str, poster_id: str, amount: int) -> None:
    await session.execute(
        text("UPDATE agents SET credits = credits + :amount WHERE id = :id"),
        {"amount": amount, "id": poster_id},
    )
    await record_credit(session, poster_id, amount, "refund", task_id)


async def get_balance(session: AsyncSession, agent_id: str) -> int:
    agent = await session.get(Agent, agent_id)
    return agent.credits if agent else 0


async def get_ledger(
    session: AsyncSession, agent_id: str, offset: int = 0, limit: int = 50
) -> tuple[list[dict], int]:
    """Return (entries, total_count)."""
    # Total count
    count_result = await session.execute(
        select(func.count()).select_from(CreditLedger).where(CreditLedger.agent_id == agent_id)
    )
    total = count_result.scalar_one()

    result = await session.execute(
        select(CreditLedger)
        .where(CreditLedger.agent_id == agent_id)
        .order_by(CreditLedger.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.scalars().all()
    entries = [
        {
            "id": r.id,
            "amount": r.amount,
            "reason": r.reason,
            "task_id": r.task_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return entries, total
