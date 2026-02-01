"""Tests for the LangChain Pinchwork tool integration."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    resp = httpx.Response(status_code, json=json_data or {})
    return resp


class TestPinchworkDelegateTool:
    def test_delegate_creates_task(self):
        from integrations.langchain.pinchwork_tool import PinchworkDelegateTool

        tool = PinchworkDelegateTool(api_key="pwk-test", base_url="https://test.pinchwork.dev")

        mock_resp = _mock_response(200, {"task_id": "tk-abc", "status": "posted", "need": "test"})

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = tool._run(need="Summarize this", max_credits=5)

        data = json.loads(result)
        assert data["task_id"] == "tk-abc"
        assert data["status"] == "posted"

    def test_delegate_with_wait_polls(self):
        from integrations.langchain.pinchwork_tool import PinchworkDelegateTool

        tool = PinchworkDelegateTool(api_key="pwk-test", base_url="https://test.pinchwork.dev")

        create_resp = _mock_response(200, {"task_id": "tk-abc", "status": "posted"})
        poll_resp = _mock_response(
            200, {"task_id": "tk-abc", "status": "delivered", "result": "done"}
        )

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = create_resp
            mock_client.get.return_value = poll_resp
            mock_client_cls.return_value = mock_client

            result = tool._run(need="test", wait=True, poll_interval=0.01, poll_timeout=1)

        data = json.loads(result)
        assert data["status"] == "delivered"
        assert data["result"] == "done"


class TestPinchworkPickupTool:
    def test_pickup_returns_task(self):
        from integrations.langchain.pinchwork_tool import PinchworkPickupTool

        tool = PinchworkPickupTool(api_key="pwk-test", base_url="https://test.pinchwork.dev")

        mock_resp = _mock_response(200, {"task_id": "tk-xyz", "need": "write docs"})

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = tool._run()

        data = json.loads(result)
        assert data["task_id"] == "tk-xyz"


class TestPinchworkDeliverTool:
    def test_deliver_sends_result(self):
        from integrations.langchain.pinchwork_tool import PinchworkDeliverTool

        tool = PinchworkDeliverTool(api_key="pwk-test", base_url="https://test.pinchwork.dev")

        mock_resp = _mock_response(200, {"task_id": "tk-abc", "status": "delivered"})

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = tool._run(task_id="tk-abc", result="here is the answer", credits_claimed=5)

        data = json.loads(result)
        assert data["status"] == "delivered"


class TestPinchworkBrowseTool:
    def test_browse_lists_tasks(self):
        from integrations.langchain.pinchwork_tool import PinchworkBrowseTool

        tool = PinchworkBrowseTool(api_key="pwk-test", base_url="https://test.pinchwork.dev")

        mock_resp = _mock_response(
            200,
            {"tasks": [{"task_id": "tk-1", "need": "test"}], "total": 1},
        )

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = tool._run()

        data = json.loads(result)
        assert data["total"] == 1


class TestErrorHandling:
    def test_api_error_raises(self):
        from integrations.langchain.pinchwork_tool import PinchworkDelegateTool

        tool = PinchworkDelegateTool(api_key="pwk-test", base_url="https://test.pinchwork.dev")

        mock_resp = _mock_response(401, {"error": "unauthorized"})

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="401"):
                tool._run(need="test")
