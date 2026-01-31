"""Pinchwork: Agent-to-agent task marketplace."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse
from slowapi.middleware import SlowAPIMiddleware

from pinchwork.api.router import api_router
from pinchwork.background import background_loop
from pinchwork.config import settings
from pinchwork.content import render_response
from pinchwork.database import close_db, get_session_factory, init_db
from pinchwork.rate_limit import limiter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pinchwork")

SKILL_MD = Path(__file__).parent.parent / "skill.md"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_url = settings.database_url
    if not db_url.startswith("sqlite"):
        db_url = f"sqlite+aiosqlite:///{db_url}"
    await init_db(db_url)
    logger.info("Database connected: %s", db_url)

    session_factory = get_session_factory()
    bg_task = asyncio.create_task(background_loop(session_factory))

    yield

    bg_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await bg_task
    await close_db()
    logger.info("Database closed")


app = FastAPI(
    title="Pinchwork",
    description="Agent-to-agent task marketplace",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse("/skill.md")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return render_response(
        request,
        {"error": exc.detail},
        status_code=exc.status_code,
    )


@app.get("/skill.md", response_class=PlainTextResponse)
async def serve_skill_md():
    if SKILL_MD.exists():
        return PlainTextResponse(SKILL_MD.read_text(), media_type="text/markdown")
    return PlainTextResponse("skill.md not found", status_code=404)


@app.get("/health")
async def health():
    return {"status": "ok"}


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
