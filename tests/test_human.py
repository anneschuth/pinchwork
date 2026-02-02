"""Tests for the browser-facing /human dashboard."""

from __future__ import annotations

import pytest

from pinchwork.config import settings
from pinchwork.db_models import Agent
from tests.conftest import auth_header, register_agent


@pytest.fixture(autouse=True)
async def ensure_platform_agent(db):
    """Create the platform agent so welcome tasks can escrow credits."""
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


@pytest.mark.anyio
async def test_root_redirects_browser_to_human(client):
    resp = await client.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/human"


@pytest.mark.anyio
async def test_root_redirects_agent_to_skill_md(client):
    resp = await client.get("/", headers={"Accept": "*/*"}, follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/skill.md"


@pytest.mark.anyio
async def test_root_redirects_json_to_skill_md(client):
    resp = await client.get("/", headers={"Accept": "application/json"}, follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/skill.md"


@pytest.mark.anyio
async def test_human_returns_html(client):
    resp = await client.get("/human")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Pinchwork" in resp.text
    assert "PINCHWORK" in resp.text


@pytest.mark.anyio
async def test_human_shows_stats(client):
    # Register an agent
    await register_agent(client, "dashboard-test-agent")
    resp = await client.get("/human")
    assert resp.status_code == 200
    # Should show at least 1 agent
    assert "<b>1</b> agents" in resp.text


@pytest.mark.anyio
async def test_human_shows_recent_tasks(client):
    agent = await register_agent(client, "task-poster")
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Translate this document into French", "max_credits": 10},
        headers=auth_header(agent["api_key"]),
    )
    assert resp.status_code == 201

    resp = await client.get("/human")
    assert resp.status_code == 200
    assert "Translate this document into French" in resp.text


@pytest.mark.anyio
async def test_human_escapes_html(client):
    agent = await register_agent(client, "xss-tester")
    resp = await client.post(
        "/v1/tasks",
        json={"need": "<script>alert('xss')</script>", "max_credits": 5},
        headers=auth_header(agent["api_key"]),
    )
    assert resp.status_code == 201

    resp = await client.get("/human")
    assert resp.status_code == 200
    # The script tag should be escaped, not raw
    assert "<script>" not in resp.text
    assert "&lt;script&gt;" in resp.text


@pytest.mark.anyio
async def test_task_detail_page(client):
    agent = await register_agent(client, "detail-poster")
    resp = await client.post(
        "/v1/tasks",
        json={
            "need": "A very long task description that should be fully visible on the detail page",
            "max_credits": 20,
            "tags": ["test", "detail"],
        },
        headers=auth_header(agent["api_key"]),
    )
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]

    resp = await client.get(f"/human/tasks/{task_id}")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    # Full need text, not truncated
    assert "A very long task description that should be fully visible" in resp.text
    # Task ID displayed
    assert task_id in resp.text
    # Curl pickup command shown (task is posted)
    assert "curl" in resp.text
    assert "/pickup" in resp.text
    # Tags shown
    assert "test" in resp.text
    assert "detail" in resp.text
    # Back link
    assert "/human" in resp.text


@pytest.mark.anyio
async def test_task_detail_not_found(client):
    resp = await client.get("/human/tasks/tk_nonexistent")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


@pytest.mark.anyio
async def test_task_detail_escapes_html(client):
    agent = await register_agent(client, "xss-detail")
    resp = await client.post(
        "/v1/tasks",
        json={"need": "<img src=x onerror=alert(1)>", "max_credits": 5},
        headers=auth_header(agent["api_key"]),
    )
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]

    resp = await client.get(f"/human/tasks/{task_id}")
    assert resp.status_code == 200
    assert "<img src=x" not in resp.text
    assert "&lt;img" in resp.text


@pytest.mark.anyio
async def test_dashboard_task_ids_are_links(client):
    agent = await register_agent(client, "link-poster")
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Some task", "max_credits": 5},
        headers=auth_header(agent["api_key"]),
    )
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]

    resp = await client.get("/human")
    assert resp.status_code == 200
    assert f'/human/tasks/{task_id}"' in resp.text


@pytest.mark.anyio
async def test_robots_txt(client):
    resp = await client.get("/robots.txt")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "Disallow: /v1/" in resp.text
    assert "Allow: /human" in resp.text
    assert "Allow: /skill.md" in resp.text
    assert "Disallow: /docs" in resp.text
    assert "Disallow: /openapi.json" in resp.text


@pytest.mark.anyio
async def test_humans_txt(client):
    resp = await client.get("/humans.txt")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "TEAM" in resp.text
    assert "Pinchwork" in resp.text


@pytest.mark.anyio
async def test_security_txt(client):
    resp = await client.get("/.well-known/security.txt")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "Contact:" in resp.text


@pytest.mark.anyio
async def test_favicon_ico(client):
    resp = await client.get("/favicon.ico")
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.headers["content-type"]


@pytest.mark.anyio
async def test_terms_page(client):
    resp = await client.get("/terms")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "As-Is" in resp.text
    assert "No Warranty" in resp.text
    assert "Content Responsibility" in resp.text
    assert "No Liability" in resp.text
    assert "Acceptable Use" in resp.text
    assert "Credits" in resp.text


@pytest.mark.anyio
async def test_task_detail_has_noindex_meta(client):
    agent = await register_agent(client, "noindex-poster")
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Test noindex meta", "max_credits": 5},
        headers=auth_header(agent["api_key"]),
    )
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]

    resp = await client.get(f"/human/tasks/{task_id}")
    assert resp.status_code == 200
    assert 'name="robots" content="noindex, nofollow"' in resp.text


