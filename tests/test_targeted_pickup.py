"""Tests for targeted task pickup (POST /v1/tasks/{task_id}/pickup)."""

from __future__ import annotations

import pytest

from tests.conftest import auth_header, register_agent


@pytest.mark.anyio
async def test_pickup_specific_task(two_agents):
    """Worker can claim a specific task by ID."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    resp = await c.post(
        "/v1/tasks",
        json={"need": "specific pickup", "max_credits": 15},
        headers=auth_header(poster["key"]),
    )
    task_id = resp.json()["task_id"]

    resp = await c.post(f"/v1/tasks/{task_id}/pickup", headers=auth_header(worker["key"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == task_id
    assert body["need"] == "specific pickup"
    assert body["max_credits"] == 15


@pytest.mark.anyio
async def test_pickup_specific_already_claimed(two_agents):
    """Can't claim a task that's already claimed."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    resp = await c.post(
        "/v1/tasks",
        json={"need": "double claim", "max_credits": 10},
        headers=auth_header(poster["key"]),
    )
    task_id = resp.json()["task_id"]

    # First claim succeeds
    await c.post(f"/v1/tasks/{task_id}/pickup", headers=auth_header(worker["key"]))

    # Register a third agent to try claiming
    d3 = await register_agent(c, "third")
    resp = await c.post(f"/v1/tasks/{task_id}/pickup", headers=auth_header(d3["api_key"]))
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_pickup_specific_own_task(two_agents):
    """Can't pick up your own task."""
    c = two_agents["client"]
    poster = two_agents["poster"]

    resp = await c.post(
        "/v1/tasks",
        json={"need": "self claim", "max_credits": 10},
        headers=auth_header(poster["key"]),
    )
    task_id = resp.json()["task_id"]

    resp = await c.post(f"/v1/tasks/{task_id}/pickup", headers=auth_header(poster["key"]))
    assert resp.status_code == 409
    assert "own task" in resp.json()["error"].lower()


@pytest.mark.anyio
async def test_pickup_specific_nonexistent(client):
    """Can't pick up a nonexistent task."""
    data = await register_agent(client, "picker")
    resp = await client.post(
        "/v1/tasks/tk_nonexistent/pickup",
        headers=auth_header(data["api_key"]),
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_blind_pickup_still_works(two_agents):
    """Regular blind pickup still works (regression test)."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    resp = await c.post(
        "/v1/tasks",
        json={"need": "blind pickup", "max_credits": 10},
        headers=auth_header(poster["key"]),
    )
    task_id = resp.json()["task_id"]

    resp = await c.post("/v1/tasks/pickup", headers=auth_header(worker["key"]))
    assert resp.status_code == 200
    assert resp.json()["task_id"] == task_id


@pytest.mark.anyio
async def test_pickup_specific_delivered_task(two_agents):
    """Can't pick up a task that's already delivered."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    resp = await c.post(
        "/v1/tasks",
        json={"need": "delivered test", "max_credits": 10},
        headers=auth_header(poster["key"]),
    )
    task_id = resp.json()["task_id"]

    # Claim and deliver
    await c.post(f"/v1/tasks/{task_id}/pickup", headers=auth_header(worker["key"]))
    await c.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "done"},
        headers=auth_header(worker["key"]),
    )

    # Third agent tries to pick up
    d3 = await register_agent(c, "latecomer")
    resp = await c.post(f"/v1/tasks/{task_id}/pickup", headers=auth_header(d3["api_key"]))
    assert resp.status_code == 409
