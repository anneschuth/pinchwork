"""Pinchwork integration blocks for AutoGPT.

Enables agents to delegate tasks to the Pinchwork marketplace and pick up
work from other agents.
"""

import httpx
from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr

from backend.data.block import (
    Block,
    BlockCategory,
    BlockOutput,
    BlockSchemaInput,
    BlockSchemaOutput,
)
from backend.data.model import (
    APIKeyCredentials,
    CredentialsField,
    CredentialsMetaInput,
    SchemaField,
)
from backend.integrations.providers import ProviderName

# -----------------------------------------------------------------
# Credentials
# -----------------------------------------------------------------

TEST_CREDENTIALS = APIKeyCredentials(
    id="01234567-89ab-cdef-0123-456789abcdef",
    provider="pinchwork",
    api_key=SecretStr("pwk-test-key"),
    title="Mock Pinchwork credentials",
)

TEST_CREDENTIALS_INPUT = {
    "provider": TEST_CREDENTIALS.provider,
    "id": TEST_CREDENTIALS.id,
    "type": TEST_CREDENTIALS.type,
    "title": TEST_CREDENTIALS.title,
}

PinchworkCredentials = APIKeyCredentials
PinchworkCredentialsInput = CredentialsMetaInput[
    Literal[ProviderName.PINCHWORK],
    Literal["api_key"],
]


def PinchworkCredentialsField() -> PinchworkCredentialsInput:
    return CredentialsField(
        description="Pinchwork API key. Register at https://pinchwork.dev to get one.",
    )


# -----------------------------------------------------------------
# Config
# -----------------------------------------------------------------

class PinchworkConfig(BaseModel):
    base_url: str = SchemaField(
        default="https://pinchwork.dev",
        description="Pinchwork API base URL",
    )
    model_config = ConfigDict(title="Pinchwork Config")


# -----------------------------------------------------------------
# Delegate Task Block
# -----------------------------------------------------------------

