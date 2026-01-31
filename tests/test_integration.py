"""Integration smoke tests: full end-to-end flows through the HTTP API.

These mirror the manual smoke tests that would be run against a Docker container,
but use the in-memory test client for speed and isolation.
"""

from __future__ import annotations

import json
from datetime import UTC

import pytest

from pinchwork.db_models import Task, TaskStatus
from tests.conftest import auth_header


async def _reg(client, name, **kwargs):
    """Register agent with optional capabilities."""
    resp = await client.post(
        "/v1/register",
        json={"name": name, **kwargs},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 201
    return resp.json()


async def _pickup_system_tasks(client, infra, worker_id=None):
    """Pick up and deliver all pending system tasks for infra agent.

    Returns list of system task types processed.
    """
    processed = []
    for _ in range(10):
        resp = await client.post("/v1/tasks/pickup", headers=auth_header(infra["api_key"]))
        if resp.status_code == 204:
            break
        picked = resp.json()
        need = picked["need"]

        if "Match agents for:" in need:
            agents = [worker_id] if worker_id else []
            result = json.dumps({"ranked_agents": agents})
            task_type = "match_agents"
        elif "Verify completion" in need:
            result = json.dumps({"meets_requirements": True, "explanation": "Looks good"})
            task_type = "verify_completion"
        else:
            break  # Not a system task

        resp = await client.post(
            f"/v1/tasks/{picked['task_id']}/deliver",
            json={"result": result},
            headers=auth_header(infra["api_key"]),
        )
        assert resp.status_code == 200
        processed.append(task_type)

    return processed


# ---------------------------------------------------------------------------
# Health & skill.md
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health(client, db):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_skill_md_documents_new_features(client, db):
    resp = await client.get("/skill.md")
    assert resp.status_code == 200
    body = resp.text
    assert "PATCH" in body
    assert "good_at" in body
    assert "accepts_system_tasks" in body
    assert "Infra Agents" in body


# ---------------------------------------------------------------------------
# Agent capabilities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_with_capabilities(client, db):
    agent = await _reg(client, "skilled", good_at="Dutch translation", accepts_system_tasks=True)

    resp = await client.get("/v1/me", headers=auth_header(agent["api_key"]))
    me = resp.json()
    assert me["good_at"] == "Dutch translation"
    assert me["accepts_system_tasks"] is True


@pytest.mark.asyncio
async def test_patch_me_updates_capabilities(client, db):
    agent = await _reg(client, "plain")

    resp = await client.patch(
        "/v1/me",
        json={"good_at": "Python, data analysis", "accepts_system_tasks": True},
        headers=auth_header(agent["api_key"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["good_at"] == "Python, data analysis"
    assert data["accepts_system_tasks"] is True


# ---------------------------------------------------------------------------
# Full matching cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_matching_and_verification_cycle(client, db):
    """End-to-end: create -> match -> pickup -> deliver -> verify -> auto-approve."""
    infra = await _reg(client, "infra", good_at="matching", accepts_system_tasks=True)
    worker = await _reg(client, "worker", good_at="Dutch translation")
    poster = await _reg(client, "poster")

    # 1. Create task
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Translate to Dutch", "max_credits": 20},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]

    # 2. Infra picks up match_agents system task
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(infra["api_key"]))
    assert resp.status_code == 200
    sys_pickup = resp.json()
    assert sys_pickup["poster_id"] == "ag_platform"
    assert "Match agents for:" in sys_pickup["need"]

    # 3. Deliver match result
    match_result = json.dumps({"ranked_agents": [worker["agent_id"]]})
    resp = await client.post(
        f"/v1/tasks/{sys_pickup['task_id']}/deliver",
        json={"result": match_result},
        headers=auth_header(infra["api_key"]),
    )
    assert resp.status_code == 200

    # 4. Matched worker picks up the task
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(worker["api_key"]))
    assert resp.status_code == 200
    assert resp.json()["task_id"] == task_id

    # 5. Worker delivers
    resp = await client.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "Dit is de vertaling."},
        headers=auth_header(worker["api_key"]),
    )
    assert resp.status_code == 200

    # 6. Infra picks up verify_completion system task
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(infra["api_key"]))
    assert resp.status_code == 200
    assert "Verify completion" in resp.json()["need"]
    verify_tid = resp.json()["task_id"]

    # 7. Deliver verification (pass)
    verify_result = json.dumps({"meets_requirements": True, "explanation": "Correct"})
    resp = await client.post(
        f"/v1/tasks/{verify_tid}/deliver",
        json={"result": verify_result},
        headers=auth_header(infra["api_key"]),
    )
    assert resp.status_code == 200

    # 8. Task should be auto-approved
    async with db() as session:
        task = await session.get(Task, task_id)
        status = task.status.value if isinstance(task.status, TaskStatus) else task.status
        assert status == "approved"
        assert task.verification_status == "passed"


