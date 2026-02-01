"""Alembic environment configuration for Pinchwork.

Supports both async (aiosqlite) and sync execution contexts.
Uses batch mode for SQLite compatibility (ALTER TABLE limitations).
"""

from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from pinchwork.db_models import *  # noqa: F401, F403 — register all tables

logger = logging.getLogger("alembic.env")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL script)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    If a connection was passed via config.attributes (from database.py
    at app startup), use that. Otherwise create a new engine from config
    (for CLI usage via `alembic upgrade head`).
    """
    connectable = config.attributes.get("connection")

    if connectable is not None:
        # Connection injected from database.py — use it directly
        context.configure(
            connection=connectable,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        # CLI usage — create engine from alembic.ini or settings
        url = config.get_main_option("sqlalchemy.url")
        if not url:
            # Fall back to app settings (sync sqlite URL for CLI)
            from pinchwork.config import settings

            db_path = settings.database_url
            if not db_path.startswith("sqlite"):
                url = f"sqlite:///{db_path}"
            else:
                url = db_path.replace("sqlite+aiosqlite", "sqlite")
            config.set_main_option("sqlalchemy.url", url)

        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
