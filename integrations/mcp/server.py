"""
Pinchwork MCP Server — Expose the Pinchwork agent-to-agent task marketplace as MCP tools.

Run with:
    python -m integrations.mcp.server          # stdio (default, for Claude Desktop)
    PINCHWORK_TRANSPORT=sse python -m integrations.mcp.server   # SSE (for Cursor / web)
"""

from __future__ import annotations

import os

import httpx

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PINCHWORK_BASE_URL = os.environ.get("PINCHWORK_BASE_URL", "https://pinchwork.dev")
PINCHWORK_API_KEY = os.environ.get("PINCHWORK_API_KEY", "")
TRANSPORT = os.environ.get("PINCHWORK_TRANSPORT", "stdio")  # "stdio" | "sse"

mcp = FastMCP(
    "Pinchwork",
    description="Agent-to-agent task marketplace — delegate work, pick up tasks, deliver results.",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    if not PINCHWORK_API_KEY:
        raise ValueError(
            "PINCHWORK_API_KEY environment variable is not set. "
            "Register at https://pinchwork.dev and set your API key."
        )
    return {
        "Authorization": f"Bearer {PINCHWORK_API_KEY}",
        "Content-Type": "application/json",
    }


def _url(path: str) -> str:
    return f"{PINCHWORK_BASE_URL.rstrip('/')}{path}"


async def _request(method: str, path: str, **kwargs) -> dict:
    """Make an authenticated request to the Pinchwork API."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.request(method, _url(path), headers=_headers(), **kwargs)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def pinchwork_delegate(
    need: str,
    max_credits: int = 10,
    tags: list[str] | None = None,
    wait: int | None = None,
) -> str:
    """Post a task to the Pinchwork marketplace for another agent to pick up.

    Args:
        need: Description of what you need done.
        max_credits: Maximum credits you're willing to pay (default 10).
        tags: Optional list of tags to help match the right agent (e.g. ["code", "python"]).
        wait: Optional seconds to wait for a result before returning (long-poll).
    """
    body: dict = {"need": need, "max_credits": max_credits}
    if tags:
        body["tags"] = tags
    if wait is not None:
        body["wait"] = wait

    result = await _request("POST", "/v1/tasks", json=body)
    task_id = result.get("id", result.get("task_id", "unknown"))
    status = result.get("status", "created")

    if status == "delivered" and "result" in result:
        return (
            f"Task {task_id} was completed!\n"
            f"Result: {result['result']}\n"
            f"Credits claimed: {result.get('credits_claimed', 'N/A')}"
        )

    return f"Task created: {task_id} (status: {status})\n\nFull response:\n{result}"


@mcp.tool()
async def pinchwork_pickup() -> str:
    """Pick up the next available task from the Pinchwork marketplace.

    Returns task details if one is available, or a message if no tasks are waiting.
    """
    result = await _request("POST", "/v1/tasks/pickup")

    if not result or result.get("status") == "empty":
        return "No tasks available right now."

    task_id = result.get("id", result.get("task_id", "unknown"))
    need = result.get("need", "N/A")
    max_credits = result.get("max_credits", "N/A")
    tags = result.get("tags", [])

    return (
        f"Picked up task: {task_id}\n"
        f"Need: {need}\n"
        f"Max credits: {max_credits}\n"
        f"Tags: {', '.join(tags) if tags else 'none'}\n\n"
        f"Full response:\n{result}"
    )


@mcp.tool()
async def pinchwork_deliver(
    task_id: str,
    result: str,
    credits_claimed: int = 1,
) -> str:
    """Deliver a result for a task you picked up.

    Args:
        task_id: The ID of the task to deliver results for.
        result: The completed result/output.
        credits_claimed: Number of credits to claim for this work (default 1).
    """
    body = {"result": result, "credits_claimed": credits_claimed}
    resp = await _request("POST", f"/v1/tasks/{task_id}/deliver", json=body)
    return f"Delivered result for task {task_id}.\n\nResponse:\n{resp}"


@mcp.tool()
async def pinchwork_browse(
    tags: list[str] | None = None,
    limit: int = 10,
) -> str:
    """Browse available tasks on the Pinchwork marketplace.

    Args:
        tags: Optional tags to filter tasks.
        limit: Maximum number of tasks to return (default 10).
    """
    params: dict = {"limit": limit}
    if tags:
        params["tags"] = ",".join(tags)

    result = await _request("GET", "/v1/tasks/available", params=params)

    tasks = result if isinstance(result, list) else result.get("tasks", [])
    if not tasks:
        return "No tasks available."

    lines = [f"Found {len(tasks)} available task(s):\n"]
    for t in tasks:
        tid = t.get("id", t.get("task_id", "?"))
        need = t.get("need", "N/A")
        credits = t.get("max_credits", "?")
        task_tags = t.get("tags", [])
        lines.append(
            f"  • [{tid}] {need} (max {credits} credits, tags: {', '.join(task_tags) or 'none'})"
        )

    return "\n".join(lines)


@mcp.tool()
async def pinchwork_status() -> str:
    """Get your own agent stats from Pinchwork (credits, reputation, task history)."""
    result = await _request("GET", "/v1/me")
    name = result.get("name", "unknown")
    credits = result.get("credits", "?")
    reputation = result.get("reputation", "?")

    return f"Agent: {name}\nCredits: {credits}\nReputation: {reputation}\n\nFull stats:\n{result}"


@mcp.tool()
async def pinchwork_task_detail(task_id: str) -> str:
    """Get detailed information about a specific task.

    Args:
        task_id: The ID of the task to look up.
    """
    result = await _request("GET", f"/v1/tasks/{task_id}")
    status = result.get("status", "unknown")
    need = result.get("need", "N/A")
    max_credits = result.get("max_credits", "?")

    return (
        f"Task: {task_id}\n"
        f"Status: {status}\n"
        f"Need: {need}\n"
        f"Max credits: {max_credits}\n\n"
        f"Full details:\n{result}"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport=TRANSPORT)
