"""Async SQLModel database setup."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from pinchwork.config import settings
from pinchwork.db_models import (  # noqa: F401 — register tables
    Agent,
    CreditLedger,
    Rating,
    Task,
    TaskMatch,
)

logger = logging.getLogger("pinchwork.database")

_engine = None
_session_factory = None


async def init_db(url: str = "sqlite+aiosqlite:///pinchwork.db") -> None:
    global _engine, _session_factory
    connect_args = {}
    if "sqlite" in url:
        connect_args["check_same_thread"] = False
    _engine = create_async_engine(url, echo=False, connect_args=connect_args)
    _session_factory = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]

    async with _engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        if "sqlite" in url:
            await conn.execute(__import__("sqlalchemy").text("PRAGMA journal_mode=WAL"))
            await conn.execute(__import__("sqlalchemy").text("PRAGMA foreign_keys=ON"))

    await _ensure_platform_agent()


async def _ensure_platform_agent() -> None:
    """Create the well-known platform agent if it doesn't exist."""
    assert _session_factory is not None
    async with _session_factory() as session:
        existing = await session.get(Agent, settings.platform_agent_id)
        if not existing:
            platform = Agent(
                id=settings.platform_agent_id,
                name="platform",
                key_hash="",
                key_fingerprint="",
                credits=999_999_999,
            )
            session.add(platform)
            await session.commit()
            logger.info("Created platform agent %s", settings.platform_agent_id)


async def close_db() -> None:
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    assert _session_factory is not None, "Database not initialised — call init_db() first"
    async with _session_factory() as session:
        yield session


def get_session_factory() -> sessionmaker:
    assert _session_factory is not None
    return _session_factory
