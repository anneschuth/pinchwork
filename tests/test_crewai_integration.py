"""Tests for the CrewAI Pinchwork tool integration."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=json_data or {})


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("PINCHWORK_API_KEY", "pwk-test")
    monkeypatch.setenv("PINCHWORK_BASE_URL", "https://test.pinchwork.dev")


class TestPinchworkDelegate:
    def test_delegate_creates_task(self):
        mock_resp = _mock_response(200, {"task_id": "tk-abc", "status": "posted", "need": "test"})

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            from integrations.crewai.pinchwork_tools import pinchwork_delegate

            result = pinchwork_delegate.run(
                need="Summarize this", max_credits=5, tags="research", wait=0
            )

        data = json.loads(result)
        assert data["task_id"] == "tk-abc"

    def test_delegate_with_tags(self):
        mock_resp = _mock_response(200, {"task_id": "tk-def", "status": "posted"})

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            from integrations.crewai.pinchwork_tools import pinchwork_delegate

            result = pinchwork_delegate.run(need="test", tags="python,code-review", wait=0)

        data = json.loads(result)
        assert data["task_id"] == "tk-def"
        # Verify tags were split and sent correctly
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs.get("json", {})
        assert body.get("tags") == ["python", "code-review"]


class TestPinchworkPickup:
    def test_pickup_returns_task(self):
        mock_resp = _mock_response(200, {"task_id": "tk-xyz", "need": "write docs"})

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            from integrations.crewai.pinchwork_tools import pinchwork_pickup

            result = pinchwork_pickup.run()

        data = json.loads(result)
        assert data["task_id"] == "tk-xyz"


class TestPinchworkDeliver:
    def test_deliver_sends_result(self):
        mock_resp = _mock_response(200, {"task_id": "tk-abc", "status": "delivered"})

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_cls.return_value = mock_client

            from integrations.crewai.pinchwork_tools import pinchwork_deliver

            result = pinchwork_deliver.run(task_id="tk-abc", result="done", credits_claimed=5)

        data = json.loads(result)
        assert data["status"] == "delivered"


class TestPinchworkBrowse:
    def test_browse_returns_tasks(self):
        mock_resp = _mock_response(
            200,
            {"tasks": [{"task_id": "tk-1", "need": "test"}], "total": 1},
        )

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_cls.return_value = mock_client

            from integrations.crewai.pinchwork_tools import pinchwork_browse

            result = pinchwork_browse.run()

        data = json.loads(result)
        assert data["total"] == 1


class TestErrorHandling:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("PINCHWORK_API_KEY", raising=False)

        # Need to reimport to pick up env change
        import importlib
        import integrations.crewai.pinchwork_tools as mod

        importlib.reload(mod)

        with pytest.raises(RuntimeError, match="PINCHWORK_API_KEY"):
            mod.pinchwork_browse.run()

    def test_api_error_raises(self):
        mock_resp = _mock_response(403, {"error": "forbidden"})

        with patch("httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_cls.return_value = mock_client

            from integrations.crewai.pinchwork_tools import pinchwork_browse

            with pytest.raises(RuntimeError, match="403"):
                pinchwork_browse.run()
