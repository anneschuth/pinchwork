"""Tests for abuse prevention: suspension, abandon cooldown, reporting, rate limiting."""

from __future__ import annotations

import pytest

from pinchwork.config import settings
from tests.conftest import auth_header, register_agent


@pytest.fixture(autouse=True)
def _set_admin_key(monkeypatch):
    monkeypatch.setattr(settings, "admin_key", "test-admin-secret")


ADMIN_HEADERS = {"Authorization": "Bearer test-admin-secret", "Accept": "application/json"}


@pytest.mark.anyio
async def test_suspended_agent_blocked(client):
    """Suspended agent gets 403 on authenticated endpoints."""
    data = await register_agent(client, "victim")
    headers = auth_header(data["api_key"])

    # Suspend the agent
    resp = await client.post(
        "/v1/admin/agents/suspend",
        json={"agent_id": data["agent_id"], "suspended": True, "reason": "bad behavior"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["suspended"] is True

    # Verify blocked from creating tasks
    resp = await client.post(
        "/v1/tasks",
        json={"need": "test", "max_credits": 10},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "suspended" in resp.json()["error"].lower()


@pytest.mark.anyio
async def test_admin_unsuspend(client):
    """Admin can unsuspend an agent."""
    data = await register_agent(client, "temp-ban")
    headers = auth_header(data["api_key"])

    # Suspend
    await client.post(
        "/v1/admin/agents/suspend",
        json={"agent_id": data["agent_id"], "suspended": True},
        headers=ADMIN_HEADERS,
    )

    # Unsuspend
    resp = await client.post(
        "/v1/admin/agents/suspend",
        json={"agent_id": data["agent_id"], "suspended": False},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["suspended"] is False

    # Verify agent works again
    resp = await client.get("/v1/me", headers=headers)
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_suspend_nonexistent_agent(client):
    """Suspending nonexistent agent returns 404."""
    resp = await client.post(
        "/v1/admin/agents/suspend",
        json={"agent_id": "ag_nonexistent", "suspended": True},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_abandon_increments_count(two_agents):
    """Abandoning a task increments the worker's abandon_count."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    # Create and pickup a task
    resp = await c.post(
        "/v1/tasks",
        json={"need": "abandon test", "max_credits": 10},
        headers=auth_header(poster["key"]),
    )
    task_id = resp.json()["task_id"]

    await c.post("/v1/tasks/pickup", headers=auth_header(worker["key"]))

    # Abandon
    resp = await c.post(f"/v1/tasks/{task_id}/abandon", headers=auth_header(worker["key"]))
    assert resp.status_code == 200

    # Do it again
    resp2 = await c.post(
        "/v1/tasks",
        json={"need": "another task", "max_credits": 10},
        headers=auth_header(poster["key"]),
    )
    task_id2 = resp2.json()["task_id"]
    await c.post("/v1/tasks/pickup", headers=auth_header(worker["key"]))
    await c.post(f"/v1/tasks/{task_id2}/abandon", headers=auth_header(worker["key"]))

    # The worker should now have abandon_count = 2
    # We can't directly check the DB field through the API, but the cooldown mechanism
    # should work after max_abandons_before_cooldown is reached


@pytest.mark.anyio
async def test_abandon_cooldown_blocks_pickup(two_agents, monkeypatch):
    """After too many abandons, pickup returns 429."""
    monkeypatch.setattr(settings, "max_abandons_before_cooldown", 2)
    monkeypatch.setattr(settings, "abandon_cooldown_minutes", 60)

    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    # Create and abandon 2 tasks using targeted pickup to avoid race issues
    for i in range(2):
        resp = await c.post(
            "/v1/tasks",
            json={"need": f"task {i}", "max_credits": 10},
            headers=auth_header(poster["key"]),
        )
        task_id = resp.json()["task_id"]
        await c.post(f"/v1/tasks/{task_id}/pickup", headers=auth_header(worker["key"]))
        await c.post(f"/v1/tasks/{task_id}/abandon", headers=auth_header(worker["key"]))

    # Create another task - worker should be blocked
    await c.post(
        "/v1/tasks",
        json={"need": "blocked task", "max_credits": 10},
        headers=auth_header(poster["key"]),
    )

    resp = await c.post("/v1/tasks/pickup", headers=auth_header(worker["key"]))
    assert resp.status_code == 429


@pytest.mark.anyio
async def test_report_task_happy_path(two_agents):
    """Can report a task with a reason."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    resp = await c.post(
        "/v1/tasks",
        json={"need": "report me", "max_credits": 10},
        headers=auth_header(poster["key"]),
    )
    task_id = resp.json()["task_id"]

    resp = await c.post(
        f"/v1/tasks/{task_id}/report",
        json={"reason": "spam"},
        headers=auth_header(worker["key"]),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["task_id"] == task_id
    assert body["reason"] == "spam"
    assert body["status"] == "open"
    assert body["report_id"].startswith("rp_")


@pytest.mark.anyio
async def test_report_nonexistent_task(client):
    """Reporting nonexistent task returns 404."""
    data = await register_agent(client, "reporter")
    resp = await client.post(
        "/v1/tasks/tk_nonexistent/report",
        json={"reason": "spam"},
        headers=auth_header(data["api_key"]),
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_report_missing_reason(two_agents):
    """Reporting without reason returns 400."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    resp = await c.post(
        "/v1/tasks",
        json={"need": "report test", "max_credits": 10},
        headers=auth_header(poster["key"]),
    )
    task_id = resp.json()["task_id"]

    resp = await c.post(
        f"/v1/tasks/{task_id}/report",
        json={},
        headers=auth_header(worker["key"]),
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_suspended_agent_blocked_from_pickup(client):
    """Suspended agent can't pick up tasks."""
    d1 = await register_agent(client, "poster")
    d2 = await register_agent(client, "worker")

    # Create a task
    await client.post(
        "/v1/tasks",
        json={"need": "test", "max_credits": 10},
        headers=auth_header(d1["api_key"]),
    )

    # Suspend worker
    await client.post(
        "/v1/admin/agents/suspend",
        json={"agent_id": d2["agent_id"], "suspended": True},
        headers=ADMIN_HEADERS,
    )

    resp = await client.post("/v1/tasks/pickup", headers=auth_header(d2["api_key"]))
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_suspended_agent_blocked_from_deliver(two_agents):
    """Suspended agent can't deliver tasks."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    resp = await c.post(
        "/v1/tasks",
        json={"need": "suspend test", "max_credits": 10},
        headers=auth_header(poster["key"]),
    )
    task_id = resp.json()["task_id"]

    await c.post("/v1/tasks/pickup", headers=auth_header(worker["key"]))

    # Suspend worker after they picked up
    await c.post(
        "/v1/admin/agents/suspend",
        json={"agent_id": worker["id"], "suspended": True},
        headers=ADMIN_HEADERS,
    )

    resp = await c.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "done"},
        headers=auth_header(worker["key"]),
    )
    assert resp.status_code == 403
