"""Tests for the Pinchwork MCP server integration."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=json_data or {})


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("PINCHWORK_API_KEY", "pwk-test")
    monkeypatch.setenv("PINCHWORK_BASE_URL", "https://test.pinchwork.dev")


class TestPinchworkDelegate:
    @pytest.mark.asyncio
    async def test_delegate_creates_task(self):
        mock_resp = _mock_response(200, {"task_id": "tk-abc", "status": "posted"})

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request.return_value = mock_resp
            mock_cls.return_value = mock_client

            # Re-import after env is set
            from integrations.mcp.server import pinchwork_delegate

            result = await pinchwork_delegate(need="Summarize this", max_credits=5)

        assert "tk-abc" in result
        assert "posted" in result

    @pytest.mark.asyncio
    async def test_delegate_with_wait_returns_result(self):
        mock_resp = _mock_response(
            200,
            {
                "task_id": "tk-abc",
                "status": "delivered",
                "result": "here is the summary",
                "credits_claimed": 5,
            },
        )

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request.return_value = mock_resp
            mock_cls.return_value = mock_client

            from integrations.mcp.server import pinchwork_delegate

            result = await pinchwork_delegate(need="test", wait=30)

        assert "completed" in result or "delivered" in result.lower() or "tk-abc" in result


class TestPinchworkPickup:
    @pytest.mark.asyncio
    async def test_pickup_returns_task(self):
        mock_resp = _mock_response(
            200, {"task_id": "tk-xyz", "need": "write docs", "max_credits": 10}
        )

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request.return_value = mock_resp
            mock_cls.return_value = mock_client

            from integrations.mcp.server import pinchwork_pickup

            result = await pinchwork_pickup()

        assert "tk-xyz" in result
        assert "write docs" in result


class TestPinchworkDeliver:
    @pytest.mark.asyncio
    async def test_deliver_sends_result(self):
        mock_resp = _mock_response(200, {"task_id": "tk-abc", "status": "delivered"})

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request.return_value = mock_resp
            mock_cls.return_value = mock_client

            from integrations.mcp.server import pinchwork_deliver

            result = await pinchwork_deliver(
                task_id="tk-abc", result="answer here", credits_claimed=5
            )

        assert "tk-abc" in result


class TestPinchworkBrowse:
    @pytest.mark.asyncio
    async def test_browse_lists_tasks(self):
        mock_resp = _mock_response(
            200,
            {"tasks": [{"task_id": "tk-1", "need": "test task", "max_credits": 5, "tags": []}]},
        )

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request.return_value = mock_resp
            mock_cls.return_value = mock_client

            from integrations.mcp.server import pinchwork_browse

            result = await pinchwork_browse()

        assert "1" in result  # Found 1 task


class TestPinchworkStatus:
    @pytest.mark.asyncio
    async def test_status_returns_agent_info(self):
        mock_resp = _mock_response(200, {"name": "test-agent", "credits": 100, "reputation": 4.5})

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.request.return_value = mock_resp
            mock_cls.return_value = mock_client

            from integrations.mcp.server import pinchwork_status

            result = await pinchwork_status()

        assert "test-agent" in result
        assert "100" in result
