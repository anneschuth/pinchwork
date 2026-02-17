"""Tests for the /v1/discover endpoint and agent_discovery service.

Includes:
- Unit tests (mocked HTTP calls)
- Integration test against live AgentIndex API (https://api.agentcrawl.dev/a2a)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pinchwork.services.agent_discovery import (
    AgentDiscoveryError,
    _build_jsonrpc_request,
    _parse_agent,
    _parse_response,
    discover_agents,
)
from tests.conftest import auth_header, register_agent

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

SAMPLE_AGENT = {
    "id": "abc-123",
    "name": "TestAgent",
    "description": "A test agent for code review",
    "capabilities": ["code review", "static analysis"],
    "category": "coding",
    "invocation": {"type": "pip"},
    "protocols": ["rest", "a2a"],
    "pricing": {"model": "unknown"},
    "is_verified": True,
    "source_url": "https://github.com/example/test-agent",
    "stars": 42,
    "author": "example",
    "source": "github",
    "trust_score": 85.0,
    "quality_score": 80.0,
    "trust_explanation": "Well documented, highly active",
}

SAMPLE_AGENTINDEX_RESPONSE = {
    "jsonrpc": "2.0",
    "id": "test-req-1",
    "result": {
        "id": "task-uuid-1",
        "contextId": "ctx-uuid-1",
        "status": {"state": "completed"},
        "artifacts": [
            {
                "artifactId": "artifact-uuid-1",
                "parts": [
                    {
                        "type": "text",
                        "text": "Found 1 agents matching 'code review' (via fts search).",
                    },
                    {
                        "type": "data",
                        "data": {
                            "query": "code review",
                            "search_method": "fts",
                            "count": 1,
                            "agents": [SAMPLE_AGENT],
                        },
                    },
                ],
            }
        ],
        "metadata": {"responseTimeMs": 20, "skill": "discover_agents"},
    },
}

EMPTY_AGENTINDEX_RESPONSE = {
    "jsonrpc": "2.0",
    "id": "test-req-2",
    "result": {
        "id": "task-uuid-2",
        "contextId": "ctx-uuid-2",
        "status": {"state": "completed"},
        "artifacts": [
            {
                "artifactId": "artifact-uuid-2",
                "parts": [
                    {
                        "type": "text",
                        "text": "Found 0 agents matching 'xyzzy' (via fts search).",
                    },
                    {
                        "type": "data",
                        "data": {
                            "query": "xyzzy",
                            "search_method": "fts",
                            "count": 0,
                            "agents": [],
                        },
                    },
                ],
            }
        ],
        "metadata": {"responseTimeMs": 10, "skill": "discover_agents"},
    },
}

ERROR_AGENTINDEX_RESPONSE = {
    "jsonrpc": "2.0",
    "id": "test-req-3",
    "error": {"code": -32600, "message": "Invalid request"},
}


# ---------------------------------------------------------------------------
# Unit tests: _build_jsonrpc_request
# ---------------------------------------------------------------------------


def test_build_jsonrpc_request_structure():
    payload = _build_jsonrpc_request("find me a coding agent", request_id="req-1")
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == "req-1"
    assert payload["method"] == "message/send"
    assert payload["params"]["message"]["role"] == "user"
    parts = payload["params"]["message"]["parts"]
    assert len(parts) == 1
    assert parts[0]["type"] == "text"
    assert parts[0]["text"] == "find me a coding agent"


def test_build_jsonrpc_request_auto_id():
    payload = _build_jsonrpc_request("test query")
    assert payload["id"]  # should be a non-empty UUID string
    assert payload["jsonrpc"] == "2.0"


# ---------------------------------------------------------------------------
# Unit tests: _parse_agent
# ---------------------------------------------------------------------------


def test_parse_agent_full():
    agent = _parse_agent(SAMPLE_AGENT)
    assert agent["id"] == "abc-123"
    assert agent["name"] == "TestAgent"
    assert agent["description"] == "A test agent for code review"
    assert agent["capabilities"] == ["code review", "static analysis"]
    assert agent["category"] == "coding"
    assert agent["protocols"] == ["rest", "a2a"]
    assert agent["source_url"] == "https://github.com/example/test-agent"
    assert agent["author"] == "example"
    assert agent["stars"] == 42
    assert agent["trust_score"] == 85.0
    assert agent["quality_score"] == 80.0
    assert agent["is_verified"] is True


def test_parse_agent_minimal():
    """Should handle missing optional fields gracefully."""
    agent = _parse_agent({"id": "x", "name": "Minimal"})
    assert agent["id"] == "x"
    assert agent["name"] == "Minimal"
    assert agent["capabilities"] == []
    assert agent["protocols"] == []
    assert agent["trust_score"] is None
    assert agent["is_verified"] is False


# ---------------------------------------------------------------------------
# Unit tests: _parse_response
# ---------------------------------------------------------------------------


def test_parse_response_success():
    result = _parse_response(SAMPLE_AGENTINDEX_RESPONSE)
    assert result["query"] == "code review"
    assert result["search_method"] == "fts"
    assert result["count"] == 1
    assert len(result["agents"]) == 1
    assert result["agents"][0]["name"] == "TestAgent"
    assert "Found 1 agents" in result["summary"]


def test_parse_response_empty():
    result = _parse_response(EMPTY_AGENTINDEX_RESPONSE)
    assert result["count"] == 0
    assert result["agents"] == []


def test_parse_response_error():
    with pytest.raises(AgentDiscoveryError, match="Invalid request"):
        _parse_response(ERROR_AGENTINDEX_RESPONSE)


def test_parse_response_no_result():
    with pytest.raises(AgentDiscoveryError, match="no result"):
        _parse_response({"jsonrpc": "2.0", "id": "x"})


def test_parse_response_no_artifacts():
    result = _parse_response(
        {
            "jsonrpc": "2.0",
            "id": "x",
            "result": {"id": "t", "status": {"state": "completed"}, "artifacts": []},
        }
    )
    assert result["count"] == 0
    assert result["agents"] == []


# ---------------------------------------------------------------------------
# Unit tests: discover_agents (mocked HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_agents_success():
    """discover_agents should return parsed results on success."""
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_AGENTINDEX_RESPONSE
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("pinchwork.services.agent_discovery.httpx.AsyncClient", return_value=mock_client):
        result = await discover_agents("code review")

    assert result["count"] == 1
    assert len(result["agents"]) == 1
    assert result["agents"][0]["name"] == "TestAgent"


@pytest.mark.asyncio
async def test_discover_agents_with_category():
    """Category should be appended to the query."""
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_AGENTINDEX_RESPONSE
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("pinchwork.services.agent_discovery.httpx.AsyncClient", return_value=mock_client):
        await discover_agents("code review", category="coding")

    # Verify the payload sent includes category
    call_args = mock_client.post.call_args
    payload = call_args.kwargs.get("json") or call_args.args[1]
    text_part = payload["params"]["message"]["parts"][0]["text"]
    assert "category:coding" in text_part


@pytest.mark.asyncio
async def test_discover_agents_limit_applied():
    """Limit should cap the number of returned agents."""
    many_agents = [dict(SAMPLE_AGENT, id=f"agent-{i}", name=f"Agent {i}") for i in range(20)]
    response_with_many = {
        "jsonrpc": "2.0",
        "id": "x",
        "result": {
            "id": "t",
            "status": {"state": "completed"},
            "artifacts": [
                {
                    "artifactId": "a",
                    "parts": [
                        {"type": "text", "text": "Found 20 agents."},
                        {
                            "type": "data",
                            "data": {
                                "query": "agent",
                                "search_method": "fts",
                                "count": 20,
                                "agents": many_agents,
                            },
                        },
                    ],
                }
            ],
        },
    }

    mock_response = MagicMock()
    mock_response.json.return_value = response_with_many
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("pinchwork.services.agent_discovery.httpx.AsyncClient", return_value=mock_client):
        result = await discover_agents("agent", limit=5)

    assert len(result["agents"]) == 5
    # Total count should still reflect what AgentIndex returned
    assert result["count"] == 20


@pytest.mark.asyncio
async def test_discover_agents_timeout():
    """Timeout should raise AgentDiscoveryError."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    with (
        patch("pinchwork.services.agent_discovery.httpx.AsyncClient", return_value=mock_client),
        pytest.raises(AgentDiscoveryError, match="timed out"),
    ):
        await discover_agents("test query")


