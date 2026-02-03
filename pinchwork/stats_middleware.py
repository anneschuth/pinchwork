"""Middleware for collecting route statistics."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Patterns to normalize routes (replace IDs with placeholders)
ID_PATTERNS = [
    (re.compile(r"/tasks/[a-zA-Z0-9_-]+"), "/tasks/{id}"),
    (re.compile(r"/agents/[a-zA-Z0-9_-]+"), "/agents/{id}"),
    (re.compile(r"/questions/[a-zA-Z0-9_-]+"), "/questions/{id}"),
    (re.compile(r"/messages/[a-zA-Z0-9_-]+"), "/messages/{id}"),
    (re.compile(r"/ratings/[a-zA-Z0-9_-]+"), "/ratings/{id}"),
    (re.compile(r"/reports/[a-zA-Z0-9_-]+"), "/reports/{id}"),
    (re.compile(r"/page/[a-zA-Z0-9_.-]+"), "/page/{name}"),
    (re.compile(r"/admin/tasks/[a-zA-Z0-9_-]+"), "/admin/tasks/{id}"),
    (re.compile(r"/admin/agents/[a-zA-Z0-9_-]+"), "/admin/agents/{id}"),
]

# Routes to skip (health checks, static, etc.)
SKIP_ROUTES = {"/health", "/healthz", "/ready", "/favicon.ico", "/robots.txt"}


def _normalize_route(path: str) -> str:
    """Normalize a path by replacing IDs with placeholders."""
    for pattern, replacement in ID_PATTERNS:
        path = pattern.sub(replacement, path)
    return path


def _truncate_to_hour(dt: datetime) -> datetime:
    """Truncate datetime to the hour."""
    return dt.replace(minute=0, second=0, microsecond=0)


class StatsMiddleware(BaseHTTPMiddleware):
    """Middleware that collects request statistics per route."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip certain routes
        if path in SKIP_ROUTES or path.startswith("/docs-assets/"):
            return await call_next(request)

        start_time = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        # Record stats asynchronously (fire and forget to not slow down response)
        # Using try/except instead of contextlib.suppress because suppress() doesn't
        # work well with async code, and we want to ensure stats never break requests.
        try:  # noqa: SIM105
            await self._record_stats(
                route=_normalize_route(path),
                method=request.method,
                status_code=response.status_code,
                elapsed_ms=elapsed_ms,
            )
        except Exception:
            pass

        return response

    async def _record_stats(
        self,
        route: str,
        method: str,
        status_code: int,
        elapsed_ms: int,
    ) -> None:
        """Record stats to database using raw SQL for performance."""
        from sqlalchemy import text

        from pinchwork.database import get_session_factory

        hour = _truncate_to_hour(datetime.now(UTC))
        is_4xx = 1 if 400 <= status_code < 500 else 0
        is_5xx = 1 if status_code >= 500 else 0

        session_factory = get_session_factory()
        if session_factory is None:
            return  # DB not initialized yet

        async with session_factory() as session:
            # Upsert pattern for SQLite
            await session.execute(
                text("""
                    INSERT INTO route_stats
                        (route, method, hour, request_count, error_4xx, error_5xx,
                         total_ms, min_ms, max_ms)
                    VALUES
                        (:route, :method, :hour, 1, :is_4xx, :is_5xx,
                         :elapsed_ms, :elapsed_ms, :elapsed_ms)
                    ON CONFLICT (route, method, hour) DO UPDATE SET
                        request_count = request_count + 1,
                        error_4xx = error_4xx + :is_4xx,
                        error_5xx = error_5xx + :is_5xx,
                        total_ms = total_ms + :elapsed_ms,
                        min_ms = MIN(min_ms, :elapsed_ms),
                        max_ms = MAX(max_ms, :elapsed_ms)
                """),
                {
                    "route": route,
                    "method": method,
                    "hour": hour.isoformat(),
                    "is_4xx": is_4xx,
                    "is_5xx": is_5xx,
                    "elapsed_ms": elapsed_ms,
                },
            )
            await session.commit()