# ---------------------------------------------------------------------------
# Broadcast fallback (no infra agents)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_infra_agents_broadcast_fallback(client, db):
    """Without infra agents, tasks go straight to broadcast and are pickable."""
    poster = await _reg(client, "poster")
    worker = await _reg(client, "worker")

    resp = await client.post(
        "/v1/tasks",
        json={"need": "Simple task", "max_credits": 10},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]

    # Worker picks it up directly
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(worker["api_key"]))
    assert resp.status_code == 200
    assert resp.json()["task_id"] == task_id
    assert resp.json()["need"] == "Simple task"


# ---------------------------------------------------------------------------
# Pending tasks are pickable (not hidden)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_task_pickable_by_non_matched_worker(client, db):
    """Tasks with match_status=pending are still pickable, just deprioritized."""
    await _reg(client, "infra", accepts_system_tasks=True, good_at="matching")
    poster = await _reg(client, "poster")
    worker = await _reg(client, "worker")

    resp = await client.post(
        "/v1/tasks",
        json={"need": "Pending test", "max_credits": 5},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]

    # Worker picks up the pending task
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(worker["api_key"]))
    assert resp.status_code == 200
    assert resp.json()["task_id"] == task_id


# ---------------------------------------------------------------------------
# Conflict rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conflict_rule_blocks_matcher_from_pickup(client, db):
    """Agent who matched a task cannot pick up that same task."""
    infra = await _reg(client, "infra", good_at="matching, Dutch", accepts_system_tasks=True)
    poster = await _reg(client, "poster")

    # Create task
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Conflict test", "max_credits": 5},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]

    # Infra picks up match system task
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(infra["api_key"]))
    assert resp.status_code == 200
    assert "Match agents for:" in resp.json()["need"]
    sys_id = resp.json()["task_id"]

    # Deliver match ranking itself
    match = json.dumps({"ranked_agents": [infra["agent_id"]]})
    resp = await client.post(
        f"/v1/tasks/{sys_id}/deliver",
        json={"result": match},
        headers=auth_header(infra["api_key"]),
    )
    assert resp.status_code == 200

    # Infra tries to pick up the task — should NOT get the conflicted task
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(infra["api_key"]))
    if resp.status_code == 200:
        assert resp.json()["task_id"] != task_id, "Conflict rule violated!"
    else:
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# System tasks only visible to infra agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regular_agent_never_sees_system_tasks(client, db):
    """Non-infra agents should never pick up system tasks."""
    await _reg(client, "infra", good_at="matching", accepts_system_tasks=True)
    poster = await _reg(client, "poster")
    regular = await _reg(client, "regular-worker")

    resp = await client.post(
        "/v1/tasks",
        json={"need": "Task for regular", "max_credits": 5},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201

    # Regular worker picks up the task, not the system task
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(regular["api_key"]))
    assert resp.status_code == 200
    assert "Match agents for:" not in resp.json()["need"]
    assert resp.json()["need"] == "Task for regular"


# ---------------------------------------------------------------------------
# Verification: failed -> task stays delivered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verification_failed_leaves_task_delivered(client, db):
    """Failed verification flags but doesn't reject — poster decides."""
    infra = await _reg(client, "infra", good_at="matching", accepts_system_tasks=True)
    worker = await _reg(client, "worker", good_at="translation")
    poster = await _reg(client, "poster")

    # Create, match, pickup, deliver
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Verify fail test", "max_credits": 10},
        headers=auth_header(poster["api_key"]),
    )
    task_id = resp.json()["task_id"]

    # Process match system task
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(infra["api_key"]))
    sys_id = resp.json()["task_id"]
    match = json.dumps({"ranked_agents": [worker["agent_id"]]})
    await client.post(
        f"/v1/tasks/{sys_id}/deliver", json={"result": match}, headers=auth_header(infra["api_key"])
    )

    # Worker picks up and delivers
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(worker["api_key"]))
    assert resp.json()["task_id"] == task_id
    await client.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "Bad work"},
        headers=auth_header(worker["api_key"]),
    )

    # Infra picks up verification, delivers FAIL
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(infra["api_key"]))
    assert "Verify completion" in resp.json()["need"]
    fail_result = json.dumps({"meets_requirements": False, "explanation": "Quality too low"})
    await client.post(
        f"/v1/tasks/{resp.json()['task_id']}/deliver",
        json={"result": fail_result},
        headers=auth_header(infra["api_key"]),
    )

    # Task should still be delivered (not auto-approved, not rejected)
    async with db() as session:
        task = await session.get(Task, task_id)
        status = task.status.value if isinstance(task.status, TaskStatus) else task.status
        assert status == "delivered"
        assert task.verification_status == "failed"
        vr = json.loads(task.verification_result)
        assert vr["meets_requirements"] is False


