"""Test content negotiation: markdown and JSON parsing."""

from __future__ import annotations

import pytest

from tests.conftest import auth_header, register_agent


@pytest.mark.asyncio
async def test_delegate_json(client):
    agent = await register_agent(client, "json-agent")
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Test task", "max_credits": 5},
        headers=auth_header(agent["api_key"]),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "posted"
    assert data["need"] == "Test task"


@pytest.mark.asyncio
async def test_delegate_markdown(client):
    agent = await register_agent(client, "md-agent")
    body = "---\nmax_credits: 5\n---\nTranslate this to French: Good morning"
    resp = await client.post(
        "/v1/tasks",
        content=body.encode(),
        headers={
            **auth_header(agent["api_key"]),
            "Content-Type": "text/markdown",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["need"] == "Translate this to French: Good morning"


@pytest.mark.asyncio
async def test_markdown_response(client):
    await register_agent(client, "md-reader")
    # Don't send Accept: application/json → get markdown
    resp = await client.post(
        "/v1/register",
        json={"name": "md-test"},
    )
    assert resp.status_code == 201
    assert resp.headers["content-type"].startswith("text/markdown")


@pytest.mark.asyncio
async def test_register_markdown_body(client):
    body = "---\nname: frontmatter-agent\n---\n"
    resp = await client.post(
        "/v1/register",
        content=body.encode(),
        headers={"Accept": "application/json", "Content-Type": "text/markdown"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_id"].startswith("ag_")
