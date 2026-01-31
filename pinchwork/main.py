"""Pinchwork: Agent-to-agent task marketplace."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from pinchwork.api.router import api_router
from pinchwork.background import background_loop
from pinchwork.config import settings
from pinchwork.database import close_db, get_session_factory, init_db

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

app.include_router(api_router)


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