@pytest.mark.anyio
async def test_dashboard_footer_links_to_terms(client):
    resp = await client.get("/human")
    assert resp.status_code == 200
    assert "/terms" in resp.text
    assert "user-generated" in resp.text


@pytest.mark.anyio
async def test_dashboard_shows_visibility_note(client):
    resp = await client.get("/human")
    assert resp.status_code == 200
    assert "publicly visible" in resp.text


@pytest.mark.anyio
async def test_dashboard_hides_welcome_tasks(client):
    """Welcome tasks should not appear on the public dashboard."""
    # Register an agent - this creates a welcome task automatically
    agent = await register_agent(client, "welcome-test-agent")

    # Verify the welcome task exists via agent API
    resp = await client.get("/v1/tasks/available", headers=auth_header(agent["api_key"]))
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    welcome_task = next((t for t in tasks if "Welcome to Pinchwork" in t.get("need", "")), None)
    assert welcome_task is not None, "Welcome task should exist for new agent"

    # Check dashboard doesn't show the welcome task
    resp = await client.get("/human")
    assert resp.status_code == 200
    assert "Welcome to Pinchwork" not in resp.text
    assert welcome_task["task_id"] not in resp.text


@pytest.mark.anyio
async def test_dashboard_stats_exclude_welcome_tasks(client):
    """Dashboard stats should not count welcome tasks."""
    # Get initial stats
    resp = await client.get("/human")
    assert resp.status_code == 200
    initial_html = resp.text

    # Extract task count from stats (looking for pattern like "<b>X</b> tasks")
    import re

    match = re.search(r"<b>(\d+)</b> tasks", initial_html)
    initial_count = int(match.group(1)) if match else 0

    # Register a new agent (creates welcome task)
    agent = await register_agent(client, "stats-test-agent")

    # Verify welcome task exists
    resp = await client.get("/v1/tasks/available", headers=auth_header(agent["api_key"]))
    welcome_tasks = [t for t in resp.json()["tasks"] if "Welcome to Pinchwork" in t.get("need", "")]
    assert len(welcome_tasks) > 0

    # Check stats haven't changed
    resp = await client.get("/human")
    assert resp.status_code == 200
    match = re.search(r"<b>(\d+)</b> tasks", resp.text)
    new_count = int(match.group(1)) if match else 0
    assert new_count == initial_count, "Welcome tasks should not be counted in dashboard stats"


@pytest.mark.anyio
async def test_welcome_task_detail_returns_404(client):
    """Direct access to welcome task detail page should return 404."""
    # Register agent and get welcome task ID
    agent = await register_agent(client, "detail-404-test")
    resp = await client.get("/v1/tasks/available", headers=auth_header(agent["api_key"]))
    tasks = resp.json()["tasks"]
    welcome_task = next((t for t in tasks if "Welcome to Pinchwork" in t.get("need", "")), None)
    assert welcome_task is not None

    # Try to access the welcome task detail page
    resp = await client.get(f"/human/tasks/{welcome_task['task_id']}")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


@pytest.mark.anyio
async def test_welcome_task_still_accessible_via_api(client):
    """Welcome tasks should still be fully accessible via agent API endpoints."""
    # Register agent
    agent = await register_agent(client, "api-access-test")

    # Get welcome task via API
    resp = await client.get("/v1/tasks/available", headers=auth_header(agent["api_key"]))
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    welcome_task = next((t for t in tasks if "Welcome to Pinchwork" in t.get("need", "")), None)
    assert welcome_task is not None

    # Pickup the welcome task
    resp = await client.post(
        f"/v1/tasks/{welcome_task['task_id']}/pickup", headers=auth_header(agent["api_key"])
    )
    assert resp.status_code == 200

    # Deliver the welcome task
    resp = await client.post(
        f"/v1/tasks/{welcome_task['task_id']}/deliver",
        headers=auth_header(agent["api_key"]),
        json={"result": "Hello! I'm ready to work."},
    )
    assert resp.status_code == 200

    # Verify task is now delivered
    resp = await client.get(
        f"/v1/tasks/{welcome_task['task_id']}", headers=auth_header(agent["api_key"])
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "delivered"


@pytest.mark.anyio
async def test_dashboard_with_regular_and_welcome_tasks(client):
    """Regular tasks should be visible, welcome tasks should be hidden."""
    # Register agent (creates welcome task)
    agent = await register_agent(client, "mixed-test-agent")

    # Create a regular task
    resp = await client.post(
        "/v1/tasks",
        json={"need": "Regular task for testing", "max_credits": 15},
        headers=auth_header(agent["api_key"]),
    )
    assert resp.status_code == 201
    regular_task_id = resp.json()["task_id"]

    # Get welcome task ID
    resp = await client.get("/v1/tasks/available", headers=auth_header(agent["api_key"]))
    tasks = resp.json()["tasks"]
    welcome_task = next((t for t in tasks if "Welcome to Pinchwork" in t.get("need", "")), None)
    assert welcome_task is not None

    # Check dashboard
    resp = await client.get("/human")
    assert resp.status_code == 200

    # Regular task should be visible
    assert "Regular task for testing" in resp.text
    assert regular_task_id in resp.text

    # Welcome task should NOT be visible
    assert "Welcome to Pinchwork" not in resp.text
    assert welcome_task["task_id"] not in resp.text
