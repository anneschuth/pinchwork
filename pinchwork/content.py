"""Content negotiation: accept markdown (with YAML frontmatter) or JSON."""

from __future__ import annotations

import json

import frontmatter
from fastapi import Request, Response
from pydantic import BaseModel


async def parse_body(request: Request) -> dict:
    """Parse request body as JSON or markdown with YAML frontmatter."""
    content_type = request.headers.get("content-type", "")
    raw = await request.body()
    text = raw.decode("utf-8").strip()

    if not text:
        return {}

    if "application/json" in content_type:
        return json.loads(text)

    # Try JSON first (some agents send JSON without content-type),
    # but only if it looks like JSON and content-type isn't explicitly markdown
    if text.startswith("{") and "text/markdown" not in content_type:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Parse as markdown with optional YAML frontmatter
    post = frontmatter.loads(text)
    result = dict(post.metadata)
    if post.content.strip():
        result["need"] = post.content.strip()
    return result


def wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" in accept


def render_response(
    request: Request,
    data: dict | BaseModel,
    status_code: int = 200,
    headers: dict | None = None,
) -> Response:
    """Return JSON or markdown based on Accept header."""
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")

    if wants_json(request):
        return Response(
            content=json.dumps(data, indent=2),
            status_code=status_code,
            media_type="application/json",
            headers=headers,
        )

    # Copy before mutating so callers' dicts are not affected
    data = dict(data)

    # Markdown: structured fields as YAML frontmatter, 'result'/'need' as body
    body_key = None
    for k in ("result", "need", "message"):
        if k in data:
            body_key = k
            break

    if body_key:
        body = data.pop(body_key)
        if data:
            fm = frontmatter.Post(body, **data)
            content = frontmatter.dumps(fm)
        else:
            content = body
    else:
        fm = frontmatter.Post("", **data)
        content = frontmatter.dumps(fm)

    return Response(
        content=content,
        status_code=status_code,
        media_type="text/markdown",
        headers=headers,
    )


def render_task_result(
    request: Request,
    task: dict,
    status_code: int = 200,
) -> Response:
    """Render a task result with consistent TaskResponse shape."""
    headers = {
        "X-Task-Id": task["id"],
        "X-Status": task["status"],
    }
    if task.get("credits_charged"):
        headers["X-Credits-Charged"] = str(task["credits_charged"])

    data = {
        "task_id": task["id"],
        "status": task["status"],
        "need": task.get("need", ""),
        "context": task.get("context"),
        "result": task.get("result"),
        "credits_charged": task.get("credits_charged"),
        "poster_id": task.get("poster_id"),
        "worker_id": task.get("worker_id"),
        "deadline": task.get("deadline"),
        "claim_deadline": task.get("claim_deadline"),
        "review_timeout_minutes": task.get("review_timeout_minutes"),
        "claim_timeout_minutes": task.get("claim_timeout_minutes"),
    }
    if task.get("rejection_reason") is not None:
        data["rejection_reason"] = task["rejection_reason"]
    if task.get("rejection_count"):
        data["rejection_count"] = task["rejection_count"]
    if task.get("rejection_grace_deadline"):
        data["rejection_grace_deadline"] = task["rejection_grace_deadline"]

    return render_response(request, data, status_code=status_code, headers=headers)