class PinchworkDelegateBlock(Block):
    """Post a task to the Pinchwork marketplace for another agent to complete."""

    class Input(BlockSchemaInput):
        need: str = SchemaField(
            description="What you need done, in plain language",
            placeholder="Review this code for security issues",
        )
        max_credits: int = SchemaField(
            default=10,
            description="Maximum credits to pay for this task",
        )
        tags: str = SchemaField(
            default="",
            description="Comma-separated tags for matching (e.g., 'python,code-review')",
        )
        context: str = SchemaField(
            default="",
            description="Additional context or data for the worker",
        )
        wait_seconds: int = SchemaField(
            default=0,
            description="Seconds to wait for result (0=async, max 120)",
        )
        config: PinchworkConfig = SchemaField(description="Pinchwork config")
        credentials: PinchworkCredentialsInput = PinchworkCredentialsField()

    class Output(BlockSchemaOutput):
        task_id: str = SchemaField(description="The created task ID")
        status: str = SchemaField(description="Task status")
        result: str = SchemaField(description="Task result if completed")
        error: str = SchemaField(description="Error message if failed")

    def __init__(self):
        super().__init__(
            id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            description="Post a task to Pinchwork for another agent to complete.",
            categories={BlockCategory.AI},
            input_schema=PinchworkDelegateBlock.Input,
            output_schema=PinchworkDelegateBlock.Output,
            test_input={
                "need": "Test task",
                "max_credits": 10,
                "tags": "test",
                "context": "",
                "wait_seconds": 0,
                "config": {"base_url": "https://pinchwork.dev"},
                "credentials": TEST_CREDENTIALS_INPUT,
            },
            test_credentials=TEST_CREDENTIALS,
            test_output=[("task_id", "tk-test123"), ("status", "posted")],
            test_mock={"delegate": lambda *args, **kwargs: {"task_id": "tk-test123", "status": "posted"}},
        )

    def run(self, input_data: Input, *, credentials: PinchworkCredentials, **kwargs) -> BlockOutput:
        base_url = input_data.config.base_url
        api_key = credentials.api_key.get_secret_value()

        body = {
            "need": input_data.need,
            "max_credits": input_data.max_credits,
        }
        if input_data.tags:
            body["tags"] = [t.strip() for t in input_data.tags.split(",") if t.strip()]
        if input_data.context:
            body["context"] = input_data.context
        if input_data.wait_seconds > 0:
            body["wait"] = min(input_data.wait_seconds, 120)

        try:
            with httpx.Client(timeout=max(30, input_data.wait_seconds + 10)) as client:
                resp = client.post(
                    f"{base_url}/v1/tasks",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()

            yield "task_id", data.get("task_id", "")
            yield "status", data.get("status", "posted")
            yield "result", data.get("result", "")
        except Exception as e:
            yield "error", str(e)


# -----------------------------------------------------------------
# Pickup Task Block
# -----------------------------------------------------------------

class PinchworkPickupBlock(Block):
    """Pick up a task from the Pinchwork marketplace to work on."""

    class Input(BlockSchemaInput):
        tags: str = SchemaField(
            default="",
            description="Comma-separated tags to filter tasks",
        )
        config: PinchworkConfig = SchemaField(description="Pinchwork config")
        credentials: PinchworkCredentialsInput = PinchworkCredentialsField()

    class Output(BlockSchemaOutput):
        task_id: str = SchemaField(description="The picked up task ID")
        need: str = SchemaField(description="What needs to be done")
        context: str = SchemaField(description="Additional context")
        max_credits: int = SchemaField(description="Maximum credits available")
        error: str = SchemaField(description="Error message if failed")

    def __init__(self):
        super().__init__(
            id="b2c3d4e5-f6a7-8901-bcde-f23456789012",
            description="Pick up a task from Pinchwork to earn credits.",
            categories={BlockCategory.AI},
            input_schema=PinchworkPickupBlock.Input,
            output_schema=PinchworkPickupBlock.Output,
            test_input={
                "tags": "",
                "config": {"base_url": "https://pinchwork.dev"},
                "credentials": TEST_CREDENTIALS_INPUT,
            },
            test_credentials=TEST_CREDENTIALS,
            test_output=[("task_id", "tk-test456"), ("need", "Test task")],
            test_mock={"pickup": lambda *args, **kwargs: {"task_id": "tk-test456", "need": "Test task"}},
        )

    def run(self, input_data: Input, *, credentials: PinchworkCredentials, **kwargs) -> BlockOutput:
        base_url = input_data.config.base_url
        api_key = credentials.api_key.get_secret_value()

        params = {}
        if input_data.tags:
            params["tags"] = input_data.tags

        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{base_url}/v1/tasks/pickup",
                    headers={"Authorization": f"Bearer {api_key}"},
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()

            if data.get("status") == "empty":
                yield "error", "No tasks available"
                return

            yield "task_id", data.get("task_id", data.get("id", ""))
            yield "need", data.get("need", "")
            yield "context", data.get("context", "")
            yield "max_credits", data.get("max_credits", 0)
        except Exception as e:
            yield "error", str(e)


# -----------------------------------------------------------------
# Deliver Result Block
# -----------------------------------------------------------------

class PinchworkDeliverBlock(Block):
    """Deliver completed work for a task you picked up."""

    class Input(BlockSchemaInput):
        task_id: str = SchemaField(
            description="The task ID to deliver for",
            placeholder="tk-abc123",
        )
        result: str = SchemaField(
            description="Your completed work",
            placeholder="Here are my findings...",
        )
        credits_claimed: int = SchemaField(
            default=0,
            description="Credits to claim (0 = use max_credits)",
        )
        config: PinchworkConfig = SchemaField(description="Pinchwork config")
        credentials: PinchworkCredentialsInput = PinchworkCredentialsField()

    class Output(BlockSchemaOutput):
        status: str = SchemaField(description="Delivery status")
        error: str = SchemaField(description="Error message if failed")

    def __init__(self):
        super().__init__(
            id="c3d4e5f6-a7b8-9012-cdef-345678901234",
            description="Deliver completed work for a Pinchwork task.",
            categories={BlockCategory.AI},
            input_schema=PinchworkDeliverBlock.Input,
            output_schema=PinchworkDeliverBlock.Output,
            test_input={
                "task_id": "tk-test123",
                "result": "Here is my work",
                "credits_claimed": 0,
                "config": {"base_url": "https://pinchwork.dev"},
                "credentials": TEST_CREDENTIALS_INPUT,
            },
            test_credentials=TEST_CREDENTIALS,
            test_output=[("status", "delivered")],
            test_mock={"deliver": lambda *args, **kwargs: {"status": "delivered"}},
        )

    def run(self, input_data: Input, *, credentials: PinchworkCredentials, **kwargs) -> BlockOutput:
        base_url = input_data.config.base_url
        api_key = credentials.api_key.get_secret_value()

        body = {"result": input_data.result}
        if input_data.credits_claimed > 0:
            body["credits_claimed"] = input_data.credits_claimed

        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{base_url}/v1/tasks/{input_data.task_id}/deliver",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()

            yield "status", data.get("status", "delivered")
        except Exception as e:
            yield "error", str(e)


# -----------------------------------------------------------------
# Browse Tasks Block
# -----------------------------------------------------------------

class PinchworkBrowseBlock(Block):
    """Browse available tasks on the Pinchwork marketplace."""

    class Input(BlockSchemaInput):
        tags: str = SchemaField(
            default="",
            description="Comma-separated tags to filter tasks",
        )
        limit: int = SchemaField(
            default=10,
            description="Maximum number of tasks to return",
        )
        config: PinchworkConfig = SchemaField(description="Pinchwork config")
        credentials: PinchworkCredentialsInput = PinchworkCredentialsField()

    class Output(BlockSchemaOutput):
        tasks: list = SchemaField(description="List of available tasks")
        count: int = SchemaField(description="Number of tasks found")
        error: str = SchemaField(description="Error message if failed")

    def __init__(self):
        super().__init__(
            id="d4e5f6a7-b8c9-0123-defa-456789012345",
            description="Browse available tasks on the Pinchwork marketplace.",
            categories={BlockCategory.AI},
            input_schema=PinchworkBrowseBlock.Input,
            output_schema=PinchworkBrowseBlock.Output,
            test_input={
                "tags": "",
                "limit": 10,
                "config": {"base_url": "https://pinchwork.dev"},
                "credentials": TEST_CREDENTIALS_INPUT,
            },
            test_credentials=TEST_CREDENTIALS,
            test_output=[("tasks", []), ("count", 0)],
            test_mock={"browse": lambda *args, **kwargs: {"tasks": [], "total": 0}},
        )

    def run(self, input_data: Input, *, credentials: PinchworkCredentials, **kwargs) -> BlockOutput:
        base_url = input_data.config.base_url
        api_key = credentials.api_key.get_secret_value()

        params = {"limit": input_data.limit}
        if input_data.tags:
            params["tags"] = input_data.tags

        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{base_url}/v1/tasks/available",
                    headers={"Authorization": f"Bearer {api_key}"},
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()

            tasks = data.get("tasks", [])
            yield "tasks", tasks
            yield "count", len(tasks)
        except Exception as e:
            yield "error", str(e)
