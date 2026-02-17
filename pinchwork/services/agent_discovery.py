"""Agent discovery service — queries AgentIndex via A2A protocol.

Sends JSON-RPC 2.0 requests to https://api.agentcrawl.dev/a2a and parses
the response into clean agent records.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

logger = logging.getLogger("pinchwork.agent_discovery")

AGENTINDEX_A2A_URL = "https://api.agentcrawl.dev/a2a"
DEFAULT_TIMEOUT = 30.0


class AgentDiscoveryError(Exception):
    """Raised when AgentIndex returns an error or unexpected response."""


def _build_jsonrpc_request(query: str, request_id: str | None = None) -> dict:
    """Build a JSON-RPC 2.0 message/send request for AgentIndex."""
    return {
        "jsonrpc": "2.0",
        "id": request_id or str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": query}],
            }
        },
    }


def _parse_agent(raw: dict) -> dict:
    """Extract clean agent fields from a raw AgentIndex agent record."""
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "description": raw.get("description"),
        "capabilities": raw.get("capabilities") or [],
        "category": raw.get("category"),
        "protocols": raw.get("protocols") or [],
        "source_url": raw.get("source_url"),
        "author": raw.get("author"),
        "stars": raw.get("stars"),
        "trust_score": raw.get("trust_score"),
        "quality_score": raw.get("quality_score"),
        "is_verified": raw.get("is_verified", False),
        "pricing": raw.get("pricing"),
    }


def _parse_response(data: dict) -> dict:
    """Parse the AgentIndex A2A response and extract agents + summary.

    Returns:
        {
            "query": str,
            "search_method": str,
            "count": int,
            "agents": list[dict],
            "summary": str,
        }
    """
    # Check for JSON-RPC error
    if "error" in data:
        err = data["error"]
        raise AgentDiscoveryError(
            f"AgentIndex error {err.get('code', '?')}: {err.get('message', 'Unknown error')}"
        )

    result = data.get("result")
    if not result:
        raise AgentDiscoveryError("AgentIndex returned no result")

    status = result.get("status", {})
    state = status.get("state")
    if state not in ("completed", None):
        raise AgentDiscoveryError(f"AgentIndex task in unexpected state: {state!r}")

    # Extract data from artifacts
    artifacts = result.get("artifacts", [])
    if not artifacts:
        # No agents found — return empty result
        return {
            "query": "",
            "search_method": "fts",
            "count": 0,
            "agents": [],
            "summary": "No agents found.",
        }

    summary_text = ""
    agent_data: dict[str, Any] = {}

    for artifact in artifacts:
        for part in artifact.get("parts", []):
            part_type = part.get("type", "")
            if part_type == "text":
                summary_text = part.get("text", "")
            elif part_type == "data":
                agent_data = part.get("data", {})

    agents_raw = agent_data.get("agents", [])
    agents = [_parse_agent(a) for a in agents_raw]

    return {
        "query": agent_data.get("query", ""),
        "search_method": agent_data.get("search_method", "fts"),
        "count": agent_data.get("count", len(agents)),
        "agents": agents,
        "summary": summary_text,
    }


async def discover_agents(
    query: str,
    category: str | None = None,
    limit: int = 10,
) -> dict:
    """Query AgentIndex for agents matching the query.

    Args:
        query: Natural language search query (e.g. "find me a code review agent")
        category: Optional category filter (appended to query if provided)
        limit: Maximum number of agents to return (applied client-side)

    Returns:
        {
            "query": str,
            "search_method": str,
            "count": int,              # total found before limit
            "agents": list[dict],      # up to `limit` agents
            "summary": str,            # human-readable summary from AgentIndex
        }

    Raises:
        AgentDiscoveryError: If AgentIndex returns an error or is unreachable.
    """
    # Build query string — optionally include category hint
    full_query = query
    if category:
        full_query = f"{query} category:{category}"

    payload = _build_jsonrpc_request(full_query)

    logger.info("Querying AgentIndex for: %r (category=%r, limit=%d)", query, category, limit)

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(
                AGENTINDEX_A2A_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise AgentDiscoveryError("AgentIndex request timed out") from exc
    except httpx.HTTPStatusError as exc:
        raise AgentDiscoveryError(f"AgentIndex HTTP error {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise AgentDiscoveryError(f"AgentIndex request failed: {exc}") from exc

    try:
        data = response.json()
    except Exception as exc:
        raise AgentDiscoveryError("AgentIndex returned invalid JSON") from exc

    parsed = _parse_response(data)

    # Apply limit client-side
    parsed["agents"] = parsed["agents"][:limit]

    return parsed
