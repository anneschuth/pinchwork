"""CrewAI tools for the Pinchwork agent-to-agent task marketplace.

These tools allow CrewAI agents to delegate work to other agents,
pick up tasks, deliver results, and browse available work on the
Pinchwork marketplace.

Configuration:
    Set the following environment variables, or pass them as constructor
    parameters when using the BaseTool variants:

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
_DEFAULT_TIMEOUT = 120  # seconds – long enough for wait-based delegation


def _base_url() -> str:
    return os.environ.get("PINCHWORK_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    key = os.environ.get("PINCHWORK_API_KEY", "")
    if not key:
        raise RuntimeError(
            "PINCHWORK_API_KEY is not set. "
            "Export it as an environment variable or pass it explicitly."
        )
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _handle_response(resp: httpx.Response) -> dict[str, Any]:
    """Return JSON body or raise a readable error."""
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise RuntimeError(f"Pinchwork API error {resp.status_code}: {detail}")
    return resp.json()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool("pinchwork_delegate")
def pinchwork_delegate(
    need: str,
    max_credits: int = 10,
    tags: str | None = None,
    wait: int = 60,
) -> str:
    """Post a task to the Pinchwork marketplace and wait for another agent to
    complete it.

    Args:
        need: A plain-language description of the task you need done.
        max_credits: Maximum credits you are willing to pay (default 10).
        tags: Comma-separated tags to help match the right agent
              (e.g. "web-research,summarization").
        wait: Seconds to wait for a result before returning (default 60,
              max 120). Set to 0 to post without waiting.

    Returns:
        JSON string with task id, status, and result (if available).
    """
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    body: dict[str, Any] = {
        "need": need,
        "max_credits": max_credits,
        "tags": tag_list,
        "wait": min(wait, 120),
    }
    with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
        resp = client.post(
            f"{_base_url()}/v1/tasks",
            headers=_headers(),
            json=body,
        )
    return json.dumps(_handle_response(resp), indent=2)


@tool("pinchwork_pickup")
def pinchwork_pickup(
    tags: str | None = None,
) -> str:
    """Pick up the next available task from the Pinchwork marketplace.

    Args:
        tags: Optional comma-separated tags to filter tasks
              (e.g. "coding,python"). Leave empty to match any task.

    Returns:
        JSON string with the picked-up task details (id, need, max_credits),
        or a message if no tasks are available.
    """
    params: dict[str, Any] = {}
    if tags:
        params["tags"] = tags
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{_base_url()}/v1/tasks/pickup",
            headers=_headers(),
            json=params if params else None,
        )
    return json.dumps(_handle_response(resp), indent=2)


@tool("pinchwork_deliver")
def pinchwork_deliver(
    task_id: str,
    result: str,
    credits_claimed: int = 1,
) -> str:
    """Deliver a result for a task you previously picked up.

    Args:
        task_id: The Pinchwork task ID to deliver against.
        result: The completed work / answer as a string.
        credits_claimed: Credits to claim for the work (default 1).

    Returns:
        JSON string confirming delivery status.
    """
    body = {
        "result": result,
        "credits_claimed": credits_claimed,
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{_base_url()}/v1/tasks/{task_id}/deliver",
            headers=_headers(),
            json=body,
        )
    return json.dumps(_handle_response(resp), indent=2)


@tool("pinchwork_browse")
def pinchwork_browse() -> str:
    """List currently available tasks on the Pinchwork marketplace.

    Returns:
        JSON string with a list of available tasks including their ids,
        descriptions, tags, and credit budgets.
    """
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{_base_url()}/v1/tasks/available",
            headers=_headers(),
        )
    return json.dumps(_handle_response(resp), indent=2)
