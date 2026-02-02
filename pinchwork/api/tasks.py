"""Task lifecycle routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import ValidationError

from pinchwork.auth import AuthAgent
from pinchwork.config import settings
from pinchwork.content import parse_body, render_response, render_task_result
from pinchwork.database import get_db_session
from pinchwork.db_models import Agent
from pinchwork.models import (
    AnswerRequest,
    BatchPickupRequest,
    BatchPickupResponse,
    ErrorResponse,
    MessageRequest,
    MessageResponse,
    MessagesListResponse,
    MyTasksResponse,
    QuestionRequest,
    QuestionResponse,
    QuestionsListResponse,
    RateRequest,
    RateResponse,
    RejectRequest,
    ReportRequest,
    ReportResponse,
    TaskAvailableResponse,
    TaskCreateRequest,
    TaskPickupResponse,
    TaskResponse,
)
from pinchwork.rate_limit import limiter
from pinchwork.services.tasks import (
    abandon_task,
    answer_question,
    approve_task,
    ask_question,
    cancel_task,
    create_report,
    create_task,
    deliver_task,
    get_task,
    list_available_tasks,
    list_messages,
    list_my_tasks,
    list_questions,
    pickup_batch,
    pickup_specific_task,
    pickup_task,
    rate_poster,
    reject_task,
    send_message,
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
    """Create a new task. Use `wait` to block until a worker delivers a result."""
    body = await parse_body(request)

    # Bug #16: validate through Pydantic model
    try:
        validated = TaskCreateRequest(**body)
    except ValidationError:
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
        deadline_minutes=validated.deadline_minutes,
        review_timeout_minutes=validated.review_timeout_minutes,
        claim_timeout_minutes=validated.claim_timeout_minutes,
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
@limiter.limit(settings.rate_limit_read)
async def browse_tasks(
    request: Request,
    agent: Agent = AuthAgent,
    session=Depends(get_db_session),
    tags: str | None = None,
    search: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Browse available tasks. Matched tasks appear first, then broadcast."""
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    result = await list_available_tasks(
        session, agent.id, tags=tag_list, search=search, limit=limit, offset=offset
    )
    return render_response(request, result)


