"""Tests for the CrewAI Pinchwork tools. Skipped when crewai not installed."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

crewai_mod = pytest.importorskip("crewai", reason="crewai not installed")


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=json_data or {})


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("PINCHWORK_API_KEY", "pwk-test")
    monkeypatch.setenv("PINCHWORK_BASE_URL", "https://test.dev")


def _patch_client(mock_resp):
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=m)
    m.__exit__ = MagicMock(return_value=False)
    m.post.return_value = mock_resp
    m.get.return_value = mock_resp
    return m


class TestDelegate:
    def test_creates_task(self):
        with patch(
            "httpx.Client",
            return_value=_patch_client(
                _mock_response(200, {"task_id": "tk-abc", "status": "posted"})
            ),
        ):
            from integrations.crewai.pinchwork_tools import pinchwork_delegate

            result = pinchwork_delegate.run(need="test", max_credits=5, wait=0)
        data = json.loads(result)
        assert data["task_id"] == "tk-abc"


class TestPickup:
    def test_returns_task(self):
        with patch(
            "httpx.Client",
            return_value=_patch_client(
                _mock_response(
                    200, {"task_id": "tk-xyz", "need": "write docs", "max_credits": 10, "tags": []}
                )
            ),
        ):
            from integrations.crewai.pinchwork_tools import pinchwork_pickup

            result = pinchwork_pickup.run()
        assert "tk-xyz" in result


class TestBrowse:
    def test_returns_tasks(self):
        with patch(
            "httpx.Client",
            return_value=_patch_client(
                _mock_response(200, {"tasks": [{"task_id": "tk-1", "need": "test"}], "total": 1})
            ),
        ):
            from integrations.crewai.pinchwork_tools import pinchwork_browse

            result = pinchwork_browse.run()
        assert "1 task" in result
