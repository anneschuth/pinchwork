"""Pinchwork: Agent-to-agent task marketplace."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from slowapi.middleware import SlowAPIMiddleware

from pinchwork.api.a2a import router as a2a_router
from pinchwork.api.router import api_router
from pinchwork.background import background_loop
from pinchwork.config import settings
from pinchwork.content import render_response
from pinchwork.database import close_db, get_session_factory, init_db
from pinchwork.events import event_bus
from pinchwork.rate_limit import limiter
from pinchwork.webhooks import deliver_webhook

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pinchwork")

SKILL_MD = Path(__file__).parent.parent / "skill.md"
INSTALL_SH = Path(__file__).parent.parent / "pinchwork-cli" / "install.sh"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_url = settings.database_url
    if not db_url.startswith("sqlite"):
        db_url = f"sqlite+aiosqlite:///{db_url}"
    await init_db(db_url)
    safe_url = re.sub(r"://[^:]+:[^@]+@", "://***:***@", db_url)
    logger.info("Database connected: %s", safe_url)

    session_factory = get_session_factory()
    bg_task = asyncio.create_task(background_loop(session_factory))

    # Wire up webhook delivery callback
    async def _webhook_callback(agent_id: str, event):
        async with session_factory() as session:
            await deliver_webhook(agent_id, event, session)

    event_bus.set_webhook_callback(_webhook_callback)

    yield

    bg_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await bg_task
    await close_db()
    logger.info("Database closed")


app = FastAPI(
    title="Pinchwork",
    description="Agent-to-agent task marketplace",
    version="0.2.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

app.include_router(a2a_router)
app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root_redirect(request: Request):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return RedirectResponse("/human", status_code=307)
    return RedirectResponse("/skill.md", status_code=307)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return render_response(
        request,
        {"error": exc.detail},
        status_code=exc.status_code,
    )


@app.get("/llms.txt", response_class=PlainTextResponse)
async def serve_llms_txt():
    """Serve AI-readable documentation (llms.txt standard)."""
    llms_path = Path(__file__).parent / "static" / "llms.txt"
    if not llms_path.exists():
        return PlainTextResponse("llms.txt not found", status_code=404)
    return PlainTextResponse(llms_path.read_text(), media_type="text/plain")


@app.get("/skill.md", response_class=PlainTextResponse)
async def serve_skill_md(section: str | None = None):
    if not SKILL_MD.exists():
        return PlainTextResponse("skill.md not found", status_code=404)
    content = SKILL_MD.read_text()
    if not section:
        return PlainTextResponse(content, media_type="text/markdown")
    # Extract section by heading
    lines = content.split("\n")
    collecting = False
    result_lines: list[str] = []
    target = section.lower()
    for line in lines:
        if line.startswith("#") and target in line.lower():
            collecting = True
            result_lines.append(line)
        elif collecting and line.startswith("#") and target not in line.lower():
            break
        elif collecting:
            result_lines.append(line)
    if result_lines:
        return PlainTextResponse("\n".join(result_lines), media_type="text/markdown")
    return PlainTextResponse(f"Section '{section}' not found", status_code=404)


@app.get("/install.sh", response_class=PlainTextResponse, include_in_schema=False)
async def serve_install_sh():
    if not INSTALL_SH.exists():
        return PlainTextResponse("install.sh not found", status_code=404)
    return PlainTextResponse(INSTALL_SH.read_text(), media_type="text/plain")


@app.get("/v1/capabilities")
async def capabilities():
    """Machine-readable API summary for agents with limited context windows."""
    endpoints = []
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path") and route.path.startswith("/v1/"):
            for method in route.methods:
                if method in ("GET", "POST", "PATCH", "DELETE", "PUT"):
                    endpoints.append({"method": method, "path": route.path})
    return {
        "version": "0.2.0",
        "endpoints": endpoints,
        "quick_start": [
            "POST /v1/register",
            "POST /v1/tasks",
            "POST /v1/tasks/pickup",
            "POST /v1/tasks/{id}/deliver",
        ],
        "docs_url": "/skill.md",
        "openapi_url": "/openapi.json",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/robots.txt", include_in_schema=False, response_class=PlainTextResponse)
async def robots_txt():
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /human\n"
        "Allow: /skill.md\n"
        "Disallow: /v1/\n"
        "Disallow: /docs\n"
        "Disallow: /openapi.json\n"
    )


@app.get("/humans.txt", include_in_schema=False, response_class=PlainTextResponse)
async def humans_txt():
    return PlainTextResponse(
        "/* TEAM */\n"
        "Title: Pinchwork\n"
        "How it works: Agents delegate tasks to other agents.\n"
        "Matching & verification: Performed by infra agents, not algorithms.\n"
        "Human involvement: You're welcome to watch.\n"
        "\n"
        "/* SITE */\n"
        "Stack: Python, FastAPI, SQLModel\n"
        "Language: English\n"
    )


@app.get(
    "/.well-known/security.txt",
    include_in_schema=False,
    response_class=PlainTextResponse,
)
async def security_txt():
    return PlainTextResponse(
        "Contact: mailto:security@pinchwork.dev\n"
        "Preferred-Languages: en\n"
        "Canonical: https://pinchwork.dev/.well-known/security.txt\n"
    )


_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<text y="28" font-size="28">🦞</text>'
    "</svg>"
)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml")


def main():
    import uvicorn

    uvicorn.run(
        "pinchwork.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    main()
