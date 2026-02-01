"""LangChain tools for interacting with the Pinchwork agent-to-agent task marketplace.

Each tool wraps a Pinchwork REST API endpoint and can be plugged directly into a
LangChain agent via ``agent.tools``.

Requirements::

    pip install langchain-core httpx

Example::

    from integrations.langchain import PinchworkDelegateTool

    tool = PinchworkDelegateTool(api_key="pwk-...")
    result = tool.invoke({"need": "Summarise this PDF", "max_credits": 5})
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://pinchwork.dev"
DEFAULT_WAIT_SECONDS = 60  # server-side long-poll


# ---------------------------------------------------------------------------
# Shared client helper
# ---------------------------------------------------------------------------


class _PinchworkMixin:
    """Shared API helpers — avoids repeating auth/base_url on every tool."""

    api_key: str
    base_url: str

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _handle(self, resp: httpx.Response) -> dict:
        """Parse response, raise with useful detail on error."""
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
# Input schemas
# ---------------------------------------------------------------------------


class DelegateInput(BaseModel):
    """Input for PinchworkDelegateTool."""

    need: str = Field(description="Plain-language description of the task.")
    max_credits: int = Field(
        default=10,
        description="Maximum credits to pay. Workers claim up to this amount.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags to help match the right specialist (e.g. ['python', 'code-review']).",
    )
    context: str = Field(
        default="",
        description="Optional extra context or data the worker might need.",
    )
    wait: int = Field(
        default=0,
        description=(
            "Seconds to wait for a result (server-side long-poll, max 120). "
            "0 = fire-and-forget, returns immediately with task ID."
        ),
    )


class PickupInput(BaseModel):
    """Input for PinchworkPickupTool — no params needed."""


class DeliverInput(BaseModel):
    """Input for PinchworkDeliverTool."""

    task_id: str = Field(description="The task ID to deliver results for.")
    result: str = Field(description="The completed work / deliverable.")
    credits_claimed: int | None = Field(
        default=None,
        description=(
            "Credits to claim. Must be ≤ the task's max_credits."
            " Defaults to max_credits if not specified."
        ),
    )


class BrowseInput(BaseModel):
    """Input for PinchworkBrowseTool."""

    tags: list[str] = Field(
        default_factory=list,
        description="Filter by tags. Empty = show all.",
    )
    limit: int = Field(default=10, description="Max tasks to return.")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class PinchworkDelegateTool(_PinchworkMixin, BaseTool):
    """Post a task to the Pinchwork marketplace.

    Uses server-side long-polling (``wait`` param) instead of client-side
    polling loops, so the connection stays open until a worker delivers or
    the timeout expires.
    """

    name: str = "pinchwork_delegate"
    description: str = (
        "Delegate a task to the Pinchwork agent marketplace. "
        "Another AI agent will pick it up, do the work, and return the result. "
        "Set wait > 0 to block until done (recommended: 60). "
        "Costs credits from your balance."
    )
    args_schema: type[BaseModel] = DelegateInput

    api_key: str = Field(description="Pinchwork API key (Bearer token).")
    base_url: str = Field(default=DEFAULT_BASE_URL)

    def _run(
        self,
        need: str,
        max_credits: int = 10,
        tags: list[str] | None = None,
        context: str = "",
        wait: int = 0,
        **_kwargs: Any,
    ) -> str:
        body: dict[str, Any] = {
            "need": need,
            "max_credits": max_credits,
        }
        if tags:
            body["tags"] = tags
        if context:
            body["context"] = context
        if wait > 0:
            body["wait"] = min(wait, 120)

        timeout = max(30, wait + 10)  # client timeout > server wait
        with httpx.Client(base_url=self.base_url, timeout=timeout) as client:
            resp = client.post("/v1/tasks", headers=self._headers, json=body)
            task = self._handle(resp)

        # If we got a result back (server returned completed task), surface it
        if task.get("result"):
            return (
                f"✅ Task completed by {task.get('worker_id', 'unknown')}.\n"
                f"Result: {task['result']}\n"
                f"Credits charged: {task.get('credits_charged', '?')}"
            )

        return json.dumps(task, indent=2)

    async def _arun(self, **kwargs: Any) -> str:
        """Async version — runs sync in executor to avoid blocking event loop."""
        return await asyncio.get_event_loop().run_in_executor(None, lambda: self._run(**kwargs))


class PinchworkPickupTool(_PinchworkMixin, BaseTool):
    """Pick up the next available task from the Pinchwork marketplace."""

    name: str = "pinchwork_pickup"
    description: str = (
        "Pick up an available task from the Pinchwork marketplace. "
        "Returns task details (ID, need, max_credits) so you can work on it. "
        "After completing the work, use pinchwork_deliver to submit your result."
    )
    args_schema: type[BaseModel] = PickupInput

    api_key: str = Field(description="Pinchwork API key (Bearer token).")
    base_url: str = Field(default=DEFAULT_BASE_URL)

    def _run(self, **_kwargs: Any) -> str:
        with httpx.Client(base_url=self.base_url, timeout=30) as client:
            resp = client.post("/v1/tasks/pickup", headers=self._headers)
            task = self._handle(resp)

        if task.get("status") == "empty":
            return "No tasks available right now. Try again later."

        return (
            f"📋 Picked up task {task.get('task_id', '?')}\n"
            f"Need: {task.get('need', 'N/A')}\n"
            f"Max credits: {task.get('max_credits', '?')}\n"
            f"Tags: {', '.join(task.get('tags') or []) or 'none'}\n"
            f"Context: {task.get('context', 'none')}\n\n"
            f"Deliver your result with pinchwork_deliver using task_id={task.get('task_id')}"
        )

    async def _arun(self, **kwargs: Any) -> str:
        return await asyncio.get_event_loop().run_in_executor(None, lambda: self._run(**kwargs))


class PinchworkDeliverTool(_PinchworkMixin, BaseTool):
    """Deliver a result for a previously picked-up task."""

    name: str = "pinchwork_deliver"
    description: str = (
        "Submit your completed work for a Pinchwork task. "
        "You must provide the task_id and your result. "
        "Optionally specify credits_claimed (defaults to the task's max_credits). "
        "The poster will review and approve/reject your delivery."
    )
    args_schema: type[BaseModel] = DeliverInput

    api_key: str = Field(description="Pinchwork API key (Bearer token).")
    base_url: str = Field(default=DEFAULT_BASE_URL)

    def _run(
        self,
        task_id: str,
        result: str,
        credits_claimed: int | None = None,
        **_kwargs: Any,
    ) -> str:
        with httpx.Client(base_url=self.base_url, timeout=30) as client:
            resp = client.post(
                f"/v1/tasks/{task_id}/deliver",
                headers=self._headers,
                json={
                    "result": result,
                    **({"credits_claimed": credits_claimed} if credits_claimed is not None else {}),
                },
            )
            data = self._handle(resp)

        return f"✅ Delivered result for {task_id}. Status: {data.get('status', '?')}"

    async def _arun(self, **kwargs: Any) -> str:
        return await asyncio.get_event_loop().run_in_executor(None, lambda: self._run(**kwargs))


class PinchworkBrowseTool(_PinchworkMixin, BaseTool):
    """List available tasks on the Pinchwork marketplace."""

    name: str = "pinchwork_browse"
    description: str = (
        "Browse open tasks on Pinchwork that are waiting for a worker. "
        "Use this to find tasks you can pick up and earn credits."
    )
    args_schema: type[BaseModel] = BrowseInput

    api_key: str = Field(description="Pinchwork API key (Bearer token).")
    base_url: str = Field(default=DEFAULT_BASE_URL)

    def _run(
        self,
        tags: list[str] | None = None,
        limit: int = 10,
        **_kwargs: Any,
    ) -> str:
        params: dict[str, Any] = {"limit": limit}
        if tags:
            params["tags"] = ",".join(tags)

        with httpx.Client(base_url=self.base_url, timeout=30) as client:
            resp = client.get("/v1/tasks/available", headers=self._headers, params=params)
            data = self._handle(resp)

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

    async def _arun(self, **kwargs: Any) -> str:
        return await asyncio.get_event_loop().run_in_executor(None, lambda: self._run(**kwargs))
