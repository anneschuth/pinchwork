"""Tests for the verify_completion system via system tasks."""

from __future__ import annotations

import json

import pytest
from sqlmodel import select

from pinchwork.db_models import Task, TaskStatus
from tests.conftest import auth_header, register_agent


async def _register_infra_agent(client, name="infra"):
    data = await register_agent(client, name)
    resp = await client.patch(
        "/v1/me",
        json={"accepts_system_tasks": True, "good_at": "verification"},
        headers=auth_header(data["api_key"]),
    )
    assert resp.status_code == 200
    return data


async def _create_and_deliver_task(client, poster, worker, need="Test task", max_credits=20):
    """Helper: create task, worker picks up and delivers."""
    # Create
    resp = await client.post(
        "/v1/tasks",
        json={"need": need, "max_credits": max_credits},
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]

    # Worker picks up
    resp = await client.post(
        "/v1/tasks/pickup",
        headers=auth_header(worker["api_key"]),
    )
    assert resp.status_code == 200
    picked_id = resp.json()["task_id"]
    assert picked_id == task_id

    # Worker delivers
    resp = await client.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "Here is the completed work."},
        headers=auth_header(worker["api_key"]),
    )
    assert resp.status_code == 200

    return task_id


@pytest.mark.asyncio
async def test_verification_spawned_on_deliver(client, db):
    """When a regular task is delivered and infra agents exist, a verify task is created."""
    poster = await register_agent(client, "poster")
    worker = await register_agent(client, "worker")
    infra = await _register_infra_agent(client, "infra")

    await _create_and_deliver_task(client, poster, worker)

    # Infra should be able to pick up verification system task
    # First, pick up the match_agents task that was spawned on create
    resp = await client.post(
        "/v1/tasks/pickup",
        headers=auth_header(infra["api_key"]),
    )
    # This might be the match task or verify task depending on ordering
    assert resp.status_code == 200
    picked = resp.json()

    # Keep picking up until we find verify_completion
    found_verify = "Verify completion" in picked["need"]
    if not found_verify:
        # Deliver the match task first
        match_result = json.dumps({"ranked_agents": [worker["agent_id"]]})
        resp = await client.post(
            f"/v1/tasks/{picked['task_id']}/deliver",
            json={"result": match_result},
            headers=auth_header(infra["api_key"]),
        )
        assert resp.status_code == 200

        # Now pick up the verify task
        resp = await client.post(
            "/v1/tasks/pickup",
            headers=auth_header(infra["api_key"]),
        )
        assert resp.status_code == 200
        picked = resp.json()
        found_verify = "Verify completion" in picked["need"]

    assert found_verify, f"Expected verify_completion task, got: {picked['need']}"


@pytest.mark.asyncio
async def test_verification_passed_auto_approves(client, db):
    """When verification passes, the parent task is auto-approved."""
    poster = await register_agent(client, "poster")
    worker = await register_agent(client, "worker")
    infra = await _register_infra_agent(client, "infra")

    task_id = await _create_and_deliver_task(client, poster, worker)

    # Pick up and deliver all system tasks
    for _ in range(5):  # Max iterations to clear system tasks
        resp = await client.post(
            "/v1/tasks/pickup",
            headers=auth_header(infra["api_key"]),
        )
        if resp.status_code == 204:
            break
        picked = resp.json()
        sys_task_id = picked["task_id"]

        if "Match agents for:" in picked["need"]:
            result = json.dumps({"ranked_agents": [worker["agent_id"]]})
        elif "Verify completion" in picked["need"]:
            result = json.dumps(
                {"meets_requirements": True, "explanation": "Work matches the need"}
            )
        else:
            result = "done"

        resp = await client.post(
            f"/v1/tasks/{sys_task_id}/deliver",
            json={"result": result},
            headers=auth_header(infra["api_key"]),
        )
        assert resp.status_code == 200

    # Check the parent task is auto-approved
    async with db() as session:
        task = await session.get(Task, task_id)
        status = task.status.value if isinstance(task.status, TaskStatus) else task.status
        assert status == "approved", f"Expected approved, got {status}"
        assert task.verification_status == "passed"


