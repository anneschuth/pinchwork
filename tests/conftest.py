"""Test fixtures with in-memory SQLite via SQLModel."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from pinchwork.database import get_db_session
from pinchwork.db_models import (  # noqa: F401 — register tables
    Agent,
    CreditLedger,
    Rating,
    Task,
    TaskMatch,
)
from pinchwork.main import app


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://", echo=False, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]

    async def override_get_db_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session

    yield factory

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
async def client(db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def register_agent(client: AsyncClient, name: str = "test-agent") -> dict:
    """Helper: register an agent, return {"agent_id", "api_key"}."""
    resp = await client.post(
        "/v1/register",
        json={"name": name},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 201
    return resp.json()


def auth_header(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


@pytest.fixture
async def registered_agent(client):
    """Register an agent and return (client, agent_id, api_key)."""
    data = await register_agent(client, "test-agent")
    return client, data["agent_id"], data["api_key"]


@pytest.fixture
async def two_agents(client):
    """Register two agents: a poster and a worker."""
    d1 = await register_agent(client, "poster")
    d2 = await register_agent(client, "worker")
    return {
        "client": client,
        "poster": {"id": d1["agent_id"], "key": d1["api_key"]},
        "worker": {"id": d2["agent_id"], "key": d2["api_key"]},
    }
