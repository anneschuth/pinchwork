"""Tests for the admin dashboard."""

from __future__ import annotations

import pytest

from pinchwork.config import settings
from pinchwork.db_models import Agent
from tests.conftest import auth_header, register_agent


@pytest.fixture(autouse=True)
async def ensure_platform_agent(db):
    async with db() as session:
        existing = await session.get(Agent, settings.platform_agent_id)
        if not existing:
            platform = Agent(
                id=settings.platform_agent_id,
                name="platform",
                key_hash="",
                key_fingerprint="",
                credits=999_999_999,
            )
            session.add(platform)
            await session.commit()


@pytest.fixture
def admin_key():
    """Set a test admin key."""
    original = settings.admin_key
    settings.admin_key = "test-admin-secret-key"
    yield settings.admin_key
    settings.admin_key = original


@pytest.fixture
def no_admin_key():
    """Ensure no admin key is set."""
    original = settings.admin_key
    settings.admin_key = None
    yield
    settings.admin_key = original


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_rejects_without_cookie(client, admin_key):
    resp = await client.get("/admin", follow_redirects=False)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_admin_login_page_renders(client, admin_key):
    resp = await client.get("/admin/login")
    assert resp.status_code == 200
    assert "Admin Login" in resp.text
    assert "password" in resp.text


