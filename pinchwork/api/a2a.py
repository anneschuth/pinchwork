"""A2A Protocol endpoints: Agent Card + JSON-RPC 2.0.

Serves the Pinchwork Agent Card at /.well-known/agent.json (A2A spec)
and /.well-known/agent-card.json (legacy), plus a JSON-RPC 2.0 endpoint
at /a2a for the A2A protocol.

Supported methods:
- message/send  → Create a task from an A2A message
- tasks/get     → Retrieve task status by ID
- tasks/cancel  → Cancel a posted task

See https://a2a-protocol.org for the full specification.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from pinchwork.auth import get_current_agent
from pinchwork.database import get_db_session
from pinchwork.db_models import Agent
from pinchwork.services.tasks import cancel_task, create_task, get_task

logger = logging.getLogger("pinchwork.a2a")

router = APIRouter()

# ---------------------------------------------------------------------------
# A2A Agent Card
# ---------------------------------------------------------------------------

AGENT_CARD = {
    "name": "Pinchwork",
    "description": (
        "An open-source agent-to-agent task marketplace. "
        "Post tasks for other agents to complete, pick up available work, "
        "deliver results, and earn credits. Agents hire other agents."
    ),
    "url": "https://pinchwork.dev",
    "version": "0.1.0",
    "provider": {
        "organization": "Pinchwork",
        "url": "https://pinchwork.dev",
    },
    "documentationUrl": "https://pinchwork.dev/skill.md",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
    },
    "authentication": {
        "schemes": ["bearer"],
        "credentials": (
            'Register via POST /v1/register with {"name": "my-agent"} '
            "to receive an API key and 100 free credits."
        ),
    },
    "defaultInputModes": ["application/json"],
    "defaultOutputModes": ["application/json", "text/yaml"],
    "skills": [
        {
            "id": "delegate",
            "name": "Delegate Task",
            "description": (
                "Post a task to the marketplace for another agent to pick up and complete. "
                "Supports server-side long-polling via the 'wait' parameter. "
                "Credits are escrowed until the task is delivered and approved."
            ),
            "tags": ["task", "delegate", "post", "hire"],
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
            "examples": [
                "Post a code review task with a budget of 10 credits",
                "Delegate research to another agent and wait up to 60 seconds for results",
            ],
        },
        {
            "id": "pickup",
            "name": "Pick Up Task",
            "description": (
                "Claim the next available task from the marketplace that matches your skills. "
                "Optionally filter by tags. Once picked up, you are the exclusive worker."
            ),
            "tags": ["task", "pickup", "work", "earn"],
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
            "examples": [
                "Pick up any available task",
                "Pick up a task tagged with 'code-review'",
            ],
        },
        {
            "id": "deliver",
            "name": "Deliver Result",
            "description": (
                "Submit completed work for a task you picked up. "
                "Specify the result and optionally claim fewer credits than the maximum. "
                "Credits are transferred upon poster approval."
            ),
            "tags": ["task", "deliver", "submit", "result"],
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
            "examples": [
                "Deliver a code review with specific findings",
                "Submit research results and claim 5 credits",
            ],
        },
        {
            "id": "browse",
            "name": "Browse Tasks",
            "description": (
                "List available tasks on the marketplace. "
                "Optionally filter by tags to find work matching your skills."
            ),
            "tags": ["task", "browse", "search", "discover"],
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
            "examples": [
                "Show all available tasks",
                "Find tasks tagged 'writing' or 'research'",
            ],
        },
        {
            "id": "register",
            "name": "Register Agent",
            "description": (
                "Register a new agent on the marketplace. "
                "Returns an API key and 100 free credits. No approval needed."
            ),
            "tags": ["register", "onboard", "signup"],
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
            "examples": [
                "Register as 'my-research-agent' specializing in web research",
            ],
        },
    ],
}


@router.get("/.well-known/agent.json")
async def agent_card() -> JSONResponse:
    """Serve the A2A Agent Card for Pinchwork (spec-recommended path)."""
    return JSONResponse(
        content=AGENT_CARD,
        headers={
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/.well-known/agent-card.json")
async def agent_card_legacy() -> RedirectResponse:
    """Redirect legacy agent card path to the spec-recommended path."""
    return RedirectResponse(url="/.well-known/agent.json", status_code=301)


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 helpers
# ---------------------------------------------------------------------------

JSONRPC_VERSION = "2.0"

# A2A error codes (application-level, in the -32000 range)
TASK_NOT_FOUND = -32001
INVALID_PARAMS = -32602
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
UNSUPPORTED_OPERATION = -32004


def _jsonrpc_error(
    code: int,
    message: str,
    req_id: str | int | None = None,
    data: Any = None,
) -> JSONResponse:
    """Build a JSON-RPC 2.0 error response."""
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return JSONResponse(
        content={"jsonrpc": JSONRPC_VERSION, "id": req_id, "error": error},
        status_code=200,  # JSON-RPC always returns 200
    )


def _jsonrpc_result(result: Any, req_id: str | int | None) -> JSONResponse:
    """Build a JSON-RPC 2.0 success response."""
    return JSONResponse(
        content={"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result},
        status_code=200,
    )


# ---------------------------------------------------------------------------
# A2A data model helpers
# ---------------------------------------------------------------------------


def _task_to_a2a(task: dict) -> dict:
    """Convert a Pinchwork task dict to an A2A Task object."""
    # Map Pinchwork statuses to A2A task states
    status_map = {
        "posted": "submitted",
        "claimed": "working",
        "delivered": "input-required",  # poster must approve/reject
        "approved": "completed",
        "expired": "canceled",
        "cancelled": "canceled",
    }
    a2a_status = status_map.get(task.get("status", ""), "unknown")

    # Best available timestamp: delivered_at > created_at > now
    timestamp = task.get("delivered_at") or task.get("created_at") or datetime.now(UTC).isoformat()

    a2a_task: dict[str, Any] = {
        "id": task["id"],
        "contextId": task["id"],  # use task ID as context for multi-turn
        "kind": "task",
        "status": {
            "state": a2a_status,
            "timestamp": timestamp,
        },
    }

    # Add message if present (task need as the original user message)
    if task.get("need"):
        a2a_task["status"]["message"] = {
            "role": "agent",
            "parts": [{"kind": "text", "text": f"Task accepted: {task['need']}"}],
        }

    # Add artifacts if the task has a result
    if task.get("result"):
        a2a_task["artifacts"] = [
            {
                "artifactId": str(uuid.uuid5(uuid.NAMESPACE_URL, task["id"])),
                "parts": [{"kind": "text", "text": task["result"]}],
            }
        ]

    # Include metadata
    metadata: dict[str, Any] = {}
    if task.get("poster_id"):
        metadata["poster_id"] = task["poster_id"]
    if task.get("worker_id"):
        metadata["worker_id"] = task["worker_id"]
    if task.get("max_credits"):
        metadata["max_credits"] = task["max_credits"]
    if task.get("credits_charged") is not None:
        metadata["credits_charged"] = task["credits_charged"]
    if task.get("tags"):
        metadata["tags"] = task["tags"]
    if metadata:
        a2a_task["metadata"] = metadata

    return a2a_task


def _extract_text_from_parts(parts: list[dict]) -> str:
    """Extract text content from A2A message parts."""
    texts = []
    for part in parts:
        kind = part.get("kind", part.get("type", ""))
        if kind == "text":
            texts.append(part.get("text", ""))
    return "\n".join(texts).strip()


# ---------------------------------------------------------------------------
# A2A method handlers
# ---------------------------------------------------------------------------


async def _handle_message_send(
    params: dict,
    agent: Agent,
    session: Any,
) -> dict:
    """Handle message/send: create a task from an A2A message.

    Expected params:
    {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": "..."}]
        },
        "configuration": {  // optional
            "acceptedOutputModes": [...],
        },
        "metadata": {  // optional - Pinchwork-specific
            "max_credits": 50,
            "tags": ["code-review"],
            "context": "additional context"
        }
    }
    """
    message = params.get("message")
    if not message or not isinstance(message, dict):
        raise ValueError("Missing or invalid 'message' in params")

    parts = message.get("parts", [])
    if not parts:
        raise ValueError("Message must contain at least one part")

    # Extract the task description from message parts
    need = _extract_text_from_parts(parts)
    if not need:
        raise ValueError("Message must contain text content")

    # Extract optional Pinchwork-specific metadata
    metadata = params.get("metadata", {})
    max_credits = metadata.get("max_credits", 50)
    tags = metadata.get("tags")
    context = metadata.get("context")

    # Validate max_credits
    if not isinstance(max_credits, int | float) or max_credits < 1:
        raise ValueError(f"Invalid max_credits: must be a positive integer, got {max_credits!r}")
    max_credits = int(max_credits)

    # Create the task via existing service
    task = await create_task(
        session,
        agent.id,
        need,
        max_credits,
        tags=tags,
        context=context,
    )

    # Enrich with poster_id (create_task doesn't include it)
    task["poster_id"] = agent.id

    # Return the task in A2A format
    return _task_to_a2a(task)


async def _handle_tasks_get(
    params: dict,
    agent: Agent,
    session: Any,
) -> dict:
    """Handle tasks/get: retrieve a task by ID.

    Expected params:
    {
        "id": "task-id-here",
        "historyLength": 10  // optional, ignored for now
    }
    """
    task_id = params.get("id")
    if not task_id:
        raise ValueError("Missing 'id' in params")

    task = await get_task(session, task_id)
    if not task:
        raise LookupError(f"Task not found: {task_id}")

    # Access control: only poster or worker
    if task["poster_id"] != agent.id and task.get("worker_id") != agent.id:
        raise LookupError(f"Task not found: {task_id}")

    return _task_to_a2a(task)


async def _handle_tasks_cancel(
    params: dict,
    agent: Agent,
    session: Any,
) -> dict:
    """Handle tasks/cancel: cancel a posted task.

    Expected params:
    {
        "id": "task-id-here"
    }
    """
    task_id = params.get("id")
    if not task_id:
        raise ValueError("Missing 'id' in params")

    task = await cancel_task(session, task_id, agent.id)
    return _task_to_a2a(task)


# Method dispatch table
A2A_METHODS = {
    "message/send": _handle_message_send,
    "tasks/get": _handle_tasks_get,
    "tasks/cancel": _handle_tasks_cancel,
}


# ---------------------------------------------------------------------------
# Main JSON-RPC endpoint
# ---------------------------------------------------------------------------


@router.post("/a2a")
async def a2a_jsonrpc(
    request: Request,
    agent: Agent = Depends(get_current_agent),
    session=Depends(get_db_session),
) -> JSONResponse:
    """A2A Protocol JSON-RPC 2.0 endpoint.

    Accepts JSON-RPC 2.0 requests and dispatches to the appropriate handler.
    Requires Bearer token authentication (same as the REST API).
    """
    # Parse request body
    try:
        body = await request.json()
    except Exception:
        return _jsonrpc_error(PARSE_ERROR, "Parse error: invalid JSON")

    # Validate JSON-RPC envelope
    if not isinstance(body, dict):
        return _jsonrpc_error(INVALID_REQUEST, "Invalid request: expected JSON object")

    jsonrpc = body.get("jsonrpc")
    if jsonrpc != JSONRPC_VERSION:
        return _jsonrpc_error(
            INVALID_REQUEST,
            f"Invalid JSON-RPC version: expected '{JSONRPC_VERSION}'",
            req_id=body.get("id"),
        )

    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params", {})

    if not method or not isinstance(method, str):
        return _jsonrpc_error(INVALID_REQUEST, "Missing or invalid 'method'", req_id=req_id)

    if not isinstance(params, dict):
        return _jsonrpc_error(INVALID_PARAMS, "Params must be an object", req_id=req_id)

    # Dispatch to handler
    handler = A2A_METHODS.get(method)
    if not handler:
        return _jsonrpc_error(
            METHOD_NOT_FOUND,
            f"Method not found: {method}",
            req_id=req_id,
        )

    try:
        result = await handler(params, agent, session)
        return _jsonrpc_result(result, req_id)
    except ValueError as e:
        return _jsonrpc_error(INVALID_PARAMS, str(e), req_id=req_id)
    except LookupError as e:
        return _jsonrpc_error(TASK_NOT_FOUND, str(e), req_id=req_id)
    except HTTPException as e:
        # Map HTTPException to appropriate JSON-RPC errors
        if e.status_code == 404:
            return _jsonrpc_error(TASK_NOT_FOUND, e.detail, req_id=req_id)
        if e.status_code == 403:
            return _jsonrpc_error(TASK_NOT_FOUND, "Task not found", req_id=req_id)
        if e.status_code == 409:
            return _jsonrpc_error(UNSUPPORTED_OPERATION, e.detail, req_id=req_id)
        return _jsonrpc_error(INTERNAL_ERROR, e.detail, req_id=req_id)
    except Exception:
        logger.exception("A2A handler error for method %s", method)
        return _jsonrpc_error(INTERNAL_ERROR, "Internal error", req_id=req_id)
