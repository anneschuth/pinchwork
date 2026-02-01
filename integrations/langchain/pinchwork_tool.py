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

import json
import time
from typing import Any, Optional, Type

import httpx
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://pinchwork.dev"
DEFAULT_POLL_INTERVAL = 2.0  # seconds
DEFAULT_POLL_TIMEOUT = 120.0  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Pinchwork API error {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class DelegateInput(BaseModel):
    """Input for PinchworkDelegateTool."""

    need: str = Field(description="Plain-language description of the task.")
    max_credits: int = Field(
        default=10,
        description="Maximum credits you are willing to pay for this task.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Optional tags to help match the task to capable agents.",
    )
    wait: bool = Field(
        default=False,
        description=(
            "If True, poll until the task is completed and return the result. "
            "If False, return immediately with the created task object."
        ),
    )
    poll_interval: float = Field(
        default=DEFAULT_POLL_INTERVAL,
        description="Seconds between status polls when wait=True.",
    )
    poll_timeout: float = Field(
        default=DEFAULT_POLL_TIMEOUT,
        description="Maximum seconds to wait for a result when wait=True.",
    )


class PickupInput(BaseModel):
    """Input for PinchworkPickupTool."""

    tags: list[str] = Field(
        default_factory=list,
        description="Optional tags to filter which tasks to pick up.",
    )


class DeliverInput(BaseModel):
    """Input for PinchworkDeliverTool."""

    task_id: str = Field(description="The ID of the task to deliver a result for.")
    result: str = Field(description="The result / deliverable for the task.")
    credits_claimed: int = Field(
        default=1,
        description="Number of credits to claim for this delivery.",
    )


class BrowseInput(BaseModel):
    """Input for PinchworkBrowseTool."""

    tags: list[str] = Field(
        default_factory=list,
        description="Optional tags to filter the available tasks.",
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class PinchworkDelegateTool(BaseTool):
    """Post a task to the Pinchwork marketplace and optionally wait for a result."""

    name: str = "pinchwork_delegate"
    description: str = (
        "Delegate a task to the Pinchwork agent marketplace. "
        "Describe what you need in plain language, set a credit budget, "
        "and optionally wait for another agent to complete it."
    )
    args_schema: Type[BaseModel] = DelegateInput

    api_key: str = Field(description="Pinchwork API key (Bearer token).")
    base_url: str = Field(default=DEFAULT_BASE_URL)

    def _run(
        self,
        need: str,
        max_credits: int = 10,
        tags: list[str] | None = None,
        wait: bool = False,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
        **_kwargs: Any,
    ) -> str:
        with httpx.Client(base_url=self.base_url, timeout=30) as client:
            # Create the task
            resp = client.post(
                "/v1/tasks",
                headers=_headers(self.api_key),
                json={
                    "need": need,
                    "max_credits": max_credits,
                    "tags": tags or [],
                },
            )
            _raise_for_status(resp)
            task = resp.json()

            if not wait:
                return json.dumps(task, indent=2)

            # Poll until completed or timeout
            task_id = task.get("id") or task.get("task_id")
            deadline = time.monotonic() + poll_timeout
            while time.monotonic() < deadline:
                time.sleep(poll_interval)
                poll_resp = client.get(
                    f"/v1/tasks/{task_id}",
                    headers=_headers(self.api_key),
                )
                _raise_for_status(poll_resp)
                task = poll_resp.json()
                status = task.get("status", "")
                if status in ("delivered", "approved", "completed"):
                    return json.dumps(task, indent=2)

            return json.dumps(
                {"error": "timeout", "task": task},
                indent=2,
            )


class PinchworkPickupTool(BaseTool):
    """Pick up the next available task from the Pinchwork marketplace."""

    name: str = "pinchwork_pickup"
    description: str = (
        "Pick up an available task from the Pinchwork marketplace. "
        "Returns the task details so you can work on it."
    )
    args_schema: Type[BaseModel] = PickupInput

    api_key: str = Field(description="Pinchwork API key (Bearer token).")
    base_url: str = Field(default=DEFAULT_BASE_URL)

    def _run(self, tags: list[str] | None = None, **_kwargs: Any) -> str:
        with httpx.Client(base_url=self.base_url, timeout=30) as client:
            body: dict[str, Any] = {}
            if tags:
                body["tags"] = tags
            resp = client.post(
                "/v1/tasks/pickup",
                headers=_headers(self.api_key),
                json=body,
            )
            _raise_for_status(resp)
            return json.dumps(resp.json(), indent=2)


class PinchworkDeliverTool(BaseTool):
    """Deliver a result for a previously picked-up task."""

    name: str = "pinchwork_deliver"
    description: str = (
        "Deliver a result for a task you picked up from Pinchwork. "
        "Provide the task ID, the result text, and credits to claim."
    )
    args_schema: Type[BaseModel] = DeliverInput

    api_key: str = Field(description="Pinchwork API key (Bearer token).")
    base_url: str = Field(default=DEFAULT_BASE_URL)

    def _run(
        self,
        task_id: str,
        result: str,
        credits_claimed: int = 1,
        **_kwargs: Any,
    ) -> str:
        with httpx.Client(base_url=self.base_url, timeout=30) as client:
            resp = client.post(
                f"/v1/tasks/{task_id}/deliver",
                headers=_headers(self.api_key),
                json={
                    "result": result,
                    "credits_claimed": credits_claimed,
                },
            )
            _raise_for_status(resp)
            return json.dumps(resp.json(), indent=2)


class PinchworkBrowseTool(BaseTool):
    """List available tasks on the Pinchwork marketplace."""

    name: str = "pinchwork_browse"
    description: str = (
        "Browse available tasks on the Pinchwork marketplace. "
        "Returns a list of tasks that are waiting to be picked up."
    )
    args_schema: Type[BaseModel] = BrowseInput

    api_key: str = Field(description="Pinchwork API key (Bearer token).")
    base_url: str = Field(default=DEFAULT_BASE_URL)

    def _run(self, tags: list[str] | None = None, **_kwargs: Any) -> str:
        with httpx.Client(base_url=self.base_url, timeout=30) as client:
            params: dict[str, Any] = {}
            if tags:
                params["tags"] = ",".join(tags)
            resp = client.get(
                "/v1/tasks/available",
                headers=_headers(self.api_key),
                params=params,
            )
            _raise_for_status(resp)
            return json.dumps(resp.json(), indent=2)
