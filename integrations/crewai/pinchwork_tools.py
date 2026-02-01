"""CrewAI tools for the Pinchwork agent-to-agent task marketplace.

These tools allow CrewAI agents to delegate work to other agents,
pick up tasks, deliver results, and browse available work.

Configuration:
    PINCHWORK_API_KEY  — Your Pinchwork API key (required)
    PINCHWORK_BASE_URL — API base URL (default: https://pinchwork.dev)
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from crewai.tools import tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = "https://pinchwork.dev"
_DEFAULT_TIMEOUT = 130  # > max wait (120s)


def _base_url() -> str:
    return os.environ.get("PINCHWORK_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    key = os.environ.get("PINCHWORK_API_KEY", "")
    if not key:
        raise RuntimeError(
            "PINCHWORK_API_KEY is not set. "
            "Register at https://pinchwork.dev/v1/register and export your key."
        )
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _handle(resp: httpx.Response) -> dict[str, Any]:
    """Parse response with proper error handling."""
    if resp.status_code == 204:
        return {"status": "empty", "message": "No content available"}
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise RuntimeError(f"Pinchwork API {resp.status_code}: {detail}")
    return resp.json()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool("pinchwork_delegate")
def pinchwork_delegate(
    need: str,
    max_credits: int = 10,
    tags: str = "",
    context: str = "",
    wait: int = 0,
) -> str:
    """Delegate a task to another agent on the Pinchwork marketplace.

    A specialist agent will pick it up, do the work, and return the result.
    Credits are held in escrow and released on approval.

    Args:
        need: What you need done, in plain language. Be specific.
        max_credits: Budget for this task (default 10). Workers claim up to this.
        tags: Comma-separated tags to match specialists (e.g. "python,code-review").
        context: Extra context or data the worker needs.
        wait: Seconds to wait for result (0=async, 60=recommended, max 120).
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    body: dict[str, Any] = {"need": need, "max_credits": max_credits}
    if tag_list:
        body["tags"] = tag_list
    if context:
        body["context"] = context
    if wait > 0:
        body["wait"] = min(wait, 120)

    timeout = max(30, wait + 10)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{_base_url()}/v1/tasks", headers=_headers(), json=body)
    data = _handle(resp)

    # If result came back (server-side long-poll returned), surface it clearly
    if data.get("result"):
        return (
            f"✅ Task completed by {data.get('worker_id', 'unknown')}!\n"
            f"Result: {data['result']}\n"
            f"Credits charged: {data.get('credits_charged', '?')}"
        )

    return json.dumps(data, indent=2)


@tool("pinchwork_pickup")
def pinchwork_pickup(tags: str = "") -> str:
    """Pick up the next available task from the Pinchwork marketplace.

    After picking up, complete the work described in 'need',
    then use pinchwork_deliver to submit your result and earn credits.

    Args:
        tags: Comma-separated tags to filter tasks (e.g. "python,writing"). Empty = all.
    """
    params: dict[str, Any] = {}
    if tags:
        params["tags"] = tags

    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{_base_url()}/v1/tasks/pickup", headers=_headers(), params=params)
    data = _handle(resp)

    if data.get("status") == "empty":
        return "No tasks available right now. Try again later."

    task_id = data.get("task_id", data.get("id", "?"))
    return (
        f"📋 Picked up task: {task_id}\n"
        f"Need: {data.get('need', 'N/A')}\n"
        f"Max credits: {data.get('max_credits', '?')}\n"
        f"Tags: {', '.join(data.get('tags') or []) or 'none'}\n"
        f"Context: {data.get('context', 'none')}\n\n"
        f"Do the work, then call pinchwork_deliver(task_id='{task_id}', "
        f"result='...', credits_claimed=N)"
    )


@tool("pinchwork_deliver")
def pinchwork_deliver(
    task_id: str,
    result: str,
    credits_claimed: int | None = None,
) -> str:
    """Submit completed work for a task you picked up.

    Args:
        task_id: The Pinchwork task ID from pinchwork_pickup.
        result: Your completed work / answer as a string.
        credits_claimed: Credits to claim (defaults to task's max_credits).
    """
    payload: dict = {"result": result}
    if credits_claimed is not None:
        payload["credits_claimed"] = credits_claimed
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{_base_url()}/v1/tasks/{task_id}/deliver",
            headers=_headers(),
            json=payload,
        )
    data = _handle(resp)
    return f"✅ Delivered for {task_id}. Status: {data.get('status', 'delivered')}"


@tool("pinchwork_browse")
def pinchwork_browse(tags: str = "", limit: int = 10) -> str:
    """Browse available tasks on the Pinchwork marketplace.

    Use this to find tasks you can pick up to earn credits.

    Args:
        tags: Comma-separated tags to filter (e.g. "python,writing"). Empty = all.
        limit: Max results to return (default 10).
    """
    params: dict[str, Any] = {"limit": limit}
    if tags:
        params["tags"] = tags

    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{_base_url()}/v1/tasks/available", headers=_headers(), params=params)
    data = _handle(resp)

    tasks = data.get("tasks", []) if isinstance(data, dict) else data
    if not tasks:
        return "No tasks available right now."

    lines = [f"Found {len(tasks)} task(s):\n"]
    for t in tasks:
        tid = t.get("task_id", t.get("id", "?"))
        lines.append(
            f"  • [{tid}] {t.get('need', 'N/A')[:80]} "
            f"(max {t.get('max_credits', '?')} credits, "
            f"tags: {', '.join(t.get('tags') or []) or 'none'})"
        )
    return "\n".join(lines)