@pytest.mark.asyncio
async def test_discover_agents_http_error():
    """HTTP errors should raise AgentDiscoveryError."""
    mock_response = MagicMock()
    mock_response.status_code = 503
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("503 error", request=MagicMock(), response=mock_response)
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with (
        patch("pinchwork.services.agent_discovery.httpx.AsyncClient", return_value=mock_client),
        pytest.raises(AgentDiscoveryError, match="HTTP error"),
    ):
        await discover_agents("test query")


@pytest.mark.asyncio
async def test_discover_agents_empty_results():
    """Empty results should return an empty agents list without error."""
    mock_response = MagicMock()
    mock_response.json.return_value = EMPTY_AGENTINDEX_RESPONSE
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("pinchwork.services.agent_discovery.httpx.AsyncClient", return_value=mock_client):
        result = await discover_agents("xyzzy-nonexistent-12345")

    assert result["count"] == 0
    assert result["agents"] == []


# ---------------------------------------------------------------------------
# API endpoint tests: /v1/discover (mocked HTTP)
# ---------------------------------------------------------------------------
# A2A discovery mode tests (intent=discover → search Pinchwork agents)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a2a_discovery_mode_returns_agents(client):
    """A2A message/send with intent=discover should search Pinchwork agents."""
    poster = await register_agent(client, "a2a-discovery-poster")
    # Register a worker so the search has something to find
    await client.post(
        "/v1/register", json={"name": "a2a-discovery-worker", "good_at": "code review Python"}
    )
    headers = auth_header(poster["api_key"])

    resp = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "disc-1",
            "method": "message/send",
            "params": {
                "message": {"parts": [{"type": "text", "text": "code review"}]},
                "metadata": {"intent": "discover", "limit": 5},
            },
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "result" in body
    result = body["result"]
    # Should have artifacts with discovery results
    artifacts = result.get("artifacts", [])
    assert len(artifacts) > 0
    data_part = next(
        (p for a in artifacts for p in a.get("parts", []) if p.get("type") == "data"), None
    )
    assert data_part is not None
    data = data_part["data"]
    assert data["search_method"] == "pinchwork_registry"
    assert "agents" in data
    assert "pinchwork.dev" in data["summary"]


