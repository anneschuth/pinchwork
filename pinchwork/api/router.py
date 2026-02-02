"""Mount all API routes."""

from fastapi import APIRouter

from pinchwork.api.admin_dashboard import router as admin_router
from pinchwork.api.agents import router as agents_router
from pinchwork.api.credits import router as credits_router
from pinchwork.api.events import router as events_router
from pinchwork.api.human import router as human_router
from pinchwork.api.tasks import router as tasks_router

api_router = APIRouter()
api_router.include_router(agents_router, tags=["agents"])
api_router.include_router(tasks_router, tags=["tasks"])
api_router.include_router(credits_router, tags=["credits"])
api_router.include_router(events_router, tags=["events"])
api_router.include_router(human_router, tags=["human"])
api_router.include_router(admin_router, tags=["admin"])