@pytest.mark.anyio
async def test_admin_login_rejects_wrong_key(client, admin_key):
    csrf = await _get_csrf(client)
    resp = await client.post(
        "/admin/login",
        data={"key": "wrong-key", "csrf": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error" in resp.headers.get("location", "")


@pytest.mark.anyio
async def test_admin_login_rejects_missing_csrf(client, admin_key):
    resp = await client.post(
        "/admin/login",
        data={"key": admin_key},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error" in resp.headers.get("location", "")


@pytest.mark.anyio
async def test_admin_login_accepts_correct_key(client, admin_key):
    csrf = await _get_csrf(client)
    resp = await client.post(
        "/admin/login",
        data={"key": admin_key, "csrf": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers.get("location") == "/admin"
    # Should have a cookie set
    assert "pw_admin" in resp.headers.get("set-cookie", "")


@pytest.mark.anyio
async def test_admin_returns_501_without_key(client, no_admin_key):
    resp = await client.get("/admin/login")
    assert resp.status_code == 501


@pytest.mark.anyio
async def test_admin_logout_clears_cookie(client, admin_key):
    cookies = await _login(client, admin_key)

    resp = await client.get("/admin/logout", follow_redirects=False, cookies=cookies)
    assert resp.status_code == 303
    assert "/admin/login" in resp.headers.get("location", "")


# ---------------------------------------------------------------------------
# Authenticated page tests
# ---------------------------------------------------------------------------


async def _get_csrf(client):
    """Fetch CSRF token from the login page."""
    import re

    resp = await client.get("/admin/login")
    match = re.search(r'name="csrf" value="([^"]+)"', resp.text)
    assert match, "CSRF token not found in login page"
    return match.group(1)


async def _login(client, admin_key):
    """Login and return cookies."""
    csrf = await _get_csrf(client)
    resp = await client.post(
        "/admin/login",
        data={"key": admin_key, "csrf": csrf},
        follow_redirects=False,
    )
    return resp.cookies


@pytest.mark.anyio
async def test_admin_overview_loads(client, admin_key):
    cookies = await _login(client, admin_key)
    resp = await client.get("/admin", cookies=cookies)
    assert resp.status_code == 200
    assert "Overview" in resp.text
    assert "Agents" in resp.text
    assert "Total Tasks" in resp.text
    assert "noindex" in resp.text


@pytest.mark.anyio
async def test_admin_overview_shows_stats(client, admin_key):
    # Create some data
    agent = await register_agent(client, "admin-test-agent")
    await client.post(
        "/v1/tasks",
        json={"need": "Test task for admin", "max_credits": 10},
        headers=auth_header(agent["api_key"]),
    )

    cookies = await _login(client, admin_key)
    resp = await client.get("/admin", cookies=cookies)
    assert resp.status_code == 200
    # Should show at least 1 agent and 1 task
    assert "admin-test-agent" in resp.text or "1" in resp.text


@pytest.mark.anyio
async def test_admin_tasks_page(client, admin_key):
    agent = await register_agent(client, "task-list-agent")
    await client.post(
        "/v1/tasks",
        json={"need": "Admin task list test", "max_credits": 5},
        headers=auth_header(agent["api_key"]),
    )

    cookies = await _login(client, admin_key)
    resp = await client.get("/admin/tasks", cookies=cookies)
    assert resp.status_code == 200
    assert "Admin task list test" in resp.text
    assert "Tasks" in resp.text


@pytest.mark.anyio
async def test_admin_tasks_filter_by_status(client, admin_key):
    cookies = await _login(client, admin_key)
    resp = await client.get("/admin/tasks?status=posted", cookies=cookies)
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_admin_tasks_filter_system(client, admin_key):
    cookies = await _login(client, admin_key)
    resp = await client.get("/admin/tasks?system=hide", cookies=cookies)
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_admin_task_detail(client, admin_key):
    agent = await register_agent(client, "detail-test-agent")
    create_resp = await client.post(
        "/v1/tasks",
        json={"need": "Detailed task for admin view", "max_credits": 15, "tags": ["test"]},
        headers=auth_header(agent["api_key"]),
    )
    task_id = create_resp.json()["task_id"]

    cookies = await _login(client, admin_key)
    resp = await client.get(f"/admin/tasks/{task_id}", cookies=cookies)
    assert resp.status_code == 200
    assert "Detailed task for admin view" in resp.text
    assert task_id in resp.text
    assert "test" in resp.text  # tag


@pytest.mark.anyio
async def test_admin_task_detail_not_found(client, admin_key):
    cookies = await _login(client, admin_key)
    resp = await client.get("/admin/tasks/nonexistent", cookies=cookies)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_admin_agents_page(client, admin_key):
    await register_agent(client, "agents-page-test")

    cookies = await _login(client, admin_key)
    resp = await client.get("/admin/agents", cookies=cookies)
    assert resp.status_code == 200
    assert "agents-page-test" in resp.text


@pytest.mark.anyio
async def test_admin_agents_sort(client, admin_key):
    cookies = await _login(client, admin_key)
    for sort in ["tasks", "credits", "recent", "reputation"]:
        resp = await client.get(f"/admin/agents?sort={sort}", cookies=cookies)
        assert resp.status_code == 200


@pytest.mark.anyio
async def test_admin_agent_detail(client, admin_key):
    agent = await register_agent(client, "agent-detail-test")

    cookies = await _login(client, admin_key)
    resp = await client.get(f"/admin/agents/{agent['agent_id']}", cookies=cookies)
    assert resp.status_code == 200
    assert "agent-detail-test" in resp.text
    assert agent["agent_id"] in resp.text
    assert "Credit Ledger" in resp.text


@pytest.mark.anyio
async def test_admin_agent_detail_not_found(client, admin_key):
    cookies = await _login(client, admin_key)
    resp = await client.get("/admin/agents/nonexistent", cookies=cookies)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_admin_escapes_html_in_task(client, admin_key):
    agent = await register_agent(client, "xss-admin-test")
    create_resp = await client.post(
        "/v1/tasks",
        json={"need": "<script>alert('xss')</script>", "max_credits": 5},
        headers=auth_header(agent["api_key"]),
    )
    task_id = create_resp.json()["task_id"]

    cookies = await _login(client, admin_key)
    resp = await client.get(f"/admin/tasks/{task_id}", cookies=cookies)
    assert resp.status_code == 200
    assert "<script>" not in resp.text
    assert "&lt;script&gt;" in resp.text


@pytest.mark.anyio
async def test_admin_escapes_html_in_agent_name(client, admin_key):
    await register_agent(client, '<img src=x onerror="alert(1)">')

    cookies = await _login(client, admin_key)
    resp = await client.get("/admin/agents", cookies=cookies)
    assert resp.status_code == 200
    assert "<img src=x" not in resp.text


@pytest.mark.anyio
async def test_admin_cookie_httponly_samesite(client, admin_key):
    csrf = await _get_csrf(client)
    resp = await client.post(
        "/admin/login",
        data={"key": admin_key, "csrf": csrf},
        follow_redirects=False,
    )
    cookie_header = resp.headers.get("set-cookie", "")
    assert "httponly" in cookie_header.lower()
    assert "samesite=strict" in cookie_header.lower()
    # secure flag is only set for HTTPS/non-localhost (test runs on http://test)


@pytest.mark.anyio
async def test_admin_pages_have_noindex(client, admin_key):
    cookies = await _login(client, admin_key)
    for path in ["/admin", "/admin/tasks", "/admin/agents"]:
        resp = await client.get(path, cookies=cookies)
        assert "noindex" in resp.text, f"{path} missing noindex"


@pytest.mark.anyio
async def test_robots_txt_disallows_admin(client):
    resp = await client.get("/robots.txt")
    assert "Disallow: /admin" in resp.text


@pytest.mark.anyio
async def test_admin_referrals_page(client, admin_key):
    cookies = await _login(client, admin_key)
    resp = await client.get("/admin/referrals", cookies=cookies)
    assert resp.status_code == 200
    assert "Referrals" in resp.text
    assert "Successful Referrers" in resp.text
    assert "Welcome Task Completers" in resp.text
    assert "Likely Test" in resp.text
    assert "noindex" in resp.text


@pytest.mark.anyio
async def test_admin_stats_page(client, admin_key):
    cookies = await _login(client, admin_key)
    resp = await client.get("/admin/stats", cookies=cookies)
    assert resp.status_code == 200
    assert "Route Statistics" in resp.text
    assert "Total Requests" in resp.text
    assert "Top Routes" in resp.text
    assert "noindex" in resp.text


@pytest.mark.anyio
async def test_admin_stats_filter(client, admin_key):
    cookies = await _login(client, admin_key)
    resp = await client.get("/admin/stats?prefix=/v1", cookies=cookies)
    assert resp.status_code == 200
    assert "Route Statistics" in resp.text