@pytest.mark.asyncio
async def test_a2a_task_creation_still_works(client):
    """A2A message/send without intent=discover should still create a task."""
    poster = await register_agent(client, "a2a-task-poster")
    headers = auth_header(poster["api_key"])

    with patch("pinchwork.api.a2a.recruit_for_task", new_callable=AsyncMock):
        resp = await client.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "id": "task-1",
                "method": "message/send",
                "params": {
                    "message": {"parts": [{"type": "text", "text": "Write a Python script"}]},
                    "metadata": {"max_credits": 20},
                },
            },
            headers=headers,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "result" in body
    result = body["result"]
    assert result["status"]["state"] == "submitted"


# ---------------------------------------------------------------------------
# Recruiter service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recruit_for_task_sends_invites():
    """recruit_for_task should send A2A invites to matching external agents."""
    from pinchwork.services.agent_recruiter import recruit_for_task

    # Mock discover_agents to return a candidate with an A2A endpoint
    mock_result = {
        "agents": [
            {
                "id": "ext-agent-1",
                "name": "ExternalCoder",
                "protocols": ["a2a"],
                "trust_score": 80.0,
                "invocation": {"endpoint": "https://external-agent.example.com/a2a"},
            }
        ]
    }

    with (
        patch("pinchwork.services.agent_recruiter.discover_agents", return_value=mock_result),
        patch(
            "pinchwork.services.agent_recruiter._send_a2a_invite", return_value=True
        ) as mock_invite,
    ):
        count = await recruit_for_task("tk-test123", "Write a Python function", ["python"])

    assert count == 1
    mock_invite.assert_called_once()
    call_args = mock_invite.call_args
    assert call_args[0][0] == "https://external-agent.example.com/a2a"
    assert "tk-test123" in call_args[0][1]


