"""Tests for time-based state transitions: claim timeout, review timeout,
verification timeout, and max rejections."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from pinchwork.background import (
    auto_approve_tasks,
    expire_claim_timeout,
    expire_verification,
)
from pinchwork.config import settings
from pinchwork.db_models import (
    MatchStatus,
    SystemTaskType,
    Task,
    TaskStatus,
    VerificationStatus,
)
from tests.conftest import auth_header

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_and_pickup(client, poster_key, worker_key, **create_kwargs):
    """Create a task, pick it up, return (task_id, task)."""
    body = {"need": "do something", "max_credits": 10, **create_kwargs}
    resp = await client.post("/v1/tasks", json=body, headers=auth_header(poster_key))
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]

    resp = await client.post(f"/v1/tasks/{task_id}/pickup", headers=auth_header(worker_key))
    assert resp.status_code == 200
    return task_id, resp.json()


# ---------------------------------------------------------------------------
# Per-task review timeout / auto-approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_approve_uses_per_task_review_timeout(client, db, two_agents):
    """Per-task review_timeout_minutes is used for auto-approve instead of global."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    # Create task with 1-minute review timeout
    task_id, _ = await _create_and_pickup(c, poster["key"], worker["key"], review_timeout_minutes=1)

    # Deliver
    resp = await c.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "done"},
        headers=auth_header(worker["key"]),
    )
    assert resp.status_code == 200

    # Set delivered_at to 2 minutes ago
    async with db() as session:
        task = await session.get(Task, task_id)
        task.delivered_at = datetime.now(UTC) - timedelta(minutes=2)
        session.add(task)
        await session.commit()

    # Run auto-approve — should approve since 2min > 1min timeout
    async with db() as session:
        count = await auto_approve_tasks(session)
    assert count == 1

    # Verify approved
    resp = await c.get(f"/v1/tasks/{task_id}", headers=auth_header(poster["key"]))
    assert resp.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_auto_approve_falls_back_to_default(client, db, two_agents):
    """Tasks without review_timeout_minutes use default_review_timeout_minutes."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    task_id, _ = await _create_and_pickup(c, poster["key"], worker["key"])

    # Deliver
    resp = await c.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "done"},
        headers=auth_header(worker["key"]),
    )
    assert resp.status_code == 200

    # Set delivered_at to 5 minutes ago — should NOT auto-approve (default is 30min)
    async with db() as session:
        task = await session.get(Task, task_id)
        task.delivered_at = datetime.now(UTC) - timedelta(minutes=5)
        session.add(task)
        await session.commit()

    async with db() as session:
        count = await auto_approve_tasks(session)
    assert count == 0

    # Now set to 31 minutes ago — should auto-approve
    async with db() as session:
        task = await session.get(Task, task_id)
        task.delivered_at = datetime.now(UTC) - timedelta(minutes=31)
        session.add(task)
        await session.commit()

    async with db() as session:
        count = await auto_approve_tasks(session)
    assert count == 1


# ---------------------------------------------------------------------------
# Claim deadline / timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_deadline_set_on_pickup(client, db, two_agents):
    """claim_deadline is set when a task is picked up."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    task_id, pickup = await _create_and_pickup(c, poster["key"], worker["key"])

    assert pickup.get("claim_deadline") is not None

    async with db() as session:
        task = await session.get(Task, task_id)
        assert task.claim_deadline is not None


@pytest.mark.asyncio
async def test_claim_deadline_uses_per_task_timeout(client, db, two_agents):
    """Per-task claim_timeout_minutes overrides default."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    task_id, _ = await _create_and_pickup(c, poster["key"], worker["key"], claim_timeout_minutes=60)

    async with db() as session:
        task = await session.get(Task, task_id)
        # claim_deadline should be ~60 min from now, not 10
        delta = task.claim_deadline.replace(tzinfo=UTC) - datetime.now(UTC)
        assert delta > timedelta(minutes=55)


@pytest.mark.asyncio
async def test_claim_timeout_resets_to_posted(client, db, two_agents):
    """Claimed tasks past claim_deadline are reset to posted."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    task_id, _ = await _create_and_pickup(c, poster["key"], worker["key"])

    # Set claim_deadline to the past
    async with db() as session:
        task = await session.get(Task, task_id)
        task.claim_deadline = datetime.now(UTC) - timedelta(minutes=1)
        session.add(task)
        await session.commit()

    # Run background expire
    async with db() as session:
        count = await expire_claim_timeout(session)
    assert count == 1

    # Verify task is posted again
    resp = await c.get(f"/v1/tasks/{task_id}", headers=auth_header(poster["key"]))
    data = resp.json()
    assert data["status"] == "posted"
    assert data.get("worker_id") is None


