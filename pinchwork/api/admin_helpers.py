"""Helper functions for the admin dashboard.

Contains auth, HTML rendering, and chart utilities.
Separated for maintainability. See admin_dashboard.py for usage.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import time
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, Response

from pinchwork.config import settings

from .admin_styles import ADMIN_CSS

# ---------------------------------------------------------------------------
# SQL date helpers (SQLite-specific)
# ---------------------------------------------------------------------------


def sql_date_hour(column: str) -> str:
    """SQL fragment to truncate a datetime column to hour. SQLite only."""
    return f"strftime('%Y-%m-%d %H', {column})"


def sql_date_day(column: str) -> str:
    """SQL fragment to truncate a datetime column to day. SQLite only."""
    return f"strftime('%Y-%m-%d', {column})"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

COOKIE_NAME = "pw_admin"
COOKIE_MAX_AGE = 86400  # 24 hours


def cookie_signature(payload: str) -> str:
    """HMAC-sign a cookie payload using the admin key."""
    key = (settings.admin_key or "").encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_cookie(resp: Response, request: Request | None = None) -> Response:
    """Set a signed admin session cookie."""
    ts = str(int(time.time()))
    sig = cookie_signature(ts)
    # Set secure=True for HTTPS, but allow HTTP for local dev/testing
    is_secure = True
    if request:
        host = request.headers.get("host", "")
        scheme = request.url.scheme
        if scheme == "http" or host.startswith("localhost") or host.startswith("127."):
            is_secure = False
    resp.set_cookie(
        COOKIE_NAME,
        f"{ts}.{sig}",
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=is_secure,
        samesite="strict",
    )
    return resp


def verify_cookie(request: Request) -> bool:
    """Verify the admin session cookie is valid and not expired."""
    cookie = request.cookies.get(COOKIE_NAME, "")
    if "." not in cookie:
        return False
    ts_str, sig = cookie.rsplit(".", 1)
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    if time.time() - ts > COOKIE_MAX_AGE:
        return False
    expected = cookie_signature(ts_str)
    return hmac.compare_digest(sig, expected)


async def require_admin(request: Request) -> None:
    """Check admin access via cookie. Redirect to login if not."""
    if not settings.admin_key:
        raise HTTPException(501, "Admin dashboard not configured (set PINCHWORK_ADMIN_KEY)")
    if not verify_cookie(request):
        raise HTTPException(status_code=403, detail="Not authenticated")


AdminAuth = Depends(require_admin)


def csrf_token() -> str:
    """Generate a CSRF token tied to the admin key and current hour."""
    hour = str(int(time.time()) // 3600)
    key = (settings.admin_key or "").encode()
    return hmac.new(key, f"csrf-{hour}".encode(), hashlib.sha256).hexdigest()[:32]


def verify_csrf(token: str) -> bool:
    """Verify CSRF token (accept current hour and previous hour)."""
    current = csrf_token()
    # Also accept previous hour to handle boundary
    prev_hour = str(int(time.time()) // 3600 - 1)
    key = (settings.admin_key or "").encode()
    previous = hmac.new(key, f"csrf-{prev_hour}".encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(token, current) or hmac.compare_digest(token, previous)


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------


def admin_header() -> str:
    """Render the admin navigation header."""
    return """\
<div class="header">
  <span class="title">🦞 PINCHWORK ADMIN</span>
  <span>
    <a href="/admin">overview</a>
    <a href="/admin/tasks">tasks</a>
    <a href="/admin/agents">agents</a>
    <a href="/admin/referrals">referrals</a>
    <a href="/admin/seeder">seeder</a>
    <a href="/admin/stats">stats</a>
    <a href="/human">public</a>
    <a href="/admin/logout">logout</a>
  </span>
</div>"""


def admin_page(title: str, body: str) -> str:
    """Wrap body content in the admin page template."""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{html.escape(title)} — Pinchwork Admin</title>
<link rel="icon" href="/favicon.ico" type="image/svg+xml">
<style>{ADMIN_CSS}</style>
</head>
<body>
<div class="container">
{admin_header()}
{body}
</div>
</body>
</html>"""


def relative_time(dt: datetime) -> str:
    """Format a datetime as relative time (e.g., '5m ago')."""
    now = datetime.now(UTC)
    delta = now.replace(tzinfo=None) - dt if dt.tzinfo is None else now - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


VALID_STATUSES = {"posted", "claimed", "delivered", "approved", "expired", "cancelled"}


def status_class(status: str) -> str:
    """Get CSS class for a task status."""
    if status in VALID_STATUSES:
        return f"status-{status}"
    return "status-unknown"


# ---------------------------------------------------------------------------
# SVG chart helpers (no JS dependencies)
# ---------------------------------------------------------------------------


def svg_bar_chart(
    data: list[tuple[str, int]],
    width: int = 700,
    height: int = 160,
    color: str = "#e94560",
) -> str:
    """Render a simple SVG bar chart. data = [(label, value), ...]."""
    if not data:
        return '<span class="muted">No data yet</span>'
    max_val = max(v for _, v in data) or 1
    n = len(data)
    bar_w = max(2, (width - 40) // n - 1)
    chart_h = height - 30

    bars = []
    for i, (label, val) in enumerate(data):
        x = 30 + i * (bar_w + 1)
        h = int(val / max_val * chart_h) if max_val else 0
        y = chart_h - h + 10
        bars.append(
            f'<rect x="{x}" y="{y}" width="{bar_w}" height="{h}" '
            f'fill="{color}" opacity="0.85">'
            f"<title>{html.escape(label)}: {val}</title></rect>"
        )

    # Y-axis labels
    y_labels = ""
    for frac in (0, 0.5, 1.0):
        val = int(max_val * (1 - frac))
        y = int(10 + chart_h * frac)
        y_labels += (
            f'<text x="26" y="{y + 3}" text-anchor="end" '
            f'fill="#666" font-size="7">{val}</text>'
            f'<line x1="28" y1="{y}" x2="{width}" y2="{y}" '
            f'stroke="#333" stroke-dasharray="2,3"/>'
        )

    # X-axis labels (every Nth)
    x_labels = ""
    step = max(1, n // 8)
    for i in range(0, n, step):
        label, _ = data[i]
        x = 30 + i * (bar_w + 1) + bar_w // 2
        x_labels += (
            f'<text x="{x}" y="{height - 2}" text-anchor="middle" '
            f'fill="#666" font-size="7">{html.escape(label)}</text>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" '
        f'style="width:100%;max-width:{width}px;height:auto">'
        f"{y_labels}{''.join(bars)}{x_labels}</svg>"
    )