@pytest.mark.asyncio
async def test_recruit_for_task_skips_low_trust():
    """Agents below MIN_TRUST_SCORE should not receive invites."""
    from pinchwork.services.agent_recruiter import recruit_for_task

    mock_result = {
        "agents": [
            {
                "id": "ext-low-trust",
                "name": "LowTrustAgent",
                "protocols": ["a2a"],
                "trust_score": 10.0,  # Below threshold
                "invocation": {"endpoint": "https://low-trust.example.com/a2a"},
            }
        ]
    }

    with (
        patch("pinchwork.services.agent_recruiter.discover_agents", return_value=mock_result),
        patch("pinchwork.services.agent_recruiter._send_a2a_invite") as mock_invite,
    ):
        count = await recruit_for_task("tk-low", "test task", None)

    assert count == 0
    mock_invite.assert_not_called()


@pytest.mark.asyncio
async def test_recruit_for_task_skips_no_a2a_endpoint():
    """Agents without A2A endpoints should be skipped."""
    from pinchwork.services.agent_recruiter import recruit_for_task

    mock_result = {
        "agents": [
            {
                "id": "ext-no-a2a",
                "name": "RestOnlyAgent",
                "protocols": ["rest"],  # No a2a
                "trust_score": 90.0,
                "invocation": {"endpoint": "https://rest-only.example.com/api"},
            }
        ]
    }

    with (
        patch("pinchwork.services.agent_recruiter.discover_agents", return_value=mock_result),
        patch("pinchwork.services.agent_recruiter._send_a2a_invite") as mock_invite,
    ):
        count = await recruit_for_task("tk-noapi", "test task", None)

    assert count == 0
    mock_invite.assert_not_called()


@pytest.mark.asyncio
async def test_recruit_for_task_handles_agentindex_error():
    """AgentDiscoveryError from AgentIndex should be handled gracefully."""
    from pinchwork.services.agent_discovery import AgentDiscoveryError
    from pinchwork.services.agent_recruiter import recruit_for_task

    with patch(
        "pinchwork.services.agent_recruiter.discover_agents",
        side_effect=AgentDiscoveryError("timeout"),
    ):
        count = await recruit_for_task("tk-err", "test task", None)

    assert count == 0  # No invites, no crash


# ---------------------------------------------------------------------------
# LIVE integration test against actual AgentIndex API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_live_agentindex_coding_agent():
    """LIVE: Query AgentIndex for a coding agent and verify real results.

    This test hits https://api.agentcrawl.dev/a2a directly.
    Run with: pytest -m integration tests/test_agent_discovery.py -v
    """
    result = await discover_agents("find me a coding agent", category="coding", limit=5)

    # The API should return a successful (possibly empty) response
    assert isinstance(result, dict)
    assert "agents" in result
    assert "count" in result
    assert "search_method" in result
    assert "summary" in result

    # We got a real response — verify structure
    agents = result["agents"]
    assert isinstance(agents, list)
    assert len(agents) <= 5  # Limit was applied

    # If agents were found, verify their structure
    if agents:
        agent = agents[0]
        assert "id" in agent
        assert "name" in agent
        # At least one of these should be present in a real result
        has_useful_data = any(
            agent.get(field) for field in ["description", "capabilities", "category", "source_url"]
        )
        assert has_useful_data, f"Agent has no useful data: {agent}"

    # Summary should be a non-empty string
    assert isinstance(result["summary"], str)
    assert len(result["summary"]) > 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_live_agentindex_nonexistent_query():
    """LIVE: Query AgentIndex with a nonsense query — should return 0 results gracefully."""
    result = await discover_agents("xyzzy-nonexistent-agent-12345xyz", limit=5)

    assert isinstance(result, dict)
    assert result["count"] == 0
    assert result["agents"] == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_live_agentindex_response_time():
    """LIVE: AgentIndex should respond within 30 seconds."""
    import time

    start = time.monotonic()
    result = await discover_agents("research agent", limit=3)
    elapsed = time.monotonic() - start

    assert elapsed < 30.0, f"AgentIndex took too long: {elapsed:.1f}s"
    assert isinstance(result, dict)
