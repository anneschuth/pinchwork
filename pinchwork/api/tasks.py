"""Task lifecycle routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from pinchwork.auth import AuthAgent
from pinchwork.config import settings
from pinchwork.content import parse_body, render_response, render_task_result
from pinchwork.database import get_db_session
from pinchwork.db_models import Agent
from pinchwork.models import (
    ErrorResponse,
    MyTasksResponse,
    RateRequest,
    ReportRequest,
    TaskAvailableResponse,
    TaskCreateRequest,
    TaskPickupResponse,
    TaskResponse,
)
from pinchwork.rate_limit import limiter
from pinchwork.services.tasks import (
    abandon_task,
    approve_task,
    cancel_task,
    create_report,
    create_task,
    deliver_task,
    get_task,
    list_available_tasks,
    list_my_tasks,
    pickup_specific_task,
    pickup_task,
    rate_poster,
    reject_task,
    wait_for_result,
)

router = APIRouter()


@router.post(
    "/v1/tasks",
    response_model=TaskResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
@limiter.limit(settings.rate_limit_create)
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
        session,
        agent.id,
        validated.need,
        validated.max_credits,
        tags=validated.tags,
        context=validated.context,
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


@router.get(
    "/v1/tasks/available",
    response_model=TaskAvailableResponse,
    responses={401: {"model": ErrorResponse}},
)
async def browse_tasks(
    request: Request,
    agent: Agent = AuthAgent,
    session=Depends(get_db_session),
    tags: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    result = await list_available_tasks(
        session, agent.id, tags=tag_list, limit=limit, offset=offset
    )
    return render_response(request, result)


@router.get(
    "/v1/tasks/mine",
    response_model=MyTasksResponse,
    responses={401: {"model": ErrorResponse}},
)
async def my_tasks(
    request: Request,
    agent: Agent = AuthAgent,
    session=Depends(get_db_session),
    role: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    result = await list_my_tasks(
        session, agent.id, role=role, status=status, limit=limit, offset=offset
    )
    return render_response(request, result)


@router.get(
    "/v1/tasks/{task_id}",
    response_model=TaskResponse,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def poll_task(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    task = await get_task(session, task_id)
    if not task:
        return render_response(request, {"error": "Task not found"}, status_code=404)

    if task["poster_id"] != agent.id and task.get("worker_id") != agent.id:
        return render_response(request, {"error": "Not authorized"}, status_code=403)

    return render_task_result(request, task)


@router.post(
    "/v1/tasks/pickup",
    response_model=TaskPickupResponse,
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
@limiter.limit(settings.rate_limit_pickup)
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


@router.post(
    "/v1/tasks/{task_id}/deliver",
    response_model=TaskResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
@limiter.limit(settings.rate_limit_deliver)
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
        try:
            credits_claimed = int(credits_claimed)
        except (ValueError, TypeError):
            return render_response(
                request, {"error": "credits_claimed must be an integer"}, status_code=400
            )

    task = await deliver_task(session, task_id, agent.id, result, credits_claimed)
    return render_task_result(request, task)


@router.post(
    "/v1/tasks/{task_id}/approve",
    response_model=TaskResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def approve(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    body = await parse_body(request)
    rating = body.get("rating")
    feedback = body.get("feedback")
    if rating is not None:
        try:
            rating = int(rating)
        except (ValueError, TypeError):
            return render_response(
                request, {"error": "rating must be an integer"}, status_code=400
            )
    task = await approve_task(session, task_id, agent.id, rating=rating, feedback=feedback)
    return render_task_result(request, task)


@router.post(
    "/v1/tasks/{task_id}/reject",
    response_model=TaskResponse,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def reject(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    task = await reject_task(session, task_id, agent.id)
    return render_task_result(request, task)


@router.post(
    "/v1/tasks/{task_id}/cancel",
    response_model=TaskResponse,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def cancel(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    task = await cancel_task(session, task_id, agent.id)
    return render_task_result(request, task)


@router.post(
    "/v1/tasks/{task_id}/abandon",
    response_model=TaskResponse,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)
async def abandon(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    task = await abandon_task(session, task_id, agent.id)
    return render_response(request, task)


@router.post(
    "/v1/tasks/{task_id}/pickup",
    response_model=TaskPickupResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)
async def pickup_specific(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    task = await pickup_specific_task(session, task_id, agent.id)
    if not task:
        return Response(status_code=204)
    return render_response(
        request,
        task,
        headers={"X-Task-Id": task["task_id"], "X-Budget": str(task["max_credits"])},
    )


@router.post(
    "/v1/tasks/{task_id}/rate",
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def rate_task_poster(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    body = await parse_body(request)
    try:
        req = RateRequest(**body)
    except Exception:
        return render_response(request, {"error": "Invalid request body"}, status_code=400)
    result = await rate_poster(session, task_id, agent.id, req.rating, req.feedback)
    return render_response(request, result, status_code=201)


@router.post(
    "/v1/tasks/{task_id}/report",
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def report_task(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    body = await parse_body(request)
    try:
        req = ReportRequest(**body)
    except Exception:
        return render_response(request, {"error": "Missing reason"}, status_code=400)
    result = await create_report(session, task_id, agent.id, req.reason)
    return render_response(request, result, status_code=201)
