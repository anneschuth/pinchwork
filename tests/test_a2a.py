"""Tests for the A2A JSON-RPC 2.0 endpoint."""

import pytest

from tests.conftest import auth_header

# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_card(client):
    resp = await client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Pinchwork"
    assert data["capabilities"]["streaming"] is False
    assert data["capabilities"]["pushNotifications"] is False
    assert len(data["skills"]) >= 4


@pytest.mark.asyncio
async def test_agent_card_legacy_redirect(client):
    """Legacy /.well-known/agent-card.json redirects to /.well-known/agent.json."""
    resp = await client.get("/.well-known/agent-card.json", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/.well-known/agent.json"


# ---------------------------------------------------------------------------
# JSON-RPC envelope validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a2a_requires_auth(client):
    """A2A endpoint requires Bearer auth just like the REST API."""
    resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/send",
            "params": {},
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_a2a_invalid_json(registered_agent):
    client, _, api_key = registered_agent
    resp = await client.post(
        "/a2a",
        content=b"not json",
        headers={**auth_header(api_key), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["error"]["code"] == -32700  # Parse error


@pytest.mark.asyncio
async def test_a2a_invalid_jsonrpc_version(registered_agent):
    client, _, api_key = registered_agent
    resp = await client.post(
        "/a2a",
        json={"jsonrpc": "1.0", "id": "1", "method": "message/send", "params": {}},
        headers=auth_header(api_key),
    )
    data = resp.json()
    assert data["error"]["code"] == -32600  # Invalid request


@pytest.mark.asyncio
async def test_a2a_method_not_found(registered_agent):
    client, _, api_key = registered_agent
    resp = await client.post(
        "/a2a",
        json={"jsonrpc": "2.0", "id": "1", "method": "nonexistent/method", "params": {}},
        headers=auth_header(api_key),
    )
    data = resp.json()
    assert data["error"]["code"] == -32601  # Method not found
    assert data["id"] == "1"


@pytest.mark.asyncio
async def test_a2a_missing_method(registered_agent):
    client, _, api_key = registered_agent
    resp = await client.post(
        "/a2a",
        json={"jsonrpc": "2.0", "id": "1", "params": {}},
        headers=auth_header(api_key),
    )
    data = resp.json()
    assert data["error"]["code"] == -32600  # Invalid request


# ---------------------------------------------------------------------------
# message/send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_send(registered_agent):
    """message/send creates a Pinchwork task and returns an A2A Task."""
    client, agent_id, api_key = registered_agent
    resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "msg-1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Review my Python code for bugs"}],
                },
            },
        },
        headers=auth_header(api_key),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == "msg-1"
    assert "result" in data
    assert "error" not in data

    task = data["result"]
    assert "id" in task
    assert task["kind"] == "task"
    assert "contextId" in task
    assert task["status"]["state"] == "submitted"
    assert "timestamp" in task["status"]
    assert task["metadata"]["poster_id"] == agent_id


@pytest.mark.asyncio
async def test_message_send_invalid_max_credits(registered_agent):
    """message/send rejects invalid max_credits with -32602."""
    client, _, api_key = registered_agent
    resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "bad-credits",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Test task"}],
                },
                "metadata": {"max_credits": -5},
            },
        },
        headers=auth_header(api_key),
    )
    data = resp.json()
    assert data["error"]["code"] == -32602  # Invalid params


@pytest.mark.asyncio
async def test_message_send_with_metadata(registered_agent):
    """message/send accepts Pinchwork-specific metadata (credits, tags)."""
    client, _, api_key = registered_agent
    resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "msg-2",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Write a blog post about AI agents"}],
                },
                "metadata": {
                    "max_credits": 25,
                    "tags": ["writing", "blog"],
                    "context": "Target audience: developers",
                },
            },
        },
        headers=auth_header(api_key),
    )
    data = resp.json()
    task = data["result"]
    assert task["status"]["state"] == "submitted"
    assert task["metadata"]["max_credits"] == 25


@pytest.mark.asyncio
async def test_message_send_empty_parts(registered_agent):
    """message/send rejects messages with no parts."""
    client, _, api_key = registered_agent
    resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "msg-3",
            "method": "message/send",
            "params": {
                "message": {"role": "user", "parts": []},
            },
        },
        headers=auth_header(api_key),
    )
    data = resp.json()
    assert data["error"]["code"] == -32602  # Invalid params


