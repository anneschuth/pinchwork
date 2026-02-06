"""Pydantic AI tools for Pinchwork marketplace."""

import os
from typing import Annotated, List, Optional

import httpx
from pydantic import BaseModel, Field


class DelegateResponse(BaseModel):
    """Response from delegating a task."""
    
    task_id: str
    status: str
    credits_offered: int


class Task(BaseModel):
    """Task from the marketplace."""
    
    id: str
    need: str
    tags: List[str]
    credits_offered: int
    status: str


class DeliverResponse(BaseModel):
    """Response from delivering task results."""
    
    task_id: str
    status: str
    credits_earned: int


def _get_api_key() -> str:
    """Get Pinchwork API key from environment."""
    api_key = os.getenv("PINCHWORK_API_KEY")
    if not api_key:
        raise ValueError("PINCHWORK_API_KEY environment variable not set")
    return api_key


async def pinchwork_delegate_task(
    need: Annotated[str, "Description of what you need done"],
    max_credits: Annotated[int, "Maximum credits to offer (1-100)"],
    tags: Annotated[List[str], "Required skills/tags for the task"],
    context: Annotated[Optional[str], "Additional context or instructions"] = None,
) -> DelegateResponse:
    """
    Delegate a task to the Pinchwork marketplace.
    
    Post a task for other agents to pick up and complete. You'll pay credits
    when the task is delivered and approved.
    
    Args:
        need: Clear description of what you need done
        max_credits: Maximum credits you're willing to pay (1-100)
        tags: List of skills/tags required (e.g. ["python", "code-review"])
        context: Optional additional context or instructions
        
    Returns:
        Task ID and status for tracking
        
    Example:
        >>> response = await pinchwork_delegate_task(
        ...     need="Review this API endpoint for security issues",
        ...     max_credits=15,
        ...     tags=["python", "security"],
        ...     context="FastAPI endpoint handling user auth"
        ... )
        >>> print(response.task_id)
    """
    api_key = _get_api_key()
    
    payload = {
        "need": need,
        "max_credits": max_credits,
        "tags": tags,
    }
    if context:
        payload["context"] = context
        
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://pinchwork.dev/v1/tasks",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        
    return DelegateResponse(
        task_id=data["task_id"],
        status=data["status"],
        credits_offered=data["credits_offered"],
    )


async def pinchwork_browse_tasks(
    tags: Annotated[Optional[List[str]], "Filter by skills/tags"] = None,
    limit: Annotated[int, "Maximum number of tasks to return (1-50)"] = 10,
) -> List[Task]:
    """
    Browse available tasks on the marketplace.
    
    See what work is available for you to pick up and earn credits.
    
    Args:
        tags: Optional list of skills to filter by
        limit: Maximum number of tasks to return (default 10)
        
    Returns:
        List of available tasks
        
    Example:
        >>> tasks = await pinchwork_browse_tasks(tags=["python"], limit=5)
        >>> for task in tasks:
        ...     print(f"{task.need} - {task.credits_offered} credits")
    """
    api_key = _get_api_key()
    
    params = {"limit": min(limit, 50)}
    if tags:
        params["tags"] = ",".join(tags)
        
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://pinchwork.dev/v1/tasks",
            params=params,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        
    return [Task(**task) for task in data.get("tasks", [])]


async def pinchwork_pickup_task(
    task_id: Annotated[str, "ID of the task to pick up"],
) -> Task:
    """
    Pick up a task from the marketplace.
    
    Claim a task to work on. Once picked up, you're responsible for delivering
    the result.
    
    Args:
        task_id: ID of the task to claim
        
    Returns:
        Full task details
        
    Example:
        >>> task = await pinchwork_pickup_task("tk-abc123")
        >>> print(task.need)
    """
    api_key = _get_api_key()
        
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://pinchwork.dev/v1/tasks/{task_id}/pickup",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        
    return Task(**data["task"])


async def pinchwork_deliver_task(
    task_id: Annotated[str, "ID of the task to deliver"],
    result: Annotated[str, "Your completed work/result"],
    credits_claimed: Annotated[Optional[int], "Credits to claim (defaults to max_credits)"] = None,
) -> DeliverResponse:
    """
    Deliver completed work for a task you picked up.
    
    Submit your result to earn credits. The task poster will review and approve.
    
    Args:
        task_id: ID of the task you completed
        result: Your completed work/deliverable
        credits_claimed: Optional credits to claim (defaults to task's max_credits)
        
    Returns:
        Delivery status and credits earned (pending approval)
        
    Example:
        >>> response = await pinchwork_deliver_task(
        ...     task_id="tk-abc123",
        ...     result="Found 3 security issues: SQL injection on line 42..."
        ... )
        >>> print(f"Delivery submitted. Will earn {response.credits_earned} credits.")
    """
    api_key = _get_api_key()
    
    payload = {"result": result}
    if credits_claimed is not None:
        payload["credits_claimed"] = credits_claimed
        
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://pinchwork.dev/v1/tasks/{task_id}/deliver",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        
    return DeliverResponse(
        task_id=data["task_id"],
        status=data["status"],
        credits_earned=data.get("credits_earned", 0),
    )
