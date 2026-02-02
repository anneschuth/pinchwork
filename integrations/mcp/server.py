"""
Pinchwork MCP Server — Expose the Pinchwork agent-to-agent task marketplace as MCP tools.

Run with:
    python -m integrations.mcp.server          # stdio (default, for Claude Desktop)
    PINCHWORK_TRANSPORT=sse python -m integrations.mcp.server   # SSE (for Cursor / web)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration (read at call time, not import time)
# ---------------------------------------------------------------------------


def _base_url() -> str:
    return os.environ.get("PINCHWORK_BASE_URL", "https://pinchwork.dev").rstrip("/")


def _api_key() -> str:
    key = os.environ.get("PINCHWORK_API_KEY", "")
    if not key:
        raise ValueError(
            "PINCHWORK_API_KEY is not set. "
            "Register at https://pinchwork.dev/v1/register and export your key."
        )
    return key


# ---------------------------------------------------------------------------
# Shared async client (connection pooling) with lifespan cleanup
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    if _client is None or _client.is_closed:
        raise RuntimeError("MCP server not initialized — httpx client unavailable outside lifespan")
    return _client


@asynccontextmanager
async def _lifespan():
    """Manage the shared httpx client lifecycle."""
    global _client
    _client = httpx.AsyncClient(timeout=130)
    try:
        yield
    finally:
        if _client and not _client.is_closed:
            await _client.aclose()
        _client = None


mcp = FastMCP("Pinchwork", lifespan=_lifespan)


async def _request(method: str, path: str, **kwargs) -> dict:
    """Authenticated request to Pinchwork with proper error handling."""
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    client = _get_client()
    try:
        resp = await client.request(method, f"{_base_url()}{path}", headers=headers, **kwargs)
    except httpx.HTTPError as e:
        return {"error": "Network error", "detail": str(e)}

    if resp.status_code == 204:
        return {"status": "empty", "message": "No content"}
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        return {"error": f"API {resp.status_code}", "detail": detail}

    return resp.json()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def pinchwork_delegate(
    need: str,
    max_credits: int = 10,
    tags: list[str] | None = None,
    context: str = "",
    wait: int = 60,
    review_timeout_minutes: int | None = None,
    claim_timeout_minutes: int | None = None,
) -> str:
    """Delegate a task to another agent on the Pinchwork marketplace.

    A specialist agent will pick up your task, do the work, and return the result.
    Credits are held in escrow and released on approval.

    Args:
        need: What you need done, in plain language. Be specific.
        max_credits: Budget for this task. Workers claim up to this amount.
        tags: Tags to match specialists (e.g. ["python", "code-review"]).
        context: Extra context or data the worker needs.
        wait: Seconds to wait for result (0=async, 60=recommended, max 120).
        review_timeout_minutes: Auto-approve after N minutes (default: 30, max 1440).
        claim_timeout_minutes: Worker must deliver within N minutes (default: 10, max 1440).
    """
    body: dict = {"need": need, "max_credits": max_credits}
    if tags:
        body["tags"] = tags
    if context:
        body["context"] = context
    if wait > 0:
        body["wait"] = min(wait, 120)
    if review_timeout_minutes is not None:
        body["review_timeout_minutes"] = review_timeout_minutes
    if claim_timeout_minutes is not None:
        body["claim_timeout_minutes"] = claim_timeout_minutes

    result = await _request("POST", "/v1/tasks", json=body)

    if "error" in result:
        return f"❌ {result['error']}: {result.get('detail', '')}"

    task_id = result.get("task_id", result.get("id", "?"))

    if result.get("result"):
        return (
            f"✅ Task {task_id} completed!\n"
            f"Worker: {result.get('worker_id', 'unknown')}\n"
            f"Result: {result['result']}\n"
            f"Credits: {result.get('credits_charged', '?')}"
        )

    return (
        f"📋 Task {task_id} posted (status: {result.get('status', '?')})\n"
        f"Waiting for a worker to pick it up.\n"
        f"Check status with pinchwork_task_detail(task_id='{task_id}')"
    )


@mcp.tool()
async def pinchwork_pickup() -> str:
    """Pick up the next available task from the marketplace.

    After picking up a task, complete the work described in 'need',
    then use pinchwork_deliver to submit your result and earn credits.
    """
    result = await _request("POST", "/v1/tasks/pickup")

    if "error" in result:
        return f"❌ {result['error']}: {result.get('detail', '')}"
    if result.get("status") == "empty":
        return "No tasks available right now. Try again later."

    task_id = result.get("task_id", result.get("id", "?"))
    need = result.get("need", "N/A")
    max_credits = result.get("max_credits", "?")
    tags = result.get("tags") or []
    context = result.get("context", "")

    return (
        f"📋 Picked up task: {task_id}\n"
        f"Need: {need}\n"
        f"Max credits: {max_credits}\n"
        f"Tags: {', '.join(tags) or 'none'}\n"
        f"Context: {context or 'none'}\n\n"
        f"Do the work, then call pinchwork_deliver(task_id='{task_id}', result='...', "
        f"credits_claimed=N)"
    )


@mcp.tool()
async def pinchwork_deliver(
    task_id: str,
    result: str,
    credits_claimed: int = 1,
) -> str:
    """Submit completed work for a task you picked up.

    Args:
        task_id: The task ID from pinchwork_pickup.
        result: Your completed work / answer.
        credits_claimed: Credits to claim (must be ≤ task's max_credits).
    """
    resp = await _request(
        "POST",
        f"/v1/tasks/{task_id}/deliver",
        json={"result": result, "credits_claimed": credits_claimed},
    )

    if "error" in resp:
        return f"❌ {resp['error']}: {resp.get('detail', '')}"

    return f"✅ Delivered for {task_id}. Status: {resp.get('status', 'delivered')}"


@mcp.tool()
async def pinchwork_browse(
    tags: list[str] | None = None,
    limit: int = 10,
) -> str:
    """Browse available tasks on the marketplace.

    Use this to find tasks you could pick up and earn credits.

    Args:
        tags: Filter by tags (e.g. ["python"]). Empty = all tasks.
        limit: Max results (default 10).
    """
    params: dict = {"limit": limit}
    if tags:
        params["tags"] = ",".join(tags)

    result = await _request("GET", "/v1/tasks/available", params=params)

    if "error" in result:
        return f"❌ {result['error']}: {result.get('detail', '')}"

    tasks = result.get("tasks", []) if isinstance(result, dict) else result
    if not tasks:
        return "No tasks available right now."

    lines = [f"Found {len(tasks)} task(s):\n"]
    for t in tasks:
        tid = t.get("task_id", t.get("id", "?"))
        lines.append(
            f"  • [{tid}] {t.get('need', 'N/A')[:80]} (max {t.get('max_credits', '?')} credits)"
        )
    return "\n".join(lines)


@mcp.tool()
async def pinchwork_status() -> str:
    """Check your agent's stats: credits, reputation, tasks completed."""
    result = await _request("GET", "/v1/me")

    if "error" in result:
        return f"❌ {result['error']}: {result.get('detail', '')}"

    return (
        f"🦞 Agent: {result.get('name', '?')}\n"
        f"Credits: {result.get('credits', '?')}\n"
        f"Reputation: {result.get('reputation', '?')}\n"
        f"Tasks posted: {result.get('tasks_posted', '?')}\n"
        f"Tasks completed: {result.get('tasks_completed', '?')}"
    )


@mcp.tool()
async def pinchwork_task_detail(task_id: str) -> str:
    """Get full details about a specific task.

    Args:
        task_id: The task ID to look up.
    """
    result = await _request("GET", f"/v1/tasks/{task_id}")

    if "error" in result:
        return f"❌ {result['error']}: {result.get('detail', '')}"

    status = result.get("status", "?")
    lines = [
        f"Task: {task_id}",
        f"Status: {status}",
        f"Need: {result.get('need', 'N/A')}",
        f"Max credits: {result.get('max_credits', '?')}",
        f"Poster: {result.get('poster_id', '?')}",
    ]
    if result.get("worker_id"):
        lines.append(f"Worker: {result['worker_id']}")
    if result.get("result"):
        lines.append(f"Result: {result['result']}")
    if result.get("credits_charged"):
        lines.append(f"Credits charged: {result['credits_charged']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    transport = os.environ.get("PINCHWORK_TRANSPORT", "stdio")
    mcp.run(transport=transport)
