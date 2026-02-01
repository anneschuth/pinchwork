"""Tests for the llms.txt endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from pinchwork.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_llms_txt_returns_text(client):
    resp = await client.get("/llms.txt")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_llms_txt_has_content(client):
    resp = await client.get("/llms.txt")
    text = resp.text
    assert "Pinchwork" in text
    assert "/v1/register" in text
    assert "/v1/tasks" in text
    assert "agent-card.json" in text
