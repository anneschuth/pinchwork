"""Tests for the Pinchwork MCP server. Skipped when mcp SDK not installed."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

mcp_mod = pytest.importorskip("mcp", reason="mcp SDK not installed")


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=json_data or {})


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("PINCHWORK_API_KEY", "pwk-test")
    monkeypatch.setenv("PINCHWORK_BASE_URL", "https://test.dev")
    # Reset the global client so each test gets a fresh mock
    import integrations.mcp.server as _srv
    _srv._client = None


def _mock_async_client(mock_resp):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.request.return_value = mock_resp
    mock_client.is_closed = False
    return mock_client


class TestDelegate:
    @pytest.mark.asyncio
    async def test_creates_task(self):
        with patch(
            "httpx.AsyncClient",
            return_value=_mock_async_client(
                _mock_response(200, {"task_id": "tk-abc", "status": "posted"})
            ),
        ):
            from integrations.mcp.server import pinchwork_delegate

            result = await pinchwork_delegate(need="test", max_credits=5)
        assert "tk-abc" in result

    @pytest.mark.asyncio
    async def test_returns_completed_result(self):
        resp = _mock_response(
            200,
            {
                "task_id": "tk-abc",
                "status": "delivered",
                "result": "answer",
                "worker_id": "ag-x",
                "credits_charged": 5,
            },
        )
        with patch("httpx.AsyncClient", return_value=_mock_async_client(resp)):
            from integrations.mcp.server import pinchwork_delegate

            result = await pinchwork_delegate(need="test", wait=30)
        assert "answer" in result


class TestPickup:
    @pytest.mark.asyncio
    async def test_returns_task(self):
        resp = _mock_response(
            200, {"task_id": "tk-xyz", "need": "write docs", "max_credits": 10, "tags": []}
        )
        with patch("httpx.AsyncClient", return_value=_mock_async_client(resp)):
            from integrations.mcp.server import pinchwork_pickup

            result = await pinchwork_pickup()
        assert "tk-xyz" in result and "write docs" in result


class TestStatus:
    @pytest.mark.asyncio
    async def test_returns_agent_info(self):
        resp = _mock_response(
            200,
            {
                "name": "test-agent",
                "credits": 100,
                "reputation": 4.5,
                "tasks_posted": 5,
                "tasks_completed": 3,
            },
        )
        with patch("httpx.AsyncClient", return_value=_mock_async_client(resp)):
            from integrations.mcp.server import pinchwork_status

            result = await pinchwork_status()
        assert "test-agent" in result and "100" in result
