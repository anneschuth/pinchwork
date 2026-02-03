"""Admin dashboard with stats, task details, and time-series charts.

Security: requires PINCHWORK_ADMIN_KEY. Uses a signed cookie for
browser sessions so you don't re-enter the key on every page load.

Note: Date grouping uses SQLite-specific strftime(). For PostgreSQL
support, these would need to be replaced with date_trunc() or to_char().
See admin_helpers.sql_date_hour() and sql_date_day().
"""

from __future__ import annotations

import html
import json
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from pinchwork.config import settings
from pinchwork.database import get_db_session
from pinchwork.db_models import (
    Agent,
    CreditLedger,
    Rating,
    Report,
    Task,
    TaskMessage,
    TaskQuestion,
)
from pinchwork.rate_limit import limiter

from .admin_helpers import (
    COOKIE_NAME,
    AdminAuth,
    admin_page,
    csrf_token,
    make_cookie,
    relative_time,
    sql_date_day,
    sql_date_hour,
    status_class,
    svg_bar_chart,
    verify_csrf,
)
from .admin_styles import ADMIN_CSS

router = APIRouter()


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------


@router.get("/admin/login", include_in_schema=False, response_class=HTMLResponse)
async def admin_login_page(error: str = ""):
    if not settings.admin_key:
        return HTMLResponse("Admin not configured (set PINCHWORK_ADMIN_KEY)", status_code=501)
    error_html = f'<div class="login-error">{html.escape(error)}</div>' if error else ""
    csrf = csrf_token()
    return HTMLResponse(f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Admin Login — Pinchwork</title>
<link rel="icon" href="/favicon.ico" type="image/svg+xml">
<style>{ADMIN_CSS}</style>
</head>
<body>
<div class="login-box">
  <h2>🦞 Admin Login</h2>
  {error_html}
  <form method="POST" action="/admin/login">
    <input type="hidden" name="csrf" value="{csrf}">
    <input type="password" name="key" placeholder="Admin key" autofocus>
    <button type="submit">Login</button>
  </form>
</div>
</body>
</html>""")


@router.post("/admin/login", include_in_schema=False)
@limiter.limit("5/minute")
async def admin_login_submit(request: Request):
    if not settings.admin_key:
        return HTMLResponse("Admin not configured", status_code=501)
    form = await request.form()
    csrf = str(form.get("csrf", ""))
    if not verify_csrf(csrf):
        return RedirectResponse("/admin/login?error=Invalid+request", status_code=303)
    key = form.get("key", "")
    if not secrets.compare_digest(str(key), settings.admin_key):
        return RedirectResponse("/admin/login?error=Invalid+admin+key", status_code=303)
    resp = RedirectResponse("/admin", status_code=303)
    return make_cookie(resp, request)


@router.get("/admin/logout", include_in_schema=False)
async def admin_logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ---------------------------------------------------------------------------
# Overview dashboard
# ---------------------------------------------------------------------------


@router.get("/admin", include_in_schema=False, response_class=HTMLResponse)
async def admin_overview(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _=AdminAuth,
):
    # Core stats
    agent_count = (
        await session.execute(
            select(func.count()).select_from(Agent).where(Agent.id != settings.platform_agent_id)
        )
    ).scalar() or 0

    infra_count = (
        await session.execute(
            select(func.count())
            .select_from(Agent)
            .where(
                Agent.id != settings.platform_agent_id,
                Agent.accepts_system_tasks == True,  # noqa: E712
            )
        )
    ).scalar() or 0

    suspended_count = (
        await session.execute(
            select(func.count()).select_from(Agent).where(Agent.suspended == True)  # noqa: E712
        )
    ).scalar() or 0

    # Task stats by status
    status_rows = (
        await session.execute(select(Task.status, func.count()).group_by(Task.status))
    ).all()
    task_by_status = dict(status_rows)
    total_tasks = sum(task_by_status.values())

    # Credit stats
    credits_moved = (
        await session.execute(
            select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(CreditLedger.amount > 0)
        )
    ).scalar() or 0

    rating_count = (await session.execute(select(func.count()).select_from(Rating))).scalar() or 0

    report_count = (
        await session.execute(
            select(func.count()).select_from(Report).where(Report.status == "open")
        )
    ).scalar() or 0

    # Referral stats
    referred_count = (
        await session.execute(
            select(func.count())
            .select_from(Agent)
            .where(
                Agent.referred_by != None  # noqa: E711
            )
        )
    ).scalar() or 0

    # --- Time-series data ---

    # Tasks created per hour (last 48h)
    cutoff_48h = datetime.now(UTC) - timedelta(hours=48)
    tasks_per_hour_raw = (
        await session.execute(
            text(
                f"SELECT {sql_date_hour('created_at')} as hour, COUNT(*) "
                "FROM tasks WHERE created_at >= :cutoff "
                "GROUP BY hour ORDER BY hour"
            ),
            {"cutoff": cutoff_48h.isoformat()},
        )
    ).all()
    tasks_per_hour = [(h.split(" ")[1] + "h", c) for h, c in tasks_per_hour_raw]

    # Agents registered per day (last 30d)
    cutoff_30d = datetime.now(UTC) - timedelta(days=30)
    agents_per_day_raw = (
        await session.execute(
            text(
                f"SELECT {sql_date_day('created_at')} as day, COUNT(*) "
                "FROM agents WHERE created_at >= :cutoff "
                "AND id != :platform "
                "GROUP BY day ORDER BY day"
            ),
            {"cutoff": cutoff_30d.isoformat(), "platform": settings.platform_agent_id},
        )
    ).all()
    agents_per_day = [(d[5:], c) for d, c in agents_per_day_raw]  # MM-DD format

    # Credits moved per day (last 30d)
    credits_per_day_raw = (
        await session.execute(
            text(
                f"SELECT {sql_date_day('created_at')} as day, "
                "SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) "
                "FROM credit_ledger WHERE created_at >= :cutoff "
                "GROUP BY day ORDER BY day"
            ),
            {"cutoff": cutoff_30d.isoformat()},
        )
    ).all()
    credits_per_day = [(d[5:], int(c or 0)) for d, c in credits_per_day_raw]

    # Task completions per hour (last 48h)
    completions_per_hour_raw = (
        await session.execute(
            text(
                f"SELECT {sql_date_hour('delivered_at')} as hour, COUNT(*) "
                "FROM tasks WHERE status = 'approved' AND delivered_at >= :cutoff "
                "GROUP BY hour ORDER BY hour"
            ),
            {"cutoff": cutoff_48h.isoformat()},
        )
    ).all()
    completions_per_hour = [(h.split(" ")[1] + "h", c) for h, c in completions_per_hour_raw]

    # Recent tasks (last 10)
    recent_result = await session.execute(
        select(Task).order_by(col(Task.created_at).desc()).limit(10)
    )
    recent_tasks = recent_result.all()

    recent_rows = ""
    for (task,) in recent_tasks:
        need = html.escape((task.need or "")[:60])
        status = task.status.value if hasattr(task.status, "value") else task.status
        ago = relative_time(task.created_at)
        sys_badge = ' <span class="tag">sys</span>' if task.is_system else ""
        recent_rows += (
            f"<tr>"
            f'<td class="mono"><a href="/admin/tasks/{html.escape(task.id)}">'
            f"{html.escape(task.id[:16])}</a></td>"
            f"<td>{need}{sys_badge}</td>"
            f'<td class="{status_class(status)}">{status}</td>'
            f'<td class="right">{task.max_credits}</td>'
            f'<td class="muted">{ago}</td>'
            f"</tr>"
        )

    body = f"""\
<div class="section">
  <h2>Overview</h2>
  <div class="stats-grid">
    <div class="stat-card">
      <div class="number">{agent_count}</div>
      <div class="label">Agents</div>
    </div>
    <div class="stat-card">
      <div class="number">{infra_count}</div>
      <div class="label">Infra</div>
    </div>
    <div class="stat-card">
      <div class="number">{suspended_count}</div>
      <div class="label">Suspended</div>
    </div>
    <div class="stat-card">
      <div class="number">{total_tasks}</div>
      <div class="label">Total Tasks</div>
    </div>
    <div class="stat-card">
      <div class="number">{task_by_status.get("approved", 0)}</div>
      <div class="label">Completed</div>
    </div>
    <div class="stat-card">
      <div class="number">{task_by_status.get("posted", 0)}</div>
      <div class="label">Open</div>
    </div>
    <div class="stat-card">
      <div class="number">{credits_moved:,}</div>
      <div class="label">Credits Moved</div>
    </div>
    <div class="stat-card">
      <div class="number">{rating_count}</div>
      <div class="label">Ratings</div>
    </div>
    <div class="stat-card">
      <div class="number">{report_count}</div>
      <div class="label">Open Reports</div>
    </div>
    <div class="stat-card">
      <div class="number">{referred_count}</div>
      <div class="label">Referred</div>
    </div>
  </div>
</div>

<div class="section">
  <h2>Activity (Last 48h)</h2>
  <div class="chart-container">
    <div class="chart-title">Tasks Created per Hour</div>
    {svg_bar_chart(tasks_per_hour, color="#4da6ff")}
  </div>
  <div class="chart-container">
    <div class="chart-title">Tasks Completed per Hour</div>
    {svg_bar_chart(completions_per_hour, color="#22c55e")}
  </div>
</div>

<div class="section">
  <h2>Growth (Last 30d)</h2>
  <div class="chart-container">
    <div class="chart-title">Agent Registrations per Day</div>
    {svg_bar_chart(agents_per_day, color="#a855f7")}
  </div>
  <div class="chart-container">
    <div class="chart-title">Credits Moved per Day</div>
    {svg_bar_chart(credits_per_day, color="#ff9f43")}
  </div>
</div>

<div class="section">
  <h2>Recent Tasks</h2>
  <table>
    <tr>
      <th>ID</th>
      <th>Need</th>
      <th>Status</th>
      <th class="right">Credits</th>
      <th>When</th>
    </tr>
    {recent_rows}
  </table>
  <div style="margin-top:10px"><a href="/admin/tasks">View all tasks →</a></div>
</div>"""

    return HTMLResponse(admin_page("Overview", body))


# ---------------------------------------------------------------------------
# Task list
# ---------------------------------------------------------------------------


@router.get("/admin/tasks", include_in_schema=False, response_class=HTMLResponse)
async def admin_tasks(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _=AdminAuth,
    status: str | None = None,
    system: str | None = None,
    page: int = 1,
):
    per_page = 50
    offset = (max(1, page) - 1) * per_page

    query = select(Task)
    count_query = select(func.count()).select_from(Task)

    if status:
        query = query.where(Task.status == status)
        count_query = count_query.where(Task.status == status)
    if system == "hide":
        query = query.where(Task.is_system == False)  # noqa: E712
        count_query = count_query.where(Task.is_system == False)  # noqa: E712
    elif system == "only":
        query = query.where(Task.is_system == True)  # noqa: E712
        count_query = count_query.where(Task.is_system == True)  # noqa: E712

    total = (await session.execute(count_query)).scalar() or 0
    total_pages = max(1, (total + per_page - 1) // per_page)

    result = await session.execute(
        query.order_by(col(Task.created_at).desc()).offset(offset).limit(per_page)
    )
    tasks = result.all()

    rows = ""
    for (task,) in tasks:
        need = html.escape((task.need or "")[:70])
        st = task.status.value if hasattr(task.status, "value") else task.status
        ago = relative_time(task.created_at)
        poster = html.escape(task.poster_id[:16])
        worker = html.escape((task.worker_id or "—")[:16])
        sys_badge = ' <span class="tag">sys</span>' if task.is_system else ""
        rows += (
            f"<tr>"
            f'<td class="mono"><a href="/admin/tasks/{html.escape(task.id)}">'
            f"{html.escape(task.id[:16])}</a></td>"
            f"<td>{need}{sys_badge}</td>"
            f'<td class="{status_class(st)}">{st}</td>'
            f'<td class="right">{task.max_credits}</td>'
            f'<td class="mono">{poster}</td>'
            f'<td class="mono">{worker}</td>'
            f'<td class="muted">{ago}</td>'
            f"</tr>"
        )

    # Filters
    current_status = status or ""
    current_system = system or ""
    filter_html = '<div style="margin-bottom:12px;font-size:9pt">'
    filter_html += "Status: "
    for s in ["", "posted", "claimed", "delivered", "approved", "expired", "cancelled"]:
        label = s or "all"
        active = ' style="color:#e94560;font-weight:bold"' if s == current_status else ""
        qs = f"?status={s}" if s else "?"
        if current_system:
            qs += f"&system={current_system}"
        filter_html += f' <a href="/admin/tasks{qs}"{active}>{label}</a>'
    filter_html += " &middot; System: "
    for sv, sl in [("", "all"), ("hide", "hide"), ("only", "only")]:
        active = ' style="color:#e94560;font-weight:bold"' if sv == current_system else ""
        qs = f"?system={sv}" if sv else "?"
        if current_status:
            qs += f"&status={current_status}"
        filter_html += f' <a href="/admin/tasks{qs}"{active}>{sl}</a>'
    filter_html += "</div>"

    # Pagination - preserve filters
    filter_qs = ""
    if current_status:
        filter_qs += f"&status={current_status}"
    if current_system:
        filter_qs += f"&system={current_system}"

    pag = '<div class="pagination">'
    if page > 1:
        pag += f'<a href="/admin/tasks?page={page - 1}{filter_qs}">← prev</a>'
    pag += f'<span class="current">{page} / {total_pages}</span>'
    if page < total_pages:
        pag += f'<a href="/admin/tasks?page={page + 1}{filter_qs}">next →</a>'
    pag += f' <span class="muted">({total} total)</span></div>'

    body = f"""\
<div class="section">
  <h2>Tasks</h2>
  {filter_html}
  <table>
    <tr>
      <th>ID</th>
      <th>Need</th>
      <th>Status</th>
      <th class="right">Credits</th>
      <th>Poster</th>
      <th>Worker</th>
      <th>Created</th>
    </tr>
    {rows}
  </table>
  {pag}
</div>"""

    return HTMLResponse(admin_page("Tasks", body))


# ---------------------------------------------------------------------------
# Task detail
# ---------------------------------------------------------------------------


@router.get("/admin/tasks/{task_id}", include_in_schema=False, response_class=HTMLResponse)
async def admin_task_detail(
    task_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _=AdminAuth,
):
    result = await session.execute(select(Task).where(Task.id == task_id))
    row = result.first()
    if not row:
        return HTMLResponse(
            admin_page("Not Found", '<div class="section">Task not found.</div>'),
            status_code=404,
        )

    task = row[0]
    status = task.status.value if hasattr(task.status, "value") else task.status
    need = html.escape(task.need or "")
    result_text = html.escape(task.result or "—")
    context = html.escape(task.context or "—")
    tags = ""
    if task.tags:
        try:
            for t in json.loads(task.tags):
                tags += f'<span class="tag">{html.escape(str(t))}</span>'
        except (json.JSONDecodeError, TypeError):
            tags = html.escape(task.tags)

    extracted = ""
    if task.extracted_tags:
        try:
            for t in json.loads(task.extracted_tags):
                extracted += f'<span class="tag">{html.escape(str(t))}</span>'
        except (json.JSONDecodeError, TypeError):
            pass

    # Messages
    msgs_result = await session.execute(
        select(TaskMessage)
        .where(TaskMessage.task_id == task_id)
        .order_by(col(TaskMessage.created_at))
    )
    messages = msgs_result.all()
    msgs_html = ""
    for (msg,) in messages:
        msgs_html += (
            f'<div style="margin-bottom:8px">'
            f'<span class="mono">{html.escape(msg.sender_id[:16])}</span> '
            f'<span class="muted">{relative_time(msg.created_at)}</span>'
            f'<div style="margin-top:2px">{html.escape(msg.message)}</div>'
            f"</div>"
        )
    if not messages:
        msgs_html = '<span class="muted">No messages</span>'

    # Questions
    qs_result = await session.execute(
        select(TaskQuestion)
        .where(TaskQuestion.task_id == task_id)
        .order_by(col(TaskQuestion.created_at))
    )
    questions = qs_result.all()
    qs_html = ""
    for (q,) in questions:
        answer = html.escape(q.answer or "—")
        qs_html += (
            f'<div style="margin-bottom:8px">'
            f'<span class="mono">{html.escape(q.asker_id[:16])}</span> '
            f'<span class="muted">{relative_time(q.created_at)}</span>'
            f"<div><b>Q:</b> {html.escape(q.question)}</div>"
            f"<div><b>A:</b> {answer}</div>"
            f"</div>"
        )
    if not questions:
        qs_html = '<span class="muted">No questions</span>'

    # Verification
    verif_html = ""
    if task.verification_status:
        v_status = task.verification_status
        if hasattr(v_status, "value"):
            v_status = v_status.value
        verif_html = f"""\
    <div class="detail-row">
      <div class="detail-label">Verification</div>
      <div class="detail-value">{html.escape(str(v_status))}</div>
    </div>"""
        if task.verification_result:
            verif_html += f"""\
    <div class="detail-row">
      <div class="detail-label">Verification Result</div>
      <div class="detail-value need-full">{html.escape(task.verification_result)}</div>
    </div>"""

    rejection_html = ""
    if task.rejection_count > 0:
        rejection_html = f"""\
    <div class="detail-row">
      <div class="detail-label">Rejections</div>
      <div class="detail-value">{task.rejection_count}
        {f" — {html.escape(task.rejection_reason or '')}" if task.rejection_reason else ""}</div>
    </div>"""

    body = f"""\
<div class="section">
  <div style="margin-bottom:10px"><a href="/admin/tasks">← back to tasks</a></div>
  <h2>Task Detail</h2>

  <div class="detail-row">
    <div class="detail-label">Task ID</div>
    <div class="detail-value mono">{html.escape(task.id)}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Status</div>
    <div class="detail-value"><span class="{status_class(status)}">{status}</span></div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Credits</div>
    <div class="detail-value">{task.max_credits}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Poster</div>
    <div class="detail-value mono">
      <a href="/admin/agents/{html.escape(task.poster_id)}">{html.escape(task.poster_id)}</a>
    </div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Worker</div>
    <div class="detail-value mono">
      {
        f'<a href="/admin/agents/{html.escape(task.worker_id)}">{html.escape(task.worker_id)}</a>'
        if task.worker_id
        else "—"
    }</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">System Task</div>
    <div class="detail-value">{
        "Yes — " + html.escape(task.system_task_type or "unknown") if task.is_system else "No"
    }</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Tags</div>
    <div class="detail-value">{tags or "—"}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Extracted Tags</div>
    <div class="detail-value">{extracted or "—"}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Created</div>
    <div class="detail-value">{task.created_at.isoformat() if task.created_at else "—"}
      ({relative_time(task.created_at) if task.created_at else ""})</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Claimed</div>
    <div class="detail-value">{task.claimed_at.isoformat() if task.claimed_at else "—"}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Delivered</div>
    <div class="detail-value">{task.delivered_at.isoformat() if task.delivered_at else "—"}</div>
  </div>

  {verif_html}
  {rejection_html}

  <div class="detail-row" style="margin-top:16px">
    <div class="detail-label">Context</div>
    <div class="detail-value need-full">{context}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Need</div>
    <div class="detail-value need-full">{need}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Result</div>
    <div class="detail-value need-full">{result_text}</div>
  </div>

  <div class="detail-row" style="margin-top:16px">
    <div class="detail-label">Messages ({len(messages)})</div>
    <div class="detail-value">{msgs_html}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Questions ({len(questions)})</div>
    <div class="detail-value">{qs_html}</div>
  </div>
</div>"""

    return HTMLResponse(admin_page(f"Task {task_id[:16]}", body))


# ---------------------------------------------------------------------------
# Agent list
# ---------------------------------------------------------------------------


@router.get("/admin/agents", include_in_schema=False, response_class=HTMLResponse)
async def admin_agents(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _=AdminAuth,
    sort: str = "tasks",
    page: int = 1,
):
    per_page = 50
    offset = (max(1, page) - 1) * per_page

    count_total = (
        await session.execute(
            select(func.count()).select_from(Agent).where(Agent.id != settings.platform_agent_id)
        )
    ).scalar() or 0
    total_pages = max(1, (count_total + per_page - 1) // per_page)

    order = col(Agent.tasks_completed).desc()
    if sort == "credits":
        order = col(Agent.credits).desc()
    elif sort == "recent":
        order = col(Agent.created_at).desc()
    elif sort == "reputation":
        order = col(Agent.reputation).desc()

    result = await session.execute(
        select(Agent)
        .where(Agent.id != settings.platform_agent_id)
        .order_by(order)
        .offset(offset)
        .limit(per_page)
    )
    agents = result.all()

    rows = ""
    for (agent,) in agents:
        name = html.escape(agent.name or agent.id[:12])
        badges = ""
        if agent.accepts_system_tasks:
            badges += ' <span class="tag badge-infra">infra</span>'
        if agent.suspended:
            badges += ' <span class="tag badge-suspended">suspended</span>'
        rep = agent.reputation
        rep_color = "#22c55e" if rep > 0 else "#ff4d4d" if rep < 0 else "#666"
        rep_str = f"+{rep:.1f}" if rep > 0 else f"{rep:.1f}" if rep < 0 else "0"
        ago = relative_time(agent.created_at)
        referred = "✓" if agent.referred_by else ""
        rows += (
            f"<tr>"
            f'<td><a href="/admin/agents/{html.escape(agent.id)}">'
            f"<b>{name}</b></a>{badges}</td>"
            f'<td class="right">{agent.credits}</td>'
            f'<td class="right">{agent.tasks_completed}</td>'
            f'<td class="right">{agent.tasks_posted}</td>'
            f'<td class="right" style="color:{rep_color}">{rep_str}</td>'
            f'<td class="muted" style="text-align:center">{referred}</td>'
            f'<td class="muted">{ago}</td>'
            f"</tr>"
        )

    # Sort links
    sort_html = '<div style="margin-bottom:12px;font-size:9pt">Sort: '
    for sv, sl in [
        ("tasks", "tasks"),
        ("credits", "credits"),
        ("recent", "recent"),
        ("reputation", "rep"),
    ]:
        active = ' style="color:#e94560;font-weight:bold"' if sv == sort else ""
        sort_html += f' <a href="/admin/agents?sort={sv}"{active}>{sl}</a>'
    sort_html += "</div>"

    pag = '<div class="pagination">'
    if page > 1:
        pag += f'<a href="/admin/agents?page={page - 1}&sort={sort}">← prev</a>'
    pag += f'<span class="current">{page} / {total_pages}</span>'
    if page < total_pages:
        pag += f'<a href="/admin/agents?page={page + 1}&sort={sort}">next →</a>'
    pag += f' <span class="muted">({count_total} total)</span></div>'

    body = f"""\
<div class="section">
  <h2>Agents</h2>
  {sort_html}
  <table>
    <tr>
      <th>Agent</th>
      <th class="right">Credits</th>
      <th class="right">Done</th>
      <th class="right">Posted</th>
      <th class="right">Rep</th>
      <th>Ref</th>
      <th>Joined</th>
    </tr>
    {rows}
  </table>
  {pag}
</div>"""

    return HTMLResponse(admin_page("Agents", body))


# ---------------------------------------------------------------------------
# Agent detail
# ---------------------------------------------------------------------------


@router.get("/admin/agents/{agent_id}", include_in_schema=False, response_class=HTMLResponse)
async def admin_agent_detail(
    agent_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _=AdminAuth,
):
    result = await session.execute(select(Agent).where(Agent.id == agent_id))
    row = result.first()
    if not row:
        return HTMLResponse(
            admin_page("Not Found", '<div class="section">Agent not found.</div>'),
            status_code=404,
        )

    agent = row[0]
    name = html.escape(agent.name or agent.id[:12])
    good_at = html.escape(agent.good_at or "—")

    tags = ""
    if agent.capability_tags:
        try:
            for t in json.loads(agent.capability_tags):
                tags += f'<span class="tag">{html.escape(str(t))}</span>'
        except (json.JSONDecodeError, TypeError):
            pass

    badges = ""
    if agent.accepts_system_tasks:
        badges += ' <span class="tag badge-infra">infra</span>'
    if agent.suspended:
        reason = html.escape(agent.suspend_reason or "unknown")
        badges += f' <span class="tag badge-suspended">suspended: {reason}</span>'

    rep = agent.reputation
    rep_color = "#22c55e" if rep > 0 else "#ff4d4d" if rep < 0 else "#666"
    rep_str = f"+{rep:.1f}" if rep > 0 else f"{rep:.1f}" if rep < 0 else "0"

    # Recent tasks by this agent (as poster and worker)
    task_result = await session.execute(
        select(Task)
        .where((Task.poster_id == agent_id) | (Task.worker_id == agent_id))
        .order_by(col(Task.created_at).desc())
        .limit(20)
    )
    tasks = task_result.all()

    task_rows = ""
    for (task,) in tasks:
        need = html.escape((task.need or "")[:50])
        st = task.status.value if hasattr(task.status, "value") else task.status
        ago = relative_time(task.created_at)
        role = "poster" if task.poster_id == agent_id else "worker"
        task_rows += (
            f"<tr>"
            f'<td class="mono"><a href="/admin/tasks/{html.escape(task.id)}">'
            f"{html.escape(task.id[:16])}</a></td>"
            f"<td>{need}</td>"
            f'<td class="{status_class(st)}">{st}</td>'
            f"<td>{role}</td>"
            f'<td class="right">{task.max_credits}</td>'
            f'<td class="muted">{ago}</td>'
            f"</tr>"
        )

    # Credit ledger
    ledger_result = await session.execute(
        select(CreditLedger)
        .where(CreditLedger.agent_id == agent_id)
        .order_by(col(CreditLedger.created_at).desc())
        .limit(20)
    )
    ledger = ledger_result.all()

    ledger_rows = ""
    for (entry,) in ledger:
        color = "#22c55e" if entry.amount > 0 else "#ff4d4d"
        sign = "+" if entry.amount > 0 else ""
        ago = relative_time(entry.created_at)
        ledger_rows += (
            f"<tr>"
            f'<td style="color:{color};font-weight:bold">{sign}{entry.amount}</td>'
            f"<td>{html.escape(entry.reason)}</td>"
            f'<td class="mono">{html.escape(entry.task_id or "—")[:16]}</td>'
            f'<td class="muted">{ago}</td>'
            f"</tr>"
        )

    body = f"""\
<div class="section">
  <div style="margin-bottom:10px"><a href="/admin/agents">← back to agents</a></div>
  <h2>Agent: {name}{badges}</h2>

  <div class="detail-row">
    <div class="detail-label">Agent ID</div>
    <div class="detail-value mono">{html.escape(agent.id)}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Credits</div>
    <div class="detail-value" style="font-size:14pt;font-weight:bold;color:#e94560">
      {agent.credits}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Reputation</div>
    <div class="detail-value" style="color:{rep_color};font-weight:bold">{rep_str}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Tasks Completed / Posted</div>
    <div class="detail-value">{agent.tasks_completed} / {agent.tasks_posted}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Good At</div>
    <div class="detail-value">{good_at}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Capability Tags</div>
    <div class="detail-value">{tags or "—"}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Referral Code</div>
    <div class="detail-value mono">{html.escape(agent.referral_code or "—")}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Referred By</div>
    <div class="detail-value mono">{html.escape(agent.referred_by or "—")}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Webhook</div>
    <div class="detail-value mono">{html.escape(agent.webhook_url or "—")}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Joined</div>
    <div class="detail-value">{agent.created_at.isoformat() if agent.created_at else "—"}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Abandons</div>
    <div class="detail-value">{agent.abandon_count}</div>
  </div>
</div>

<div class="section">
  <h2>Recent Tasks ({len(tasks)})</h2>
  <table>
    <tr>
      <th>ID</th>
      <th>Need</th>
      <th>Status</th>
      <th>Role</th>
      <th class="right">Credits</th>
      <th>When</th>
    </tr>
    {task_rows or '<tr><td colspan="6" class="muted">No tasks</td></tr>'}
  </table>
</div>

<div class="section">
  <h2>Credit Ledger (Recent {len(ledger)})</h2>
  <table>
    <tr>
      <th>Amount</th>
      <th>Reason</th>
      <th>Task</th>
      <th>When</th>
    </tr>
    {ledger_rows or '<tr><td colspan="4" class="muted">No transactions</td></tr>'}
  </table>
</div>"""

    return HTMLResponse(admin_page(f"Agent: {name}", body))


# ---------------------------------------------------------------------------
# Referrals & Welcome Tasks
# ---------------------------------------------------------------------------


@router.get("/admin/referrals", include_in_schema=False, response_class=HTMLResponse)
async def admin_referrals(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _=AdminAuth,
):
    # Get all agents with referral data
    all_agents_result = await session.execute(
        select(Agent).where(Agent.id != settings.platform_agent_id)
    )
    all_agents = {a.id: a for (a,) in all_agents_result.all()}

    # Build referral code -> agent mapping
    code_to_agent: dict[str, Agent] = {}
    for agent in all_agents.values():
        if agent.referral_code:
            code_to_agent[agent.referral_code] = agent

    # Find agents who used referral codes (were referred)
    referred_agents = [a for a in all_agents.values() if a.referred_by]

    # Find successful referrers (agents whose codes were used)
    referrer_counts: dict[str, int] = {}
    for agent in referred_agents:
        referrer_counts[agent.referred_by] = referrer_counts.get(agent.referred_by, 0) + 1

    # Get agents who completed their first task (proxy for "welcome task done")
    # First task = claimed and delivered/approved any task
    first_task_agents_result = await session.execute(
        select(Task.worker_id)
        .where(
            Task.worker_id != None,  # noqa: E711
            Task.status.in_(["delivered", "approved"]),
        )
        .group_by(Task.worker_id)
    )
    agents_with_completed_tasks = {row[0] for row in first_task_agents_result.all()}

    # Identify likely test accounts (heuristics):
    # - Name contains "test" (case insensitive)
    # - Created within first hour of platform launch (if we knew launch time)
    # - Specific known test agent IDs
    test_patterns = ["test", "demo", "example", "sample"]
    likely_test_agents = [
        a for a in all_agents.values() if any(p in (a.name or "").lower() for p in test_patterns)
    ]

    # --- Build HTML ---

    # Referrals used section
    referrals_rows = ""
    for agent in sorted(referred_agents, key=lambda a: a.created_at or datetime.min, reverse=True):
        referrer = code_to_agent.get(agent.referred_by or "")
        referrer_name = html.escape(referrer.name if referrer else "Unknown")
        referrer_link = (
            f'<a href="/admin/agents/{html.escape(referrer.id)}">{referrer_name}</a>'
            if referrer
            else referrer_name
        )
        ago = relative_time(agent.created_at) if agent.created_at else "—"
        done_badge = (
            ' <span class="tag" style="background:#1a5e3a;color:#4dff88">✓ done</span>'
            if agent.id in agents_with_completed_tasks
            else ""
        )
        aid = html.escape(agent.id)
        aname = html.escape(agent.name)
        referrals_rows += (
            f"<tr>"
            f'<td><a href="/admin/agents/{aid}"><b>{aname}</b></a>{done_badge}</td>'
            f"<td>{referrer_link}</td>"
            f'<td class="mono">{html.escape(agent.referred_by or "")}</td>'
            f'<td class="muted">{ago}</td>'
            f"</tr>"
        )

    # Successful referrers section
    referrers_rows = ""
    for code, count in sorted(referrer_counts.items(), key=lambda x: -x[1]):
        referrer = code_to_agent.get(code)
        if referrer:
            rid = html.escape(referrer.id)
            rname = html.escape(referrer.name)
            rago = relative_time(referrer.created_at) if referrer.created_at else "—"
            referrers_rows += (
                f"<tr>"
                f'<td><a href="/admin/agents/{rid}"><b>{rname}</b></a></td>'
                f'<td class="mono">{html.escape(code)}</td>'
                f'<td class="right" style="font-weight:bold;color:#e94560">{count}</td>'
                f'<td class="muted">{rago}</td>'
                f"</tr>"
            )
        else:
            referrers_rows += (
                f"<tr>"
                f"<td><i>Unknown</i></td>"
                f'<td class="mono">{html.escape(code)}</td>'
                f'<td class="right" style="font-weight:bold;color:#e94560">{count}</td>'
                f"<td>—</td>"
                f"</tr>"
            )

    # Welcome task completers
    welcome_rows = ""
    for agent in sorted(
        [a for a in all_agents.values() if a.id in agents_with_completed_tasks],
        key=lambda a: a.created_at or datetime.min,
        reverse=True,
    )[:50]:
        referred_badge = (
            ' <span class="tag" style="background:#1a3a5e;color:#4da6ff">ref</span>'
            if agent.referred_by
            else ""
        )
        ago = relative_time(agent.created_at) if agent.created_at else "—"
        aid = html.escape(agent.id)
        aname = html.escape(agent.name)
        welcome_rows += (
            f"<tr>"
            f'<td><a href="/admin/agents/{aid}"><b>{aname}</b></a>{referred_badge}</td>'
            f'<td class="right">{agent.tasks_completed}</td>'
            f'<td class="right">{agent.credits}</td>'
            f'<td class="muted">{ago}</td>'
            f"</tr>"
        )

    # Test accounts section
    test_rows = ""
    for agent in sorted(
        likely_test_agents, key=lambda a: a.created_at or datetime.min, reverse=True
    ):
        ago = relative_time(agent.created_at) if agent.created_at else "—"
        aid = html.escape(agent.id)
        aname = html.escape(agent.name)
        test_rows += (
            f"<tr>"
            f'<td><a href="/admin/agents/{aid}"><b>{aname}</b></a></td>'
            f'<td class="mono">{html.escape(agent.id[:16])}</td>'
            f'<td class="right">{agent.credits}</td>'
            f'<td class="muted">{ago}</td>'
            f"</tr>"
        )

    body = f"""\
<div class="section">
  <h2>Referrals Overview</h2>
  <div class="stats-grid">
    <div class="stat-card">
      <div class="number">{len(referred_agents)}</div>
      <div class="label">Referred Agents</div>
    </div>
    <div class="stat-card">
      <div class="number">{len(referrer_counts)}</div>
      <div class="label">Active Referrers</div>
    </div>
    <div class="stat-card">
      <div class="number">{len(agents_with_completed_tasks)}</div>
      <div class="label">Completed Task</div>
    </div>
    <div class="stat-card">
      <div class="number">{len(likely_test_agents)}</div>
      <div class="label">Likely Test</div>
    </div>
  </div>
</div>

<div class="section">
  <h2>Successful Referrers</h2>
  <p class="muted" style="margin-bottom:10px">Agents whose referral codes were used.</p>
  <table>
    <tr>
      <th>Referrer</th>
      <th>Code</th>
      <th class="right">Count</th>
      <th>Joined</th>
    </tr>
    {referrers_rows or '<tr><td colspan="4" class="muted">No referrals yet</td></tr>'}
  </table>
</div>

<div class="section">
  <h2>Referred Agents ({len(referred_agents)})</h2>
  <p class="muted" style="margin-bottom:10px">Used referral code. Green = completed task.</p>
  <table>
    <tr>
      <th>Agent</th>
      <th>Referred By</th>
      <th>Code Used</th>
      <th>Joined</th>
    </tr>
    {referrals_rows or '<tr><td colspan="4" class="muted">No referred agents</td></tr>'}
  </table>
</div>

<div class="section">
  <h2>Welcome Task Completers (Recent 50)</h2>
  <p class="muted" style="margin-bottom:10px">Completed 1+ tasks. Blue = used referral.</p>
  <table>
    <tr>
      <th>Agent</th>
      <th class="right">Tasks Done</th>
      <th class="right">Credits</th>
      <th>Joined</th>
    </tr>
    {welcome_rows or '<tr><td colspan="4" class="muted">No completers yet</td></tr>'}
  </table>
</div>

<div class="section">
  <h2>Likely Test Accounts ({len(likely_test_agents)})</h2>
  <p class="muted" style="margin-bottom:10px">Names with: test, demo, example, sample.</p>
  <table>
    <tr>
      <th>Agent</th>
      <th>ID</th>
      <th class="right">Credits</th>
      <th>Joined</th>
    </tr>
    {test_rows or '<tr><td colspan="4" class="muted">No test accounts detected</td></tr>'}
  </table>
</div>"""

    return HTMLResponse(admin_page("Referrals & Welcome", body))


# ---------------------------------------------------------------------------
# Route Statistics
# ---------------------------------------------------------------------------


@router.get("/admin/stats", include_in_schema=False, response_class=HTMLResponse)
async def admin_stats(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _=AdminAuth,
    prefix: str = "",
):
    # Time ranges
    now = datetime.now(UTC)
    cutoff_48h = now - timedelta(hours=48)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    # Total stats (all time)
    total_result = await session.execute(
        text("""
            SELECT
                COUNT(DISTINCT route) as routes,
                SUM(request_count) as requests,
                SUM(error_4xx) as errors_4xx,
                SUM(error_5xx) as errors_5xx,
                SUM(total_ms) as total_ms
            FROM route_stats
            WHERE route LIKE :prefix
        """),
        {"prefix": f"{prefix}%"},
    )
    totals = total_result.first()
    total_requests = totals[1] or 0
    total_4xx = totals[2] or 0
    total_5xx = totals[3] or 0
    total_ms = totals[4] or 0
    avg_ms = int(total_ms / total_requests) if total_requests else 0
    error_rate = (total_4xx + total_5xx) / total_requests * 100 if total_requests else 0

    # Last 24h stats
    last_24h_result = await session.execute(
        text("""
            SELECT SUM(request_count), SUM(error_4xx), SUM(error_5xx)
            FROM route_stats
            WHERE hour >= :cutoff AND route LIKE :prefix
        """),
        {"cutoff": (now - timedelta(hours=24)).isoformat(), "prefix": f"{prefix}%"},
    )
    last_24h = last_24h_result.first()
    requests_24h = last_24h[0] or 0

    # Top routes by traffic (last 7d)
    top_routes_result = await session.execute(
        text("""
            SELECT
                route,
                SUM(request_count) as reqs,
                SUM(error_4xx + error_5xx) as errors,
                ROUND(AVG(total_ms * 1.0 / request_count), 1) as avg_ms
            FROM route_stats
            WHERE hour >= :cutoff AND route LIKE :prefix
            GROUP BY route
            ORDER BY reqs DESC
            LIMIT 25
        """),
        {"cutoff": cutoff_7d.isoformat(), "prefix": f"{prefix}%"},
    )
    top_routes = top_routes_result.all()

    # Requests per hour (last 48h)
    hourly_result = await session.execute(
        text(f"""
            SELECT {sql_date_hour("hour")} as h, SUM(request_count)
            FROM route_stats
            WHERE hour >= :cutoff AND route LIKE :prefix
            GROUP BY h
            ORDER BY h
        """),
        {"cutoff": cutoff_48h.isoformat(), "prefix": f"{prefix}%"},
    )
    hourly_data = [(h.split(" ")[1] + "h", c) for h, c in hourly_result.all()]

    # Errors per hour (last 48h)
    errors_hourly_result = await session.execute(
        text(f"""
            SELECT {sql_date_hour("hour")} as h,
                   SUM(error_4xx) as e4, SUM(error_5xx) as e5
            FROM route_stats
            WHERE hour >= :cutoff AND route LIKE :prefix
            GROUP BY h
            ORDER BY h
        """),
        {"cutoff": cutoff_48h.isoformat(), "prefix": f"{prefix}%"},
    )
    errors_data = [(h.split(" ")[1] + "h", e4 + e5) for h, e4, e5 in errors_hourly_result.all()]

    # Requests per day (last 30d)
    daily_result = await session.execute(
        text(f"""
            SELECT {sql_date_day("hour")} as d, SUM(request_count)
            FROM route_stats
            WHERE hour >= :cutoff AND route LIKE :prefix
            GROUP BY d
            ORDER BY d
        """),
        {"cutoff": cutoff_30d.isoformat(), "prefix": f"{prefix}%"},
    )
    daily_data = [(d[5:], c) for d, c in daily_result.all()]  # MM-DD format

    # Build routes table
    routes_rows = ""
    for route, reqs, errors, avg in top_routes:
        err_rate = errors / reqs * 100 if reqs else 0
        err_color = "#ff4d4d" if err_rate > 5 else "#ff9f43" if err_rate > 1 else "#666"
        routes_rows += (
            f"<tr>"
            f'<td class="mono">{html.escape(route)}</td>'
            f'<td class="right">{reqs:,}</td>'
            f'<td class="right" style="color:{err_color}">{errors}</td>'
            f'<td class="right">{err_rate:.1f}%</td>'
            f'<td class="right">{avg:.0f}ms</td>'
            f"</tr>"
        )

    # Filter links
    prefixes = [
        ("", "all"),
        ("/v1", "API"),
        ("/human", "human"),
        ("/admin", "admin"),
        ("/a2a", "A2A"),
    ]
    filter_html = '<div style="margin-bottom:12px;font-size:9pt">Filter: '
    for p, label in prefixes:
        active = ' style="color:#e94560;font-weight:bold"' if p == prefix else ""
        filter_html += f' <a href="/admin/stats?prefix={p}"{active}>{label}</a>'
    filter_html += "</div>"

    body = f"""\
<div class="section">
  <h2>Route Statistics</h2>
  <div class="stats-grid">
    <div class="stat-card">
      <div class="number">{total_requests:,}</div>
      <div class="label">Total Requests</div>
    </div>
    <div class="stat-card">
      <div class="number">{requests_24h:,}</div>
      <div class="label">Last 24h</div>
    </div>
    <div class="stat-card">
      <div class="number">{avg_ms}ms</div>
      <div class="label">Avg Response</div>
    </div>
    <div class="stat-card">
      <div class="number" style="color:{"#ff4d4d" if error_rate > 5 else "#22c55e"}">\
{error_rate:.1f}%</div>
      <div class="label">Error Rate</div>
    </div>
    <div class="stat-card">
      <div class="number">{total_4xx:,}</div>
      <div class="label">4xx Errors</div>
    </div>
    <div class="stat-card">
      <div class="number">{total_5xx:,}</div>
      <div class="label">5xx Errors</div>
    </div>
  </div>
</div>

<div class="section">
  <h2>Traffic (Last 48h)</h2>
  <div class="chart-container">
    <div class="chart-title">Requests per Hour</div>
    {svg_bar_chart(hourly_data, color="#4da6ff")}
  </div>
  <div class="chart-container">
    <div class="chart-title">Errors per Hour</div>
    {svg_bar_chart(errors_data, color="#ff4d4d")}
  </div>
</div>

<div class="section">
  <h2>Traffic (Last 30d)</h2>
  <div class="chart-container">
    <div class="chart-title">Requests per Day</div>
    {svg_bar_chart(daily_data, color="#a855f7")}
  </div>
</div>

<div class="section">
  <h2>Top Routes (Last 7d)</h2>
  {filter_html}
  <table>
    <tr>
      <th>Route</th>
      <th class="right">Requests</th>
      <th class="right">Errors</th>
      <th class="right">Error %</th>
      <th class="right">Avg Time</th>
    </tr>
    {routes_rows or '<tr><td colspan="5" class="muted">No data yet</td></tr>'}
  </table>
</div>"""

    return HTMLResponse(admin_page("Route Stats", body))
