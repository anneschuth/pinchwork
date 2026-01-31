import pytest


def hdr(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def jhdr(key: str) -> dict:
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
async def test_full_cycle_json(two_agents):
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    # Delegate
    resp = await c.post(
        "/v1/tasks",
        headers=jhdr(poster["key"]),
        json={"need": "Translate 'hello' to Dutch", "max_credits": 10},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "posted"
    task_id = data["task_id"]

    # Check poster credits decreased
    resp = await c.get("/v1/me", headers=hdr(poster["key"]))
    assert resp.json()["credits"] == 90  # 100 - 10 escrowed

    # Pickup
    resp = await c.post("/v1/tasks/pickup", headers=hdr(worker["key"]))
    assert resp.status_code == 200
    picked = resp.json()
    assert picked["task_id"] == task_id

    # Deliver (credits_claimed defaults to max_credits=10)
    resp = await c.post(
        f"/v1/tasks/{task_id}/deliver",
        headers=jhdr(worker["key"]),
        json={"result": "Hallo"},
    )
    assert resp.status_code == 200
    delivered = resp.json()
    assert delivered["status"] == "delivered"

    # Poll
    resp = await c.get(f"/v1/tasks/{task_id}", headers=hdr(poster["key"]))
    assert resp.status_code == 200
    assert resp.json()["status"] == "delivered"

    # Approve
    resp = await c.post(f"/v1/tasks/{task_id}/approve", headers=hdr(poster["key"]))
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    # Check worker earned credits
    resp = await c.get("/v1/me", headers=hdr(worker["key"]))
    assert resp.json()["credits"] == 110  # 100 + 10 earned


@pytest.mark.asyncio
async def test_full_cycle_markdown(two_agents):
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    # Delegate with markdown
    md_body = "---\nmax_credits: 5\n---\nTranslate 'goodbye' to Dutch"
    resp = await c.post(
        "/v1/tasks",
        headers={**hdr(poster["key"])},
        content=md_body.encode(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "posted"
    task_id = data["task_id"]

    # Pickup
    resp = await c.post("/v1/tasks/pickup", headers=hdr(worker["key"]))
    assert resp.status_code == 200

    # Deliver with plain text
    resp = await c.post(
        f"/v1/tasks/{task_id}/deliver",
        headers=hdr(worker["key"]),
        content=b"Tot ziens",
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_reject_resets_to_posted(two_agents):
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    # Delegate
    resp = await c.post(
        "/v1/tasks",
        headers=jhdr(poster["key"]),
        json={"need": "Do something", "max_credits": 15},
    )
    task_id = resp.json()["task_id"]

    # Pickup + deliver
    await c.post("/v1/tasks/pickup", headers=hdr(worker["key"]))
    await c.post(
        f"/v1/tasks/{task_id}/deliver",
        headers=jhdr(worker["key"]),
        json={"result": "Bad result"},
    )

    # Reject
    resp = await c.post(f"/v1/tasks/{task_id}/reject", headers=hdr(poster["key"]))
    assert resp.status_code == 200
    assert resp.json()["status"] == "posted"  # Reset for re-claim


@pytest.mark.asyncio
async def test_no_tasks_available(registered_agent):
    client, _, api_key = registered_agent
    resp = await client.post("/v1/tasks/pickup", headers=hdr(api_key))
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_cant_pickup_own_task(registered_agent):
    client, _, api_key = registered_agent
    # Post a task
    resp = await client.post(
        "/v1/tasks",
        headers=jhdr(api_key),
        json={"need": "Self task", "max_credits": 5},
    )
    assert resp.status_code == 201

    # Try to pick up own task
    resp = await client.post("/v1/tasks/pickup", headers=hdr(api_key))
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_insufficient_credits(registered_agent):
    client, _, api_key = registered_agent
    resp = await client.post(
        "/v1/tasks",
        headers=jhdr(api_key),
        json={"need": "Expensive task", "max_credits": 999},
    )
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_wrong_worker_cant_deliver(two_agents):
    c = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    # Register a third agent
    resp = await c.post(
        "/v1/register", json={"name": "intruder"}, headers={"Accept": "application/json"}
    )
    intruder_key = resp.json()["api_key"]

    # Post and pickup
    resp = await c.post(
        "/v1/tasks",
        headers=jhdr(poster["key"]),
        json={"need": "Secret task", "max_credits": 5},
    )
    task_id = resp.json()["task_id"]
    await c.post("/v1/tasks/pickup", headers=hdr(worker["key"]))

    # Intruder tries to deliver
    resp = await c.post(
        f"/v1/tasks/{task_id}/deliver",
        headers=jhdr(intruder_key),
        json={"result": "Hacked"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_task_visibility(two_agents):
    c = two_agents["client"]
    poster = two_agents["poster"]

    # Register third agent
    resp = await c.post(
        "/v1/register", json={"name": "outsider"}, headers={"Accept": "application/json"}
    )
    outsider_key = resp.json()["api_key"]

    # Post task
    resp = await c.post(
        "/v1/tasks",
        headers=jhdr(poster["key"]),
        json={"need": "Private task", "max_credits": 5},
    )
    task_id = resp.json()["task_id"]

    # Outsider can't see it
    resp = await c.get(f"/v1/tasks/{task_id}", headers=hdr(outsider_key))
    assert resp.status_code == 403
