"""Async SQLModel database setup."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from pinchwork.config import settings
from pinchwork.db_models import (  # noqa: F401 — register tables
    Agent,
    AgentTrust,
    CreditLedger,
    MatchStatus,
    Rating,
    Report,
    SystemTaskType,
    Task,
    TaskMatch,
    TaskMessage,
    VerificationStatus,
)

logger = logging.getLogger("pinchwork.database")

_engine = None
_session_factory = None

# Absolute path to the migrations directory (sibling of pinchwork/ package)
_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


async def init_db(url: str = "sqlite+aiosqlite:///pinchwork.db") -> None:
    global _engine, _session_factory
    connect_args = {}
    if "sqlite" in url:
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 30
    _engine = create_async_engine(url, echo=False, connect_args=connect_args, pool_pre_ping=True)
    _session_factory = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]

    async with _engine.begin() as conn:
        if "sqlite" in url:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        await _run_alembic_upgrade(conn)

    await _ensure_platform_agent()


async def _run_alembic_upgrade(conn) -> None:
    """Run Alembic migrations using the existing async connection.

    Handles three scenarios:
    1. Fresh database — runs all migrations from scratch.
    2. Existing DB created with create_all (no alembic_version table) —
       stamps at revision 001 (baseline), then applies pending migrations.
    3. Existing DB with alembic_version — applies pending migrations only.
    """
    import sqlalchemy
    from alembic import command
    from alembic.config import Config

    def _do_upgrade(sync_conn):
        from alembic.migration import MigrationContext
        from alembic.script import ScriptDirectory

        alembic_cfg = Config()
        alembic_cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
        # Pass connection so env.py uses it instead of creating a new engine
        alembic_cfg.attributes["connection"] = sync_conn

        # Check current state
        migration_ctx = MigrationContext.configure(sync_conn)
        current_rev = migration_ctx.get_current_revision()
        inspector = sqlalchemy.inspect(sync_conn)
        existing_tables = set(inspector.get_table_names())

        has_alembic_version = "alembic_version" in existing_tables
        has_existing_tables = "agents" in existing_tables

        if has_existing_tables and not has_alembic_version:
            # Scenario 2: DB was created with create_all, no Alembic tracking.
            # Stamp at 001 (baseline) so Alembic knows the tables exist,
            # then apply 002+ which adds the missing referral columns.
            logger.info(
                "Existing database detected without Alembic tracking. "
                "Stamping at revision 001 (baseline), then upgrading."
            )
            command.stamp(alembic_cfg, "001")
            command.upgrade(alembic_cfg, "head")
        elif has_alembic_version:
            # Scenario 3: Normal upgrade — apply pending migrations
            script = ScriptDirectory.from_config(alembic_cfg)
            head_rev = script.get_current_head()
            if current_rev != head_rev:
                logger.info(
                    "Upgrading database from %s to %s",
                    current_rev or "(empty)",
                    head_rev,
                )
                command.upgrade(alembic_cfg, "head")
            else:
                logger.debug("Database schema is up to date at revision %s", current_rev)
        else:
            # Scenario 1: Fresh database — run all migrations
            logger.info("Fresh database — running all migrations")
            command.upgrade(alembic_cfg, "head")

    # Alembic's command API is synchronous; run_sync bridges the gap
    await conn.run_sync(_do_upgrade)


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