@pytest.mark.asyncio
async def test_claim_timeout_skips_system_tasks(client, db, two_agents):
    """System tasks are not affected by claim timeout."""
    async with db() as session:
        # Create a fake system task that's claimed with expired deadline
        task = Task(
            id="tk-sys-test",
            poster_id=settings.platform_agent_id,
            worker_id=two_agents["worker"]["id"],
            need="system test",
            max_credits=5,
            status=TaskStatus.claimed,
            is_system=True,
            system_task_type=SystemTaskType.match_agents,
            claim_deadline=datetime.now(UTC) - timedelta(minutes=1),
            claimed_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        session.add(task)
        await session.commit()

    async with db() as session:
        count = await expire_claim_timeout(session)
    assert count == 0  # system tasks skipped


@pytest.mark.asyncio
async def test_claim_timeout_skips_active_rejection_grace(client, db, two_agents):
    """Claim timeout doesn't fire while rejection grace period is active."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    task_id, _ = await _create_and_pickup(c, poster["key"], worker["key"])

    # Deliver and reject
    resp = await c.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "done"},
        headers=auth_header(worker["key"]),
    )
    assert resp.status_code == 200

    resp = await c.post(
        f"/v1/tasks/{task_id}/reject",
        json={"reason": "bad"},
        headers=auth_header(poster["key"]),
    )
    assert resp.status_code == 200

    # Set claim_deadline to past but rejection_grace_deadline is in the future
    async with db() as session:
        task = await session.get(Task, task_id)
        task.claim_deadline = datetime.now(UTC) - timedelta(minutes=1)
        task.rejection_grace_deadline = datetime.now(UTC) + timedelta(minutes=5)
        session.add(task)
        await session.commit()

    async with db() as session:
        count = await expire_claim_timeout(session)
    assert count == 0  # grace period protects from claim timeout


# ---------------------------------------------------------------------------
# Verification timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verification_deadline_set_on_delivery(client, db):
    """verification_deadline is set when verification is spawned."""
    import json as json_mod

    # Register agents via HTTP API
    resp = await client.post(
        "/v1/register",
        json={"name": "poster-vfy"},
        headers={"Accept": "application/json"},
    )
    poster = resp.json()

    resp = await client.post(
        "/v1/register",
        json={"name": "worker-vfy"},
        headers={"Accept": "application/json"},
    )
    worker = resp.json()

    resp = await client.post(
        "/v1/register",
        json={"name": "infra-vfy", "accepts_system_tasks": True},
        headers={"Accept": "application/json"},
    )
    infra = resp.json()

    poster_key = poster["api_key"]
    worker_key = worker["api_key"]
    infra_key = infra["api_key"]

    # Create task
    resp = await client.post(
        "/v1/tasks",
        json={"need": "test verification deadline", "max_credits": 10},
        headers=auth_header(poster_key),
    )
    task_id = resp.json()["task_id"]

    # Process system tasks (matching + capability extraction)
    for _ in range(5):
        resp = await client.post("/v1/tasks/pickup", headers=auth_header(infra_key))
        if resp.status_code == 204:
            break
        picked = resp.json()
        need = picked["need"]
        if "Match agents" in need:
            result = json_mod.dumps({"ranked_agents": [worker["agent_id"]]})
        elif "Extract capability" in need:
            result = json_mod.dumps({"agent_id": "x", "tags": []})
        else:
            result = "{}"
        await client.post(
            f"/v1/tasks/{picked['task_id']}/deliver",
            json={"result": result},
            headers=auth_header(infra_key),
        )

    # Pickup the real task
    resp = await client.post(f"/v1/tasks/{task_id}/pickup", headers=auth_header(worker_key))
    assert resp.status_code == 200

    # Deliver
    resp = await client.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "done"},
        headers=auth_header(worker_key),
    )
    assert resp.status_code == 200

    # Check verification_deadline is set
    async with db() as session:
        task = await session.get(Task, task_id)
        assert task.verification_deadline is not None
        assert task.verification_status == VerificationStatus.pending


@pytest.mark.asyncio
async def test_verification_timeout_clears_status(client, db, two_agents):
    """Verification timeout clears verification_status and cancels system task."""
    async with db() as session:
        # Create a delivered task with expired verification deadline
        task = Task(
            id="tk-vfy-test",
            poster_id=two_agents["poster"]["id"],
            worker_id=two_agents["worker"]["id"],
            need="test",
            max_credits=10,
            status=TaskStatus.delivered,
            verification_status=VerificationStatus.pending,
            verification_deadline=datetime.now(UTC) - timedelta(seconds=10),
            delivered_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        sys_task = Task(
            id="tk-vfy-sys",
            poster_id=settings.platform_agent_id,
            need="verify",
            max_credits=5,
            status=TaskStatus.posted,
            is_system=True,
            system_task_type=SystemTaskType.verify_completion,
            parent_task_id="tk-vfy-test",
        )
        session.add(task)
        session.add(sys_task)
        await session.commit()

    async with db() as session:
        count = await expire_verification(session)
    assert count == 1

    async with db() as session:
        task = await session.get(Task, "tk-vfy-test")
        assert task.verification_status is None
        assert task.verification_deadline is None

        sys_task = await session.get(Task, "tk-vfy-sys")
        assert sys_task.status == TaskStatus.cancelled


# ---------------------------------------------------------------------------
# Max rejections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_rejections_releases_worker(client, db, two_agents):
    """After max_rejections, worker is released and task resets to posted."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    task_id, _ = await _create_and_pickup(c, poster["key"], worker["key"])

    with patch.object(settings, "max_rejections", 2):
        # Rejection 1
        await c.post(
            f"/v1/tasks/{task_id}/deliver",
            json={"result": "attempt 1"},
            headers=auth_header(worker["key"]),
        )
        resp = await c.post(
            f"/v1/tasks/{task_id}/reject",
            json={"reason": "nope"},
            headers=auth_header(poster["key"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "claimed"  # still claimed after 1st rejection

        # Re-deliver for rejection 2
        await c.post(
            f"/v1/tasks/{task_id}/deliver",
            json={"result": "attempt 2"},
            headers=auth_header(worker["key"]),
        )
        resp = await c.post(
            f"/v1/tasks/{task_id}/reject",
            json={"reason": "still nope"},
            headers=auth_header(poster["key"]),
        )
        assert resp.status_code == 200
        data = resp.json()
        # 2nd rejection = max_rejections, should reset to posted
        assert data["status"] == "posted"
        assert data.get("worker_id") is None

    # Verify DB state
    async with db() as session:
        task = await session.get(Task, task_id)
        assert task.status == TaskStatus.posted
        assert task.worker_id is None
        assert task.match_status == MatchStatus.broadcast


@pytest.mark.asyncio
async def test_below_max_rejections_keeps_worker(client, db, two_agents):
    """Below max_rejections, worker stays assigned with grace period."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    task_id, _ = await _create_and_pickup(c, poster["key"], worker["key"])

    # Deliver and reject once (max is 3 by default)
    await c.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "attempt 1"},
        headers=auth_header(worker["key"]),
    )
    resp = await c.post(
        f"/v1/tasks/{task_id}/reject",
        json={"reason": "not good enough"},
        headers=auth_header(poster["key"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "claimed"
    assert data["worker_id"] == worker["id"]
    assert data.get("rejection_grace_deadline") is not None


# ---------------------------------------------------------------------------
# claim_deadline cleanup on delivery / abandon
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_deadline_cleared_on_delivery(client, db, two_agents):
    """claim_deadline should be nulled when worker delivers."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    task_id, _ = await _create_and_pickup(c, poster["key"], worker["key"])

    # Verify claim_deadline is set
    async with db() as session:
        task = await session.get(Task, task_id)
        assert task.claim_deadline is not None

    # Deliver
    resp = await c.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "done"},
        headers=auth_header(worker["key"]),
    )
    assert resp.status_code == 200

    # claim_deadline should be cleared
    async with db() as session:
        task = await session.get(Task, task_id)
        assert task.claim_deadline is None


@pytest.mark.asyncio
async def test_claim_deadline_cleared_on_abandon(client, db, two_agents):
    """claim_deadline should be nulled when worker abandons."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    task_id, _ = await _create_and_pickup(c, poster["key"], worker["key"])

    # Abandon
    resp = await c.post(
        f"/v1/tasks/{task_id}/abandon",
        headers=auth_header(worker["key"]),
    )
    assert resp.status_code == 200

    # claim_deadline should be cleared
    async with db() as session:
        task = await session.get(Task, task_id)
        assert task.claim_deadline is None
        assert task.status == TaskStatus.posted


@pytest.mark.asyncio
async def test_reclaim_after_timeout_gets_fresh_deadline(client, db, two_agents):
    """After claim timeout resets a task, a new pickup gets a fresh claim_deadline."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    task_id, _ = await _create_and_pickup(c, poster["key"], worker["key"])

    # Force claim timeout
    async with db() as session:
        task = await session.get(Task, task_id)
        task.claim_deadline = datetime.now(UTC) - timedelta(minutes=1)
        session.add(task)
        await session.commit()

    async with db() as session:
        count = await expire_claim_timeout(session)
    assert count == 1

    # Register a new worker to pick it up
    from tests.conftest import register_agent

    new_worker = await register_agent(c, "worker2")

    resp = await c.post(
        f"/v1/tasks/{task_id}/pickup",
        headers=auth_header(new_worker["api_key"]),
    )
    assert resp.status_code == 200
    pickup = resp.json()
    assert pickup.get("claim_deadline") is not None

    # Verify it's a fresh deadline (in the future)
    async with db() as session:
        task = await session.get(Task, task_id)
        dl = task.claim_deadline
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=UTC)
        assert dl > datetime.now(UTC)


# ---------------------------------------------------------------------------
# get_task returns new fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_returns_new_fields(client, db, two_agents):
    """GET /v1/tasks/{id} includes claim_deadline and review_timeout_minutes."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    task_id, _ = await _create_and_pickup(
        c, poster["key"], worker["key"], review_timeout_minutes=60
    )

    resp = await c.get(f"/v1/tasks/{task_id}", headers=auth_header(poster["key"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("claim_deadline") is not None
    assert data.get("review_timeout_minutes") == 60


@pytest.mark.asyncio
async def test_list_my_tasks_returns_new_fields(client, db, two_agents):
    """GET /v1/me/tasks includes claim_deadline, review/claim_timeout_minutes."""
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    task_id, _ = await _create_and_pickup(
        c,
        poster["key"],
        worker["key"],
        review_timeout_minutes=60,
        claim_timeout_minutes=20,
    )

    # Worker sees it in their tasks
    resp = await c.get("/v1/tasks/mine", headers=auth_header(worker["key"]))
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    task = next(t for t in tasks if t["task_id"] == task_id)
    assert task.get("claim_deadline") is not None
    assert task.get("review_timeout_minutes") == 60
    assert task.get("claim_timeout_minutes") == 20


# ---------------------------------------------------------------------------
# Validation bounds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_timeout_validation_bounds(client, db, two_agents):
    """review_timeout_minutes rejects values outside 1-1440."""
    c = two_agents["client"]
    poster = two_agents["poster"]

    # Too low
    resp = await c.post(
        "/v1/tasks",
        json={"need": "test", "max_credits": 10, "review_timeout_minutes": 0},
        headers=auth_header(poster["key"]),
    )
    assert resp.status_code == 400

    # Too high
    resp = await c.post(
        "/v1/tasks",
        json={"need": "test", "max_credits": 10, "review_timeout_minutes": 1441},
        headers=auth_header(poster["key"]),
    )
    assert resp.status_code == 400

    # Valid
    resp = await c.post(
        "/v1/tasks",
        json={"need": "test", "max_credits": 10, "review_timeout_minutes": 60},
        headers=auth_header(poster["key"]),
    )
    assert resp.status_code == 201
