"""Tests for the agent matching system via system tasks."""

from __future__ import annotations

import json
from datetime import UTC

import pytest
from httpx import AsyncClient

from pinchwork.config import settings
from pinchwork.db_models import Task, TaskStatus
from tests.conftest import auth_header, register_agent


async def _register_infra_agent(client: AsyncClient, name: str = "infra") -> dict:
    """Register an agent that accepts system tasks."""
    data = await register_agent(client, name)
    # Update via PATCH /v1/me to set accepts_system_tasks and good_at
    resp = await client.patch(
        "/v1/me",
        json={"accepts_system_tasks": True, "good_at": "matching, verification"},
        headers=auth_header(data["api_key"]),
    )
    assert resp.status_code == 200
    return data


async def _register_skilled_agent(client: AsyncClient, name: str, good_at: str) -> dict:
    """Register an agent with specific skills."""
    data = await register_agent(client, name)
    resp = await client.patch(
        "/v1/me",
        json={"good_at": good_at},
        headers=auth_header(data["api_key"]),
    )
    assert resp.status_code == 200
    return data


@pytest.mark.asyncio
async def test_match_spawned_on_task_create(client, db):
    """When an infra agent exists, creating a task should spawn a match_agents system task."""
    poster = await register_agent(client, "poster")
    infra = await _register_infra_agent(client, "infra")
    await _register_skilled_agent(client, "worker", "Dutch translation")

    # Create a task
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Translate document to Dutch", "max_credits": 10},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201

    # Infra agent should be able to pick up a system task
    resp = await client.post(
        "/v1/tasks/pickup",
        headers=auth_header(infra["api_key"]),
    )
    assert resp.status_code == 200
    pickup = resp.json()
    assert "Match agents for:" in pickup["need"]
    assert pickup["poster_id"] == settings.platform_agent_id