@pytest.mark.asyncio
async def test_verification_failed_flags_for_review(client, db):
    """When verification fails, task stays delivered with failed verification status."""
    poster = await register_agent(client, "poster")
    worker = await register_agent(client, "worker")
    infra = await _register_infra_agent(client, "infra")

    task_id = await _create_and_deliver_task(client, poster, worker)

    # Pick up and deliver all system tasks
    for _ in range(5):
        resp = await client.post(
            "/v1/tasks/pickup",
            headers=auth_header(infra["api_key"]),
        )
        if resp.status_code == 204:
            break
        picked = resp.json()
        sys_task_id = picked["task_id"]

        if "Match agents for:" in picked["need"]:
            result = json.dumps({"ranked_agents": [worker["agent_id"]]})
        elif "Verify completion" in picked["need"]:
            result = json.dumps(
                {"meets_requirements": False, "explanation": "Result doesn't match need"}
            )
        else:
            result = "done"

        resp = await client.post(
            f"/v1/tasks/{sys_task_id}/deliver",
            json={"result": result},
            headers=auth_header(infra["api_key"]),
        )
        assert resp.status_code == 200

    # Check the parent task is still delivered with failed verification
    async with db() as session:
        task = await session.get(Task, task_id)
        status = task.status.value if isinstance(task.status, TaskStatus) else task.status
        assert status == "delivered", f"Expected delivered, got {status}"
        assert task.verification_status == "failed"


@pytest.mark.asyncio
async def test_poster_can_approve_before_verification(client, db):
    """Poster can approve the task before verification completes."""
    poster = await register_agent(client, "poster")
    worker = await register_agent(client, "worker")
    await _register_infra_agent(client, "infra")

    task_id = await _create_and_deliver_task(client, poster, worker)

    # Poster approves immediately, before verification
    resp = await client.post(
        f"/v1/tasks/{task_id}/approve",
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_poster_can_reject_despite_verification_pass(client, db):
    """Poster can reject even if verification passed (verification is advisory)."""
    poster = await register_agent(client, "poster")
    worker = await register_agent(client, "worker")
    await _register_infra_agent(client, "infra")

    task_id = await _create_and_deliver_task(client, poster, worker)

    # Manually set verification_status to passed without auto-approve
    async with db() as session:
        task = await session.get(Task, task_id)
        task.verification_status = "passed"
        task.verification_result = json.dumps(
            {"meets_requirements": True, "explanation": "Looks good"}
        )
        # Keep status as delivered so poster can still reject
        session.add(task)
        await session.commit()

    # Poster rejects despite verification passing
    resp = await client.post(
        f"/v1/tasks/{task_id}/reject",
        headers=auth_header(poster["api_key"]),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "posted"


@pytest.mark.asyncio
async def test_no_verification_without_infra_agents(client, db):
    """Without infra agents, no verification task is spawned."""
    poster = await register_agent(client, "poster")
    worker = await register_agent(client, "worker")

    task_id = await _create_and_deliver_task(client, poster, worker)

    # Check no system tasks exist
    async with db() as session:
        result = await session.execute(
            select(Task).where(
                Task.is_system == True,  # noqa: E712
                Task.system_task_type == "verify_completion",
                Task.parent_task_id == task_id,
            )
        )
        sys_tasks = result.scalars().all()
        assert len(sys_tasks) == 0


@pytest.mark.asyncio
async def test_verification_result_stored_on_task(client, db):
    """Verification result is stored on the parent task."""
    poster = await register_agent(client, "poster")
    worker = await register_agent(client, "worker")
    infra = await _register_infra_agent(client, "infra")

    task_id = await _create_and_deliver_task(client, poster, worker)

    # Process all system tasks
    for _ in range(5):
        resp = await client.post(
            "/v1/tasks/pickup",
            headers=auth_header(infra["api_key"]),
        )
        if resp.status_code == 204:
            break
        picked = resp.json()
        sys_task_id = picked["task_id"]

        if "Match agents for:" in picked["need"]:
            result = json.dumps({"ranked_agents": [worker["agent_id"]]})
        elif "Verify completion" in picked["need"]:
            result = json.dumps({"meets_requirements": True, "explanation": "Excellent work"})
        else:
            result = "done"

        resp = await client.post(
            f"/v1/tasks/{sys_task_id}/deliver",
            json={"result": result},
            headers=auth_header(infra["api_key"]),
        )
        assert resp.status_code == 200

    # Check verification result is stored
    async with db() as session:
        task = await session.get(Task, task_id)
        assert task.verification_result is not None
        vr = json.loads(task.verification_result)
        assert vr["meets_requirements"] is True
        assert "Excellent work" in vr["explanation"]
