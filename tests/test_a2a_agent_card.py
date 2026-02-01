"""Tests for the A2A Agent Card endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from pinchwork.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_agent_card_returns_json(client):
    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_agent_card_has_required_fields(client):
    resp = await client.get("/.well-known/agent.json")
    card = resp.json()

    # Required A2A Agent Card fields
    assert card["name"] == "Pinchwork"
    assert "description" in card
    assert card["url"] == "https://pinchwork.dev"
    assert "version" in card
    assert "provider" in card
    assert "capabilities" in card
    assert "skills" in card


@pytest.mark.asyncio
async def test_agent_card_has_skills(client):
    resp = await client.get("/.well-known/agent.json")
    card = resp.json()

    skill_ids = {s["id"] for s in card["skills"]}
    assert "delegate" in skill_ids
    assert "pickup" in skill_ids
    assert "deliver" in skill_ids
    assert "browse" in skill_ids
    assert "register" in skill_ids


@pytest.mark.asyncio
async def test_agent_card_has_auth_info(client):
    resp = await client.get("/.well-known/agent.json")
    card = resp.json()

    assert "authentication" in card
    assert "bearer" in card["authentication"]["schemes"]


@pytest.mark.asyncio
async def test_agent_card_cors_header(client):
    resp = await client.get("/.well-known/agent.json")
    assert resp.headers.get("access-control-allow-origin") == "*"
