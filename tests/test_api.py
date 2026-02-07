import pytest


def hdr(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


@pytest.mark.asyncio
async def test_register(client):
    resp = await client.post(
        "/v1/register",
        json={"name": "my-agent"},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "agent_id" in data
    assert data["api_key"].startswith("pwk-")
    assert data["credits"] == 100


@pytest.mark.asyncio
async def test_me(registered_agent):
    client, agent_id, api_key = registered_agent
    resp = await client.get("/v1/me", headers=hdr(api_key))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == agent_id
    assert data["credits"] == 100


@pytest.mark.asyncio
async def test_unauthorized(client):
    resp = await client.get("/v1/me", headers={"Accept": "application/json"})
    assert resp.status_code == 401

    resp = await client.get(
        "/v1/me",
        headers={"Authorization": "Bearer invalid", "Accept": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "seeder" in data  # Seeder status is now included


@pytest.mark.asyncio
async def test_skill_md(client):
    resp = await client.get("/skill.md")
    assert resp.status_code == 200
    assert "pinchwork" in resp.text.lower()


@pytest.mark.asyncio
async def test_agent_public_profile(registered_agent):
    client, agent_id, api_key = registered_agent
    resp = await client.get(f"/v1/agents/{agent_id}", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == agent_id
    # Public profile shouldn't show credits
    assert "credits" not in data


@pytest.mark.asyncio
async def test_agent_not_found(client):
    resp = await client.get("/v1/agents/ag_nonexistent", headers={"Accept": "application/json"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_openapi_spec_available(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "paths" in data
    assert "/v1/tasks" in data["paths"]


@pytest.mark.asyncio
async def test_docs_available(client):
    resp = await client.get("/docs")
    assert resp.status_code == 200
    assert "swagger" in resp.text.lower() or "openapi" in resp.text.lower()


# --- Step 1: Root redirect ---


@pytest.mark.asyncio
async def test_root_redirects_to_skill_md(client):
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/skill.md"


# --- Step 2: OpenAPI schema has populated schemas ---


@pytest.mark.asyncio
async def test_openapi_schemas_populated(client):
    resp = await client.get("/openapi.json")
    data = resp.json()
    schemas = data.get("components", {}).get("schemas", {})
    # Verify key models exist in the schema
    assert "TaskResponse" in schemas
    assert "TaskPickupResponse" in schemas
    assert "ErrorResponse" in schemas
    assert "AgentResponse" in schemas
    assert "RegisterResponse" in schemas
    assert "CreditBalanceResponse" in schemas
    assert "MyTasksResponse" in schemas
    # Verify they have properties (not empty)
    assert schemas["TaskResponse"].get("properties")
    assert schemas["ErrorResponse"].get("properties")


# --- Step 3: Error responses use {"error": ...} ---


@pytest.mark.asyncio
async def test_error_response_format(client):
    """HTTPException errors should return {"error": "..."} not {"detail": "..."}."""
    resp = await client.get(
        "/v1/me",
        headers={"Authorization": "Bearer invalid", "Accept": "application/json"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert "error" in data
    assert "detail" not in data


# --- Step 4: Validation ---


@pytest.mark.asyncio
async def test_tag_validation_too_many(registered_agent):
    client, agent_id, api_key = registered_agent
    tags = [f"tag{i}" for i in range(11)]
    resp = await client.post(
        "/v1/tasks",
        json={"need": "test", "max_credits": 10, "tags": tags},
        headers=hdr(api_key),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_tag_validation_invalid_chars(registered_agent):
    client, agent_id, api_key = registered_agent
    resp = await client.post(
        "/v1/tasks",
        json={"need": "test", "max_credits": 10, "tags": ['bad"tag']},
        headers=hdr(api_key),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_tag_validation_too_long(registered_agent):
    client, agent_id, api_key = registered_agent
    resp = await client.post(
        "/v1/tasks",
        json={"need": "test", "max_credits": 10, "tags": ["a" * 51]},
        headers=hdr(api_key),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_tag_validation_valid(registered_agent):
    client, agent_id, api_key = registered_agent
    resp = await client.post(
        "/v1/tasks",
        json={"need": "test", "max_credits": 10, "tags": ["python", "data-science", "ml_ops"]},
        headers=hdr(api_key),
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_need_max_length(registered_agent):
    client, agent_id, api_key = registered_agent
    resp = await client.post(
        "/v1/tasks",
        json={"need": "x" * 50_001, "max_credits": 10},
        headers=hdr(api_key),
    )
    assert resp.status_code == 400


# --- Step 5: Security ---


@pytest.mark.asyncio
async def test_malformed_credits_claimed(two_agents):
    """Non-integer credits_claimed should return 400, not 500."""
    c = two_agents["client"]
    poster, worker = two_agents["poster"], two_agents["worker"]

    resp = await c.post(
        "/v1/tasks",
        json={"need": "test task", "max_credits": 10},
        headers=hdr(poster["key"]),
    )
    task_id = resp.json()["task_id"]

    await c.post("/v1/tasks/pickup", headers=hdr(worker["key"]))

    resp = await c.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "done", "credits_claimed": "not-a-number"},
        headers=hdr(worker["key"]),
    )
    assert resp.status_code == 400
    assert "integer" in resp.json()["error"].lower()


@pytest.mark.asyncio
async def test_malformed_rating(two_agents):
    """Non-integer rating should return 400, not 500."""
    c = two_agents["client"]
    poster, worker = two_agents["poster"], two_agents["worker"]

    resp = await c.post(
        "/v1/tasks",
        json={"need": "test task", "max_credits": 10},
        headers=hdr(poster["key"]),
    )
    task_id = resp.json()["task_id"]

    await c.post("/v1/tasks/pickup", headers=hdr(worker["key"]))
    await c.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "done"},
        headers=hdr(worker["key"]),
    )

    resp = await c.post(
        f"/v1/tasks/{task_id}/approve",
        json={"rating": "bad"},
        headers=hdr(poster["key"]),
    )
    assert resp.status_code == 400
    assert "integer" in resp.json()["error"].lower()


# --- Step 6: /v1/tasks/mine ---


@pytest.mark.asyncio
async def test_my_tasks_as_poster(two_agents):
    c = two_agents["client"]
    poster = two_agents["poster"]

    await c.post(
        "/v1/tasks",
        json={"need": "my task 1", "max_credits": 10},
        headers=hdr(poster["key"]),
    )
    await c.post(
        "/v1/tasks",
        json={"need": "my task 2", "max_credits": 10},
        headers=hdr(poster["key"]),
    )

    resp = await c.get(
        "/v1/tasks/mine?role=poster",
        headers=hdr(poster["key"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["tasks"]) == 2


@pytest.mark.asyncio
async def test_my_tasks_as_worker(two_agents):
    c = two_agents["client"]
    poster, worker = two_agents["poster"], two_agents["worker"]

    await c.post(
        "/v1/tasks",
        json={"need": "work task", "max_credits": 10},
        headers=hdr(poster["key"]),
    )
    await c.post("/v1/tasks/pickup", headers=hdr(worker["key"]))

    resp = await c.get(
        "/v1/tasks/mine?role=worker",
        headers=hdr(worker["key"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["tasks"][0]["need"] == "work task"


@pytest.mark.asyncio
async def test_my_tasks_filter_by_status(two_agents):
    c = two_agents["client"]
    poster = two_agents["poster"]

    await c.post(
        "/v1/tasks",
        json={"need": "posted task", "max_credits": 10},
        headers=hdr(poster["key"]),
    )

    resp = await c.get(
        "/v1/tasks/mine?status=posted",
        headers=hdr(poster["key"]),
    )
    data = resp.json()
    assert data["total"] >= 1
    assert all(t["status"] == "posted" for t in data["tasks"])


@pytest.mark.asyncio
async def test_my_tasks_empty(registered_agent):
    client, agent_id, api_key = registered_agent
    resp = await client.get("/v1/tasks/mine", headers=hdr(api_key))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["tasks"] == []


@pytest.mark.asyncio
async def test_my_tasks_not_routed_as_task_id(registered_agent):
    """Ensure /v1/tasks/mine is not treated as /v1/tasks/{task_id}."""
    client, agent_id, api_key = registered_agent
    resp = await client.get("/v1/tasks/mine", headers=hdr(api_key))
    # Should be 200, not 404 (which would happen if "mine" was treated as a task_id)
    assert resp.status_code == 200
