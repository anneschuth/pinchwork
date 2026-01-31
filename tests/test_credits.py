"""Test credit system: escrow, release, refund, ledger."""

from __future__ import annotations

import pytest

from tests.conftest import auth_header, register_agent


@pytest.mark.asyncio
async def test_credit_ledger(client):
    agent = await register_agent(client, "ledger-test")
    resp = await client.get("/v1/me/credits", headers=auth_header(agent["api_key"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["balance"] == 100
    assert data["total"] == 1
    assert len(data["ledger"]) == 1
    assert data["ledger"][0]["reason"] == "signup_bonus"
    assert data["ledger"][0]["amount"] == 100


@pytest.mark.asyncio
async def test_escrow_and_refund_on_reject(client):
    poster = await register_agent(client, "poster")
    worker = await register_agent(client, "worker")

    # Post task (escrows 10)
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Quick task", "max_credits": 10},
        headers=auth_header(poster["api_key"]),
    )
    task_id = resp.json()["task_id"]

    # Poster has 90 after escrow
    resp = await client.get("/v1/me", headers=auth_header(poster["api_key"]))
    assert resp.json()["credits"] == 90

    # Worker picks up and delivers
    await client.post("/v1/tasks/pickup", headers=auth_header(worker["api_key"]))
    await client.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "done", "credits_claimed": 5},
        headers=auth_header(worker["api_key"]),
    )

    # Poster rejects — task goes back to posted, no credit movement yet
    await client.post(f"/v1/tasks/{task_id}/reject", headers=auth_header(poster["api_key"]))

    # Poster still has 90 (escrow still held)
    resp = await client.get("/v1/me", headers=auth_header(poster["api_key"]))
    assert resp.json()["credits"] == 90

    # Worker still has 100 (no payment)
    resp = await client.get("/v1/me", headers=auth_header(worker["api_key"]))
    assert resp.json()["credits"] == 100
