"""Tests for the LangChain Pinchwork tool integration."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=json_data or {})


class TestPinchworkDelegateTool:
    def test_delegate_creates_task_no_wait(self):
        from integrations.langchain.pinchwork_tool import PinchworkDelegateTool

        tool = PinchworkDelegateTool(api_key="pwk-test", base_url="https://test.dev")

        mock_resp = _mock_response(200, {"task_id": "tk-abc", "status": "posted", "need": "test"})

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            result = tool._run(need="Summarize this", max_credits=5, wait=0)

        data = json.loads(result)
        assert data["task_id"] == "tk-abc"
        assert data["status"] == "posted"

    def test_delegate_with_wait_returns_result(self):
        from integrations.langchain.pinchwork_tool import PinchworkDelegateTool

        tool = PinchworkDelegateTool(api_key="pwk-test", base_url="https://test.dev")

        mock_resp = _mock_response(
            200,
            {
                "task_id": "tk-abc",
                "status": "delivered",
                "result": "here is the answer",
                "worker_id": "ag-xyz",
                "credits_charged": 5,
            },
        )

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            result = tool._run(need="test", wait=60)

        assert "here is the answer" in result
        assert "✅" in result

    def test_delegate_sends_tags_and_context(self):
        from integrations.langchain.pinchwork_tool import PinchworkDelegateTool

        tool = PinchworkDelegateTool(api_key="pwk-test", base_url="https://test.dev")

        mock_resp = _mock_response(200, {"task_id": "tk-abc", "status": "posted"})

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            tool._run(
                need="review code",
                max_credits=10,
                tags=["python", "review"],
                context="PR #42",
                wait=0,
            )

        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs.get("json", {})
        assert body["tags"] == ["python", "review"]
        assert body["context"] == "PR #42"


class TestPinchworkPickupTool:
    def test_pickup_returns_formatted_task(self):
        from integrations.langchain.pinchwork_tool import PinchworkPickupTool

        tool = PinchworkPickupTool(api_key="pwk-test", base_url="https://test.dev")

        mock_resp = _mock_response(
            200, {"task_id": "tk-xyz", "need": "write docs", "max_credits": 10, "tags": ["docs"]}
        )

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            result = tool._run()

        assert "tk-xyz" in result
        assert "write docs" in result
        assert "pinchwork_deliver" in result  # should guide the agent

    def test_pickup_handles_204_no_tasks(self):
        from integrations.langchain.pinchwork_tool import PinchworkPickupTool

        tool = PinchworkPickupTool(api_key="pwk-test", base_url="https://test.dev")

        mock_resp = httpx.Response(204)

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            result = tool._run()

        assert "No tasks" in result or "empty" in result


class TestPinchworkDeliverTool:
    def test_deliver_sends_result(self):
        from integrations.langchain.pinchwork_tool import PinchworkDeliverTool

        tool = PinchworkDeliverTool(api_key="pwk-test", base_url="https://test.dev")

        mock_resp = _mock_response(200, {"task_id": "tk-abc", "status": "delivered"})

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            result = tool._run(task_id="tk-abc", result="the answer", credits_claimed=5)

        assert "✅" in result
        assert "tk-abc" in result


class TestPinchworkBrowseTool:
    def test_browse_formats_tasks(self):
        from integrations.langchain.pinchwork_tool import PinchworkBrowseTool

        tool = PinchworkBrowseTool(api_key="pwk-test", base_url="https://test.dev")

        mock_resp = _mock_response(
            200,
            {"tasks": [{"task_id": "tk-1", "need": "test task", "max_credits": 5, "tags": []}]},
        )

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_cls.return_value = mock_client

            result = tool._run()

        assert "1 task" in result
        assert "tk-1" in result

    def test_browse_empty_marketplace(self):
        from integrations.langchain.pinchwork_tool import PinchworkBrowseTool

        tool = PinchworkBrowseTool(api_key="pwk-test", base_url="https://test.dev")

        mock_resp = _mock_response(200, {"tasks": []})

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_cls.return_value = mock_client

            result = tool._run()

        assert "No tasks" in result


class TestErrorHandling:
    def test_api_error_includes_detail(self):
        from integrations.langchain.pinchwork_tool import PinchworkDelegateTool

        tool = PinchworkDelegateTool(api_key="pwk-test", base_url="https://test.dev")

        mock_resp = _mock_response(401, {"error": "invalid api key"})

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="401"):
                tool._run(need="test", wait=0)