@pytest.mark.asyncio
async def test_message_send_missing_message(registered_agent):
    """message/send rejects requests without a message."""
    client, _, api_key = registered_agent
    resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "msg-4",
            "method": "message/send",
            "params": {},
        },
        headers=auth_header(api_key),
    )
    data = resp.json()
    assert data["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# tasks/get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tasks_get(registered_agent):
    """tasks/get retrieves a task in A2A format."""
    client, agent_id, api_key = registered_agent

    # First create a task via message/send
    create_resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "c1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Do some research"}],
                },
            },
        },
        headers=auth_header(api_key),
    )
    task_id = create_resp.json()["result"]["id"]

    # Now get it
    get_resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "g1",
            "method": "tasks/get",
            "params": {"id": task_id},
        },
        headers=auth_header(api_key),
    )
    data = get_resp.json()
    assert data["id"] == "g1"
    assert data["result"]["id"] == task_id
    assert data["result"]["status"]["state"] == "submitted"


@pytest.mark.asyncio
async def test_tasks_get_not_found(registered_agent):
    """tasks/get returns error for non-existent task."""
    client, _, api_key = registered_agent
    resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "g2",
            "method": "tasks/get",
            "params": {"id": "nonexistent-task-id"},
        },
        headers=auth_header(api_key),
    )
    data = resp.json()
    assert data["error"]["code"] == -32001  # Task not found


@pytest.mark.asyncio
async def test_tasks_get_access_control(two_agents):
    """tasks/get denies access to tasks not owned by the caller."""
    client = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    # Poster creates a task
    create_resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "c1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Secret task"}],
                },
            },
        },
        headers=auth_header(poster["key"]),
    )
    task_id = create_resp.json()["result"]["id"]

    # Worker tries to get it (should fail — not poster or worker)
    get_resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "g1",
            "method": "tasks/get",
            "params": {"id": task_id},
        },
        headers=auth_header(worker["key"]),
    )
    data = get_resp.json()
    assert data["error"]["code"] == -32001


@pytest.mark.asyncio
async def test_tasks_get_missing_id(registered_agent):
    """tasks/get rejects requests without an id."""
    client, _, api_key = registered_agent
    resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "g3",
            "method": "tasks/get",
            "params": {},
        },
        headers=auth_header(api_key),
    )
    data = resp.json()
    assert data["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# tasks/cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tasks_cancel(registered_agent):
    """tasks/cancel cancels a posted task."""
    client, agent_id, api_key = registered_agent

    # Create a task
    create_resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "c1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Task to cancel"}],
                },
            },
        },
        headers=auth_header(api_key),
    )
    task_id = create_resp.json()["result"]["id"]

    # Cancel it
    cancel_resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "x1",
            "method": "tasks/cancel",
            "params": {"id": task_id},
        },
        headers=auth_header(api_key),
    )
    data = cancel_resp.json()
    assert data["id"] == "x1"
    assert data["result"]["status"]["state"] == "canceled"


@pytest.mark.asyncio
async def test_tasks_cancel_not_poster(two_agents):
    """tasks/cancel denies cancellation by non-poster."""
    client = two_agents["client"]
    poster = two_agents["poster"]
    worker = two_agents["worker"]

    # Poster creates a task
    create_resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "c1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Not your task"}],
                },
            },
        },
        headers=auth_header(poster["key"]),
    )
    task_id = create_resp.json()["result"]["id"]

    # Worker tries to cancel (should fail)
    cancel_resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "x1",
            "method": "tasks/cancel",
            "params": {"id": task_id},
        },
        headers=auth_header(worker["key"]),
    )
    data = cancel_resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_tasks_cancel_missing_id(registered_agent):
    """tasks/cancel rejects requests without an id."""
    client, _, api_key = registered_agent
    resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "x2",
            "method": "tasks/cancel",
            "params": {},
        },
        headers=auth_header(api_key),
    )
    data = resp.json()
    assert data["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# End-to-end: message/send → tasks/get roundtrip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_roundtrip_send_then_get(registered_agent):
    """Full roundtrip: create via message/send, retrieve via tasks/get."""
    client, _, api_key = registered_agent

    # Send
    send_resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "rt-1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Roundtrip test task"}],
                },
                "metadata": {"max_credits": 10, "tags": ["test"]},
            },
        },
        headers=auth_header(api_key),
    )
    task = send_resp.json()["result"]
    assert task["status"]["state"] == "submitted"

    # Get
    get_resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "rt-2",
            "method": "tasks/get",
            "params": {"id": task["id"]},
        },
        headers=auth_header(api_key),
    )
    fetched = get_resp.json()["result"]
    assert fetched["id"] == task["id"]
    assert fetched["status"]["state"] == "submitted"


# ---------------------------------------------------------------------------
# JSON-RPC id propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_id_propagation(registered_agent):
    """JSON-RPC id is always echoed back in responses."""
    client, _, api_key = registered_agent

    for req_id in ["string-id", 42, None]:
        resp = await client.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": f"id test {req_id}"}],
                    },
                },
            },
            headers=auth_header(api_key),
        )
        data = resp.json()
        assert data["id"] == req_id