@pytest.mark.asyncio
async def test_no_matching_without_infra_agents(client, db):
    """Without infra agents, task should go straight to broadcast."""
    poster = await register_agent(client, "poster")
    worker = await register_agent(client, "worker")

    resp = await client.post(
        "/v1/tasks",
        json={"need": "Simple task", "max_credits": 10},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201

    # Worker should be able to pick up the task directly (broadcast)
    resp = await client.post(
        "/v1/tasks/pickup",
        headers=auth_header(worker["api_key"]),
    )
    assert resp.status_code == 200
    assert resp.json()["need"] == "Simple task"


@pytest.mark.asyncio
async def test_matched_agent_gets_priority(client, db):
    """After matching, the matched agent should see the task first."""
    poster = await register_agent(client, "poster")
    infra = await _register_infra_agent(client, "infra")
    alice = await _register_skilled_agent(client, "alice", "Dutch translation")
    bob = await _register_skilled_agent(client, "bob", "Python coding")

    # Create task
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Translate to Dutch", "max_credits": 10},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]

    # Infra picks up the match system task
    resp = await client.post(
        "/v1/tasks/pickup",
        headers=auth_header(infra["api_key"]),
    )
    assert resp.status_code == 200
    system_task_id = resp.json()["task_id"]

    # Infra delivers match result ranking alice first
    match_result = json.dumps({"ranked_agents": [alice["agent_id"], bob["agent_id"]]})
    resp = await client.post(
        f"/v1/tasks/{system_task_id}/deliver",
        json={"result": match_result},
        headers=auth_header(infra["api_key"]),
    )
    assert resp.status_code == 200

    # Alice should be able to pick up the task (matched)
    resp = await client.post(
        "/v1/tasks/pickup",
        headers=auth_header(alice["api_key"]),
    )
    assert resp.status_code == 200
    assert resp.json()["task_id"] == task_id


@pytest.mark.asyncio
async def test_pending_task_still_pickable(client, db):
    """Tasks with match_status=pending can still be picked up (deprioritized, not hidden)."""
    poster = await register_agent(client, "poster")
    await _register_infra_agent(client, "infra")
    worker = await register_agent(client, "worker")

    # Create task (match_status will be "pending" since infra agent exists)
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Pending task", "max_credits": 10},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201

    # Worker (non-infra) should still be able to pick up the pending task
    resp = await client.post(
        "/v1/tasks/pickup",
        headers=auth_header(worker["api_key"]),
    )
    assert resp.status_code == 200
    assert resp.json()["need"] == "Pending task"


@pytest.mark.asyncio
async def test_broadcast_fallback_on_timeout(client, db):
    """When match deadline passes, background loop sets match_status to broadcast."""
    from pinchwork.background import expire_matching

    poster = await register_agent(client, "poster")
    await _register_infra_agent(client, "infra")

    # Create task
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Task to expire match", "max_credits": 10},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]

    # Manually set match_deadline to the past
    async with db() as session:
        task = await session.get(Task, task_id)
        from datetime import datetime, timedelta

        task.match_deadline = datetime.now(UTC) - timedelta(seconds=10)
        session.add(task)
        await session.commit()

    # Run background expire_matching
    async with db() as session:
        count = await expire_matching(session)
        assert count == 1

    # Verify task is now broadcast
    async with db() as session:
        task = await session.get(Task, task_id)
        assert task.match_status == "broadcast"


@pytest.mark.asyncio
async def test_conflict_rule_prevents_pickup(client, db):
    """Agent who did matching for a task cannot pick up that task."""
    poster = await register_agent(client, "poster")
    infra = await _register_infra_agent(client, "infra")
    # Also give infra agent some skills so it could theoretically match
    resp = await client.patch(
        "/v1/me",
        json={"good_at": "Dutch translation, matching, verification"},
        headers=auth_header(infra["api_key"]),
    )

    # Create task
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Translate to Dutch", "max_credits": 10},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201

    # Infra picks up system task
    resp = await client.post(
        "/v1/tasks/pickup",
        headers=auth_header(infra["api_key"]),
    )
    assert resp.status_code == 200
    system_task_id = resp.json()["task_id"]
    assert "Match agents for:" in resp.json()["need"]

    # Deliver match result (even ranking itself)
    match_result = json.dumps({"ranked_agents": [infra["agent_id"]]})
    resp = await client.post(
        f"/v1/tasks/{system_task_id}/deliver",
        json={"result": match_result},
        headers=auth_header(infra["api_key"]),
    )
    assert resp.status_code == 200

    # Infra tries to pick up the actual task — should be blocked by conflict rule
    resp = await client.post(
        "/v1/tasks/pickup",
        headers=auth_header(infra["api_key"]),
    )
    assert resp.status_code == 204  # No tasks available (conflict rule)


@pytest.mark.asyncio
async def test_system_task_only_visible_to_infra_agents(client, db):
    """Non-infra agents should not see system tasks in pickup."""
    poster = await register_agent(client, "poster")
    await _register_infra_agent(client, "infra")
    regular = await register_agent(client, "regular")

    # Create task (spawns system task)
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Some task", "max_credits": 10},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201

    # Regular agent tries pickup — should get the regular task (pending), not the system task
    resp = await client.post(
        "/v1/tasks/pickup",
        headers=auth_header(regular["api_key"]),
    )
    assert resp.status_code == 200
    assert "Match agents for:" not in resp.json()["need"]
    assert resp.json()["need"] == "Some task"


@pytest.mark.asyncio
async def test_system_task_auto_approved(client, db):
    """System tasks are auto-approved on delivery."""
    poster = await register_agent(client, "poster")
    infra = await _register_infra_agent(client, "infra")

    # Create task
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Test auto approve", "max_credits": 10},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201

    # Infra picks up system task
    resp = await client.post(
        "/v1/tasks/pickup",
        headers=auth_header(infra["api_key"]),
    )
    assert resp.status_code == 200
    system_task_id = resp.json()["task_id"]

    # Deliver match result
    match_result = json.dumps({"ranked_agents": []})
    resp = await client.post(
        f"/v1/tasks/{system_task_id}/deliver",
        json={"result": match_result},
        headers=auth_header(infra["api_key"]),
    )
    assert resp.status_code == 200

    # System task should be auto-approved
    async with db() as session:
        sys_task = await session.get(Task, system_task_id)
        status = (
            sys_task.status.value if isinstance(sys_task.status, TaskStatus) else sys_task.status
        )
        assert status == "approved"


@pytest.mark.asyncio
async def test_update_agent_capabilities(client, db):
    """PATCH /v1/me updates agent capabilities."""
    agent = await register_agent(client, "test-agent")

    resp = await client.patch(
        "/v1/me",
        json={"good_at": "Python, data analysis", "accepts_system_tasks": True},
        headers=auth_header(agent["api_key"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["good_at"] == "Python, data analysis"
    assert data["accepts_system_tasks"] is True

    # Verify via GET /v1/me
    resp = await client.get("/v1/me", headers=auth_header(agent["api_key"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["good_at"] == "Python, data analysis"
    assert data["accepts_system_tasks"] is True


@pytest.mark.asyncio
async def test_register_with_good_at(client, db):
    """Registration accepts good_at and accepts_system_tasks."""
    resp = await client.post(
        "/v1/register",
        json={"name": "skilled", "good_at": "Dutch translation", "accepts_system_tasks": True},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 201
    data = resp.json()

    # Verify via GET /v1/me
    resp = await client.get("/v1/me", headers=auth_header(data["api_key"]))
    assert resp.status_code == 200
    me = resp.json()
    assert me["good_at"] == "Dutch translation"
    assert me["accepts_system_tasks"] is True


@pytest.mark.asyncio
async def test_full_matching_cycle(client, db):
    """End-to-end: create task, match, deliver match, matched agent picks up, delivers, approves."""
    poster = await register_agent(client, "poster")
    infra = await _register_infra_agent(client, "infra")
    worker = await _register_skilled_agent(client, "worker", "Dutch translation")

    # 1. Create task
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Translate to Dutch", "max_credits": 20},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]

    # 2. Infra picks up system task
    resp = await client.post(
        "/v1/tasks/pickup",
        headers=auth_header(infra["api_key"]),
    )
    assert resp.status_code == 200
    system_task_id = resp.json()["task_id"]

    # 3. Infra delivers match result
    match_result = json.dumps({"ranked_agents": [worker["agent_id"]]})
    resp = await client.post(
        f"/v1/tasks/{system_task_id}/deliver",
        json={"result": match_result},
        headers=auth_header(infra["api_key"]),
    )
    assert resp.status_code == 200

    # 4. Worker picks up the matched task
    resp = await client.post(
        "/v1/tasks/pickup",
        headers=auth_header(worker["api_key"]),
    )
    assert resp.status_code == 200
    assert resp.json()["task_id"] == task_id

    # 5. Worker delivers
    resp = await client.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "Dit is de Nederlandse vertaling."},
        headers=auth_header(worker["api_key"]),
    )
    assert resp.status_code == 200

    # 6. Poster approves
    resp = await client.post(
        f"/v1/tasks/{task_id}/approve",
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
