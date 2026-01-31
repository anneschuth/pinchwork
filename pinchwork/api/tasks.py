"""Task lifecycle routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from pinchwork.auth import AuthAgent
from pinchwork.content import parse_body, render_response, render_task_result
from pinchwork.database import get_db_session
from pinchwork.db_models import Agent
from pinchwork.models import TaskCreateRequest
from pinchwork.services.tasks import (
    approve_task,
    cancel_task,
    create_task,
    deliver_task,
    get_task,
    pickup_task,
    reject_task,
    wait_for_result,
)

router = APIRouter()


@router.post("/v1/tasks")
async def delegate_task(
    request: Request, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    body = await parse_body(request)

    # Bug #16: validate through Pydantic model
    try:
        validated = TaskCreateRequest(**body)
    except Exception:
        return render_response(request, {"error": "Invalid request body"}, status_code=400)

    if not validated.need:
        return render_response(request, {"error": "Missing 'need' field"}, status_code=400)

    task = await create_task(
        session, agent.id, validated.need, validated.max_credits, tags=validated.tags
    )

    if validated.wait:
        result = await wait_for_result(session, task["id"], validated.wait)
        if result and result["status"] in ("delivered", "approved"):
            return render_task_result(request, result)

    return render_response(
        request,
        {"task_id": task["id"], "status": task["status"], "need": validated.need},
        status_code=201,
        headers={"X-Task-Id": task["id"], "X-Status": task["status"]},
    )


@router.get("/v1/tasks/{task_id}")
async def poll_task(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    task = await get_task(session, task_id)
    if not task:
        return render_response(request, {"error": "Task not found"}, status_code=404)

    if task["poster_id"] != agent.id and task.get("worker_id") != agent.id:
        return render_response(request, {"error": "Not authorized"}, status_code=403)

    return render_task_result(request, task)


@router.post("/v1/tasks/pickup")
async def pickup(
    request: Request,
    agent: Agent = AuthAgent,
    session=Depends(get_db_session),
    tags: str | None = None,
):
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    task = await pickup_task(session, agent.id, tags=tag_list)
    if not task:
        # Bug #5 fix: 204 with no body
        return Response(status_code=204)

    return render_response(
        request,
        task,
        headers={"X-Task-Id": task["task_id"], "X-Budget": str(task["max_credits"])},
    )


@router.post("/v1/tasks/{task_id}/deliver")
async def deliver(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    body = await parse_body(request)
    result = body.get("result", "")
    if not result:
        raw = await request.body()
        result = raw.decode("utf-8").strip()
    if not result:
        return render_response(request, {"error": "Missing result"}, status_code=400)

    credits_claimed = body.get("credits_claimed")
    if credits_claimed is not None:
        credits_claimed = int(credits_claimed)

    task = await deliver_task(session, task_id, agent.id, result, credits_claimed)
    return render_task_result(request, task)


@router.post("/v1/tasks/{task_id}/approve")
async def approve(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    task = await approve_task(session, task_id, agent.id)
    return render_task_result(request, task)


@router.post("/v1/tasks/{task_id}/reject")
async def reject(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    task = await reject_task(session, task_id, agent.id)
    return render_task_result(request, task)


@router.post("/v1/tasks/{task_id}/cancel")
async def cancel(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    task = await cancel_task(session, task_id, agent.id)
    return render_task_result(request, task)
