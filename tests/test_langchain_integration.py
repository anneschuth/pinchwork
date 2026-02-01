"""Tests for the LangChain Pinchwork tool integration.

Skipped when langchain-core is not installed (e.g. in base CI).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

langchain = pytest.importorskip("langchain_core", reason="langchain-core not installed")


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=json_data or {})


@pytest.fixture()
def delegate_tool():
    from integrations.langchain.pinchwork_tool import PinchworkDelegateTool

    return PinchworkDelegateTool(api_key="pwk-test", base_url="https://test.dev")


@pytest.fixture()
def pickup_tool():
    from integrations.langchain.pinchwork_tool import PinchworkPickupTool

    return PinchworkPickupTool(api_key="pwk-test", base_url="https://test.dev")


@pytest.fixture()
def deliver_tool():
    from integrations.langchain.pinchwork_tool import PinchworkDeliverTool

    return PinchworkDeliverTool(api_key="pwk-test", base_url="https://test.dev")


@pytest.fixture()
def browse_tool():
    from integrations.langchain.pinchwork_tool import PinchworkBrowseTool

    return PinchworkBrowseTool(api_key="pwk-test", base_url="https://test.dev")


def _patch_client(mock_client):
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    return mock_client


class TestDelegate:
    def test_creates_task_no_wait(self, delegate_tool):
        mock_resp = _mock_response(200, {"task_id": "tk-abc", "status": "posted"})
        with patch("httpx.Client") as cls:
            m = _patch_client(MagicMock())
            m.post.return_value = mock_resp
            cls.return_value = m
            result = delegate_tool._run(need="Summarize this", max_credits=5, wait=0)
        data = json.loads(result)
        assert data["task_id"] == "tk-abc"

    def test_returns_result_when_completed(self, delegate_tool):
        mock_resp = _mock_response(
            200,
            {
                "task_id": "tk-abc",
                "status": "delivered",
                "result": "done",
                "worker_id": "ag-x",
                "credits_charged": 5,
            },
        )
        with patch("httpx.Client") as cls:
            m = _patch_client(MagicMock())
            m.post.return_value = mock_resp
            cls.return_value = m
            result = delegate_tool._run(need="test", wait=60)
        assert "done" in result
        assert "✅" in result

    def test_sends_tags_and_context(self, delegate_tool):
        mock_resp = _mock_response(200, {"task_id": "tk-abc", "status": "posted"})
        with patch("httpx.Client") as cls:
            m = _patch_client(MagicMock())
            m.post.return_value = mock_resp
            cls.return_value = m
            delegate_tool._run(need="review", tags=["python"], context="PR #42", wait=0)
        body = m.post.call_args.kwargs.get("json", {})
        assert body["tags"] == ["python"]
        assert body["context"] == "PR #42"


class TestPickup:
    def test_returns_formatted_task(self, pickup_tool):
        mock_resp = _mock_response(
            200, {"task_id": "tk-xyz", "need": "write docs", "max_credits": 10, "tags": ["docs"]}
        )
        with patch("httpx.Client") as cls:
            m = _patch_client(MagicMock())
            m.post.return_value = mock_resp
            cls.return_value = m
            result = pickup_tool._run()
        assert "tk-xyz" in result and "pinchwork_deliver" in result

    def test_handles_204(self, pickup_tool):
        with patch("httpx.Client") as cls:
            m = _patch_client(MagicMock())
            m.post.return_value = httpx.Response(204)
            cls.return_value = m
            result = pickup_tool._run()
        assert "No tasks" in result or "empty" in result


class TestDeliver:
    def test_sends_result(self, deliver_tool):
        mock_resp = _mock_response(200, {"task_id": "tk-abc", "status": "delivered"})
        with patch("httpx.Client") as cls:
            m = _patch_client(MagicMock())
            m.post.return_value = mock_resp
            cls.return_value = m
            result = deliver_tool._run(task_id="tk-abc", result="answer", credits_claimed=5)
        assert "✅" in result and "tk-abc" in result


class TestBrowse:
    def test_formats_tasks(self, browse_tool):
        mock_resp = _mock_response(
            200, {"tasks": [{"task_id": "tk-1", "need": "test", "max_credits": 5, "tags": []}]}
        )
        with patch("httpx.Client") as cls:
            m = _patch_client(MagicMock())
            m.get.return_value = mock_resp
            cls.return_value = m
            result = browse_tool._run()
        assert "1 task" in result and "tk-1" in result

    def test_empty_marketplace(self, browse_tool):
        mock_resp = _mock_response(200, {"tasks": []})
        with patch("httpx.Client") as cls:
            m = _patch_client(MagicMock())
            m.get.return_value = mock_resp
            cls.return_value = m
            result = browse_tool._run()
        assert "No tasks" in result


class TestErrors:
    def test_api_error_includes_detail(self, delegate_tool):
        mock_resp = _mock_response(401, {"error": "invalid api key"})
        with patch("httpx.Client") as cls:
            m = _patch_client(MagicMock())
            m.post.return_value = mock_resp
            cls.return_value = m
            with pytest.raises(RuntimeError, match="401"):
                delegate_tool._run(need="test", wait=0)