# ---------------------------------------------------------------------------
# Poster can override verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poster_approves_before_verification(client, db):
    """Poster can approve immediately without waiting for verification."""
    await _reg(client, "infra", good_at="matching", accepts_system_tasks=True)
    worker = await _reg(client, "worker", good_at="translation")
    poster = await _reg(client, "poster")

    # Create task
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Approve early", "max_credits": 10},
        headers=auth_header(poster["api_key"]),
    )
    task_id = resp.json()["task_id"]

    # Worker picks up (pending task, since match hasn't happened yet)
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(worker["api_key"]))
    assert resp.json()["task_id"] == task_id

    # Worker delivers
    await client.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "Done"},
        headers=auth_header(worker["api_key"]),
    )

    # Poster approves immediately
    resp = await client.post(f"/v1/tasks/{task_id}/approve", headers=auth_header(poster["api_key"]))
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_poster_rejects_despite_verification_pass(client, db):
    """Poster can reject even after verification says it passed."""
    await _reg(client, "infra", good_at="matching", accepts_system_tasks=True)
    worker = await _reg(client, "worker", good_at="translation")
    poster = await _reg(client, "poster")

    resp = await client.post(
        "/v1/tasks",
        json={"need": "Reject override", "max_credits": 10},
        headers=auth_header(poster["api_key"]),
    )
    task_id = resp.json()["task_id"]

    # Worker picks up and delivers
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(worker["api_key"]))
    await client.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "Done"},
        headers=auth_header(worker["api_key"]),
    )

    # Manually set verification to passed without auto-approve
    async with db() as session:
        task = await session.get(Task, task_id)
        task.verification_status = "passed"
        task.verification_result = json.dumps(
            {"meets_requirements": True, "explanation": "Looks good"}
        )
        session.add(task)
        await session.commit()

    # Poster rejects anyway
    resp = await client.post(f"/v1/tasks/{task_id}/reject", headers=auth_header(poster["api_key"]))
    assert resp.status_code == 200
    assert resp.json()["status"] == "posted"


# ---------------------------------------------------------------------------
# Match expiry background loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_expiry_falls_back_to_broadcast(client, db):
    """When match deadline passes, expire_matching sets broadcast."""
    from datetime import datetime, timedelta

    from pinchwork.background import expire_matching

    await _reg(client, "infra", good_at="matching", accepts_system_tasks=True)
    poster = await _reg(client, "poster")

    resp = await client.post(
        "/v1/tasks",
        json={"need": "Expiry test", "max_credits": 5},
        headers=auth_header(poster["api_key"]),
    )
    task_id = resp.json()["task_id"]

    # Set match_deadline to the past
    async with db() as session:
        task = await session.get(Task, task_id)
        task.match_deadline = datetime.now(UTC) - timedelta(seconds=10)
        session.add(task)
        await session.commit()

    # Run background loop
    async with db() as session:
        count = await expire_matching(session)
        assert count == 1

    # Verify task is now broadcast
    async with db() as session:
        task = await session.get(Task, task_id)
        assert task.match_status == "broadcast"


# ---------------------------------------------------------------------------
# System task auto-approval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_task_auto_approved_on_delivery(client, db):
    """System tasks are auto-approved immediately when delivered."""
    infra = await _reg(client, "infra", good_at="matching", accepts_system_tasks=True)
    poster = await _reg(client, "poster")

    resp = await client.post(
        "/v1/tasks",
        json={"need": "Auto-approve test", "max_credits": 5},
        headers=auth_header(poster["api_key"]),
    )

    # Infra picks up and delivers system task
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(infra["api_key"]))
    sys_id = resp.json()["task_id"]
    await client.post(
        f"/v1/tasks/{sys_id}/deliver",
        json={"result": json.dumps({"ranked_agents": []})},
        headers=auth_header(infra["api_key"]),
    )

    # System task should be auto-approved
    async with db() as session:
        task = await session.get(Task, sys_id)
        status = task.status.value if isinstance(task.status, TaskStatus) else task.status
        assert status == "approved"
