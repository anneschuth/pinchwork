"""Tests for the personal onboarding welcome task."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlmodel import select

from pinchwork.config import settings
from pinchwork.db_models import Agent, Task, TaskMatch
from tests.conftest import auth_header, register_agent


@pytest.fixture(autouse=True)
async def ensure_platform_agent(db):
    """Create the platform agent so welcome tasks can escrow credits."""
    async with db() as session:
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


@pytest.mark.asyncio
async def test_welcome_task_created_on_register(client, db):
    """Registering an agent creates a welcome task matched to that agent."""
    data = await register_agent(client, "newcomer")

    # Browse available tasks as the new agent
    resp = await client.get("/v1/tasks/available", headers=auth_header(data["api_key"]))
    assert resp.status_code == 200
    body = resp.json()
    tasks = body["tasks"]

    onboarding_tasks = [t for t in tasks if "onboarding" in (t.get("tags") or [])]
    assert len(onboarding_tasks) == 1
    assert onboarding_tasks[0]["is_matched"] is True
    assert "Welcome to Pinchwork" in onboarding_tasks[0]["need"]


@pytest.mark.asyncio
async def test_welcome_task_only_visible_to_new_agent(client, db):
    """Each agent's welcome task is only visible to them, not to other agents."""
    agent1 = await register_agent(client, "agent-one")
    agent2 = await register_agent(client, "agent-two")

    # Agent 1 should see only their own welcome task
    resp1 = await client.get("/v1/tasks/available", headers=auth_header(agent1["api_key"]))
    assert resp1.status_code == 200
    tasks1 = resp1.json()["tasks"]
    onboarding1 = [t for t in tasks1 if "onboarding" in (t.get("tags") or [])]
    assert len(onboarding1) == 1

    # Agent 2 should see only their own welcome task
    resp2 = await client.get("/v1/tasks/available", headers=auth_header(agent2["api_key"]))
    assert resp2.status_code == 200
    tasks2 = resp2.json()["tasks"]
    onboarding2 = [t for t in tasks2 if "onboarding" in (t.get("tags") or [])]
    assert len(onboarding2) == 1

    # The two welcome tasks should be different tasks
    assert onboarding1[0]["task_id"] != onboarding2[0]["task_id"]


@pytest.mark.asyncio
async def test_welcome_task_pickup_and_earn(client, db):
    """Full flow: register -> pickup welcome -> deliver -> approve -> credits increase."""
    data = await register_agent(client, "earner")
    api_key = data["api_key"]
    headers = auth_header(api_key)

    # Check initial credits
    resp = await client.get("/v1/me", headers=headers)
    assert resp.status_code == 200
    credits_before = resp.json()["credits"]

    # Pick up the welcome task
    resp = await client.post("/v1/tasks/pickup", headers=headers)
    assert resp.status_code == 200
    task = resp.json()
    assert "Welcome to Pinchwork" in task["need"]
    task_id = task["task_id"]

    # Deliver
    resp = await client.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "Hi! I'm earner, good at testing."},
        headers=headers,
    )
    assert resp.status_code == 200

    # Manually approve (background auto-approve doesn't run in tests).
    # The poster is the platform agent — use direct DB approval.
    from pinchwork.services.tasks import finalize_task_approval

    async with db() as session:
        task_obj = await session.get(Task, task_id)
        assert task_obj is not None
        await finalize_task_approval(session, task_obj, settings.platform_fee_percent)
        await session.commit()

    # Verify exact credit increase: worker_amount = credits - fee
    fee = int(settings.welcome_task_credits * settings.platform_fee_percent / 100)
    expected_earned = settings.welcome_task_credits - fee
    resp = await client.get("/v1/me", headers=headers)
    assert resp.status_code == 200
    credits_after = resp.json()["credits"]
    assert credits_after == credits_before + expected_earned


@pytest.mark.asyncio
async def test_welcome_task_not_created_when_disabled(client, db):
    """When welcome_task_enabled=False, no welcome task is created."""
    with patch.object(settings, "welcome_task_enabled", False):
        data = await register_agent(client, "no-welcome")

    # Browse available tasks — should see nothing
    resp = await client.get("/v1/tasks/available", headers=auth_header(data["api_key"]))
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    onboarding_tasks = [t for t in tasks if "onboarding" in (t.get("tags") or [])]
    assert len(onboarding_tasks) == 0


@pytest.mark.asyncio
async def test_welcome_task_has_match_row(client, db):
    """The welcome task creates a TaskMatch row linking the new agent."""
    data = await register_agent(client, "matched-agent")
    aid = data["agent_id"]

    async with db() as session:
        # Find the welcome task for this agent
        result = await session.execute(select(TaskMatch).where(TaskMatch.agent_id == aid))
        matches = list(result.scalars().all())
        assert len(matches) == 1
        assert matches[0].rank == 0

        # Verify the linked task is the welcome task
        task = await session.get(Task, matches[0].task_id)
        assert task is not None
        assert task.poster_id == settings.platform_agent_id
        assert "Welcome to Pinchwork" in task.need
        assert task.review_timeout_minutes == 1