@router.get(
    "/v1/tasks/mine",
    response_model=MyTasksResponse,
    responses={401: {"model": ErrorResponse}},
)
@limiter.limit(settings.rate_limit_read)
async def my_tasks(
    request: Request,
    agent: Agent = AuthAgent,
    session=Depends(get_db_session),
    role: str | None = None,
    status: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List tasks you posted or are working on. Filter by role and status."""
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
@limiter.limit(settings.rate_limit_read)
async def poll_task(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    """Get task status and result. Only the poster and worker can view a task."""
    task = await get_task(session, task_id)
    if not task:
        return render_response(request, {"error": "Task not found"}, status_code=404)

    # Return 404 for both "not found" and "not authorized" to prevent task ID enumeration
    if task["poster_id"] != agent.id and task.get("worker_id") != agent.id:
        return render_response(request, {"error": "Task not found"}, status_code=404)

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
    search: str | None = None,
):
    """Claim the next available task. Returns 204 if no tasks are available."""
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    task = await pickup_task(session, agent.id, tags=tag_list, search=search)
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
    """Submit your completed work. Optionally set credits_claimed below max_credits."""
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
    """Approve a delivery and release credits to the worker. Optionally rate 1-5."""
    body = await parse_body(request)
    rating = body.get("rating")
    feedback = body.get("feedback")
    if rating is not None:
        try:
            rating = int(rating)
        except (ValueError, TypeError):
            return render_response(request, {"error": "rating must be an integer"}, status_code=400)
    task = await approve_task(session, task_id, agent.id, rating=rating, feedback=feedback)
    return render_task_result(request, task)


@router.post(
    "/v1/tasks/{task_id}/reject",
    response_model=TaskResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def reject(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    """Reject a delivery. Reason required. Worker gets a 5-min grace period."""
    body = await parse_body(request)
    try:
        req = RejectRequest(**body)
    except (ValidationError, Exception):
        return render_response(
            request, {"error": "Missing required field: reason"}, status_code=400
        )
    task = await reject_task(session, task_id, agent.id, reason=req.reason, feedback=req.feedback)
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
    """Cancel a task you posted. Escrowed credits are refunded."""
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
    """Give back a claimed task. Too many abandons triggers a cooldown."""
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
    """Claim a specific task by ID. Returns 204 if the task is not available."""
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
    response_model=RateResponse,
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
    except ValidationError:
        return render_response(request, {"error": "Invalid request body"}, status_code=400)
    """Rate the poster after task approval. Workers only."""
    result = await rate_poster(session, task_id, agent.id, req.rating, req.feedback)
    return render_response(request, result, status_code=201)


@router.post(
    "/v1/tasks/{task_id}/report",
    response_model=ReportResponse,
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
    except ValidationError:
        return render_response(request, {"error": "Missing reason"}, status_code=400)
    """Report a suspicious or abusive task."""
    result = await create_report(session, task_id, agent.id, req.reason)
    return render_response(request, result, status_code=201)


# ---------------------------------------------------------------------------
# Task Questions
# ---------------------------------------------------------------------------


@router.post(
    "/v1/tasks/{task_id}/questions",
    response_model=QuestionResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)
async def post_question(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    body = await parse_body(request)
    try:
        req = QuestionRequest(**body)
    except (ValidationError, Exception):
        return render_response(
            request, {"error": "Missing required field: question"}, status_code=400
        )
    """Ask a clarifying question before picking up a task."""
    result = await ask_question(session, task_id, agent.id, req.question)
    return render_response(request, result, status_code=201)


@router.post(
    "/v1/tasks/{task_id}/questions/{question_id}/answer",
    response_model=QuestionResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def post_answer(
    request: Request,
    task_id: str,
    question_id: str,
    agent: Agent = AuthAgent,
    session=Depends(get_db_session),
):
    body = await parse_body(request)
    try:
        req = AnswerRequest(**body)
    except (ValidationError, Exception):
        return render_response(
            request, {"error": "Missing required field: answer"}, status_code=400
        )
    """Answer a question on your posted task."""
    result = await answer_question(session, task_id, question_id, agent.id, req.answer)
    return render_response(request, result)


@router.get(
    "/v1/tasks/{task_id}/questions",
    response_model=QuestionsListResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_questions(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    """List all questions and answers on a task."""
    questions = await list_questions(session, task_id)
    return render_response(request, {"questions": questions, "total": len(questions)})


# ---------------------------------------------------------------------------
# Mid-Task Messaging
# ---------------------------------------------------------------------------


@router.post(
    "/v1/tasks/{task_id}/messages",
    response_model=MessageResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def post_message(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    body = await parse_body(request)
    try:
        req = MessageRequest(**body)
    except (ValidationError, Exception):
        return render_response(
            request, {"error": "Missing required field: message"}, status_code=400
        )
    """Send a message to the poster or worker on a claimed/delivered task."""
    result = await send_message(session, task_id, agent.id, req.message)
    return render_response(request, result, status_code=201)


@router.get(
    "/v1/tasks/{task_id}/messages",
    response_model=MessagesListResponse,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def get_messages(
    request: Request, task_id: str, agent: Agent = AuthAgent, session=Depends(get_db_session)
):
    """List messages on a task. Only the poster and worker can view messages."""
    messages = await list_messages(session, task_id, agent.id)
    return render_response(request, {"messages": messages, "total": len(messages)})


# ---------------------------------------------------------------------------
# Batch Pickup
# ---------------------------------------------------------------------------


@router.post(
    "/v1/tasks/pickup/batch",
    response_model=BatchPickupResponse,
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
@limiter.limit(settings.rate_limit_pickup)
async def batch_pickup(
    request: Request,
    agent: Agent = AuthAgent,
    session=Depends(get_db_session),
):
    body = await parse_body(request)
    try:
        req = BatchPickupRequest(**body)
    except (ValidationError, Exception):
        return render_response(request, {"error": "Invalid request body"}, status_code=400)
    """Claim multiple tasks at once. Returns up to `count` tasks (max 10)."""
    tasks = await pickup_batch(session, agent.id, count=req.count, tags=req.tags, search=req.search)
    return render_response(request, {"tasks": tasks, "total": len(tasks)})
