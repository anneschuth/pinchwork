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
    assert data["api_key"].startswith("pk_")
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
    assert resp.json() == {"status": "ok"}


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
