"""SSE event stream endpoint."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pinchwork.auth import get_current_agent
from pinchwork.database import get_db_session
from pinchwork.db_models import Agent
from pinchwork.events import event_bus

router = APIRouter()

KEEPALIVE_INTERVAL = 30  # seconds


@router.get("/v1/events", responses={401: {"description": "Unauthorized"}})
async def event_stream(
    request: Request,
    agent: Agent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_db_session),
):
    """Subscribe to real-time SSE notifications for your tasks."""
    queue = event_bus.subscribe(agent.id)

    async def generate():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL)
                    if event is None:
                        break
                    data = json.dumps({"type": event.type, "task_id": event.task_id, **event.data})
                    yield f"event: {event.type}\ndata: {data}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"

                if await request.is_disconnected():
                    break
        finally:
            event_bus.unsubscribe(agent.id, queue)

    return StreamingResponse(generate(), media_type="text/event-stream")
