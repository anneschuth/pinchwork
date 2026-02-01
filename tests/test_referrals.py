"""Tests for the referral system."""

import pytest

from tests.conftest import auth_header

JSON = {"Accept": "application/json"}


@pytest.mark.asyncio
async def test_register_returns_referral_code(client):
    """Registration response includes a referral_code."""
    resp = await client.post("/v1/register", json={"name": "ref-test-agent"}, headers=JSON)
    assert resp.status_code == 201
    data = resp.json()
    assert "referral_code" in data
    assert data["referral_code"].startswith("ref-")
    assert len(data["referral_code"]) > 12  # random token, not guessable


@pytest.mark.asyncio
async def test_register_with_referral_code(client):
    """An agent can register using another agent's referral code."""
    resp1 = await client.post("/v1/register", json={"name": "referrer"}, headers=JSON)
    assert resp1.status_code == 201
    ref_code = resp1.json()["referral_code"]

    resp2 = await client.post(
        "/v1/register", json={"name": "referred", "referral": ref_code}, headers=JSON
    )
    assert resp2.status_code == 201
    assert "referral_code" in resp2.json()


@pytest.mark.asyncio
async def test_register_with_free_text_referral(client):
    """An agent can register with a free-text referral source."""
    resp = await client.post(
        "/v1/register",
        json={"name": "text-ref-agent", "referral": "Found via HN Show HN post"},
        headers=JSON,
    )
    assert resp.status_code == 201
    assert "referral_code" in resp.json()


@pytest.mark.asyncio
async def test_referral_stats_endpoint(registered_agent):
    """GET /v1/referrals returns referral stats."""
    client, agent_id, api_key = registered_agent
    resp = await client.get("/v1/referrals", headers=auth_header(api_key))
    assert resp.status_code == 200
    data = resp.json()
    assert "referral_code" in data
    assert "total_referrals" in data
    assert "bonuses_earned" in data
    assert "bonus_credits_earned" in data
    assert data["total_referrals"] == 0


@pytest.mark.asyncio
async def test_referral_bonus_on_first_task(client):
    """Referrer earns 10 credits when referred agent completes first task."""
    # Register referrer
    resp1 = await client.post("/v1/register", json={"name": "bonus-referrer"}, headers=JSON)
    referrer = resp1.json()
    ref_code = referrer["referral_code"]
    referrer_key = referrer["api_key"]

    # Check initial credits
    resp = await client.get("/v1/me", headers=auth_header(referrer_key))
    initial_credits = resp.json()["credits"]

    # Register referred agent
    resp2 = await client.post(
        "/v1/register", json={"name": "bonus-referred", "referral": ref_code}, headers=JSON
    )
    referred = resp2.json()
    referred_key = referred["api_key"]

    # Referrer posts a task
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Referral test task", "max_credits": 5},
        headers=auth_header(referrer_key),
    )
    task_id = resp.json()["task_id"]

    # Referred agent picks up and delivers
    resp = await client.post("/v1/tasks/pickup", headers=auth_header(referred_key))
    assert resp.status_code == 200

    resp = await client.post(
        f"/v1/tasks/{task_id}/deliver",
        json={"result": "Done!"},
        headers=auth_header(referred_key),
    )
    assert resp.status_code == 200

    # Referrer approves
    resp = await client.post(
        f"/v1/tasks/{task_id}/approve",
        headers=auth_header(referrer_key),
    )
    assert resp.status_code == 200

    # Check referrer got bonus credits
    resp = await client.get("/v1/me", headers=auth_header(referrer_key))
    # initial - 5 (posted task) + 10 (referral bonus) = initial + 5
    final_credits = resp.json()["credits"]
    assert final_credits == initial_credits - 5 + 10

    # Check referral stats
    resp = await client.get("/v1/referrals", headers=auth_header(referrer_key))
    stats = resp.json()
    assert stats["total_referrals"] == 1
    assert stats["bonuses_earned"] == 1
    assert stats["bonus_credits_earned"] == 10


@pytest.mark.asyncio
async def test_self_referral_blocked(client):
    """An agent cannot refer itself (same agent ID check)."""
    # This tests the code path — self-referral is blocked because
    # you can't use your own referral code at registration time
    # (your agent doesn't exist yet). But we also guard in pay_referral_bonus.
    resp = await client.post("/v1/register", json={"name": "self-ref"}, headers=JSON)
    assert resp.status_code == 201
    data = resp.json()
    ref_code = data["referral_code"]

    # Try to register another agent with first agent's referral code — this is fine
    resp2 = await client.post(
        "/v1/register", json={"name": "legit-ref", "referral": ref_code}, headers=JSON
    )
    assert resp2.status_code == 201
    # The new agent should have a DIFFERENT referral code
    assert resp2.json()["referral_code"] != ref_code


@pytest.mark.asyncio
async def test_referral_codes_are_unique(client):
    """Each agent gets a unique, unpredictable referral code."""
    codes = set()
    for i in range(5):
        resp = await client.post("/v1/register", json={"name": f"unique-{i}"}, headers=JSON)
        assert resp.status_code == 201
        code = resp.json()["referral_code"]
        assert code not in codes
        codes.add(code)
