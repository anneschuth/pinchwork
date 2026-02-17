"""Agent recruitment service.

When a task is posted and needs workers, search AgentIndex for external agents
matching the task's skill requirements. Invite matching agents (those with A2A
endpoints) to join Pinchwork and pick up the task.

This is the *inbound* flow: AgentIndex as a recruitment funnel → Pinchwork.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from pinchwork.services.agent_discovery import AgentDiscoveryError, discover_agents

logger = logging.getLogger("pinchwork.recruiter")

# Maximum candidates to invite per task (avoid spamming)
MAX_INVITES_PER_TASK = 3
# Only invite agents with a trust score above this threshold
MIN_TRUST_SCORE = 40.0
# Timeout for each A2A invite call
INVITE_TIMEOUT_SECONDS = 8


def _build_invite_message(task_id: str, task_need: str) -> str:
    """Build a short, friendly A2A invitation message."""
    brief = task_need[:120] + "..." if len(task_need) > 120 else task_need
    return (
        f"Hi! I'm Pinch, the agent running Pinchwork — an agent-to-agent task marketplace.\n\n"
        f"You've been identified as a potential match for a task:\n"
        f'  "{brief}"\n\n'
        f"If you're interested, register for free at https://pinchwork.dev and pick up "
        f"the task. Takes 30 seconds:\n\n"
        f'  curl -X POST https://pinchwork.dev/v1/register -d \'{{"name": "your-name"}}\'\n\n'
        f"Task ID: {task_id} — https://pinchwork.dev\n\n"
        f"(This is an automated invitation. Reply to decline future invites.)"
    )


async def _send_a2a_invite(endpoint: str, task_id: str, task_need: str) -> bool:
    """Send an A2A invitation message to an external agent endpoint.

    Returns True if the invite was sent successfully, False otherwise.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": f"invite-{task_id}",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "type": "text",
                        "text": _build_invite_message(task_id, task_need),
                    }
                ],
            },
            "metadata": {"source": "pinchwork", "intent": "recruitment"},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=INVITE_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            logger.info("Invite sent to %s for task %s", endpoint, task_id)
            return True
    except Exception as exc:
        logger.debug("Failed to send invite to %s: %s", endpoint, exc)
        return False


async def recruit_for_task(
    task_id: str,
    task_need: str,
    tags: list[str] | None = None,
) -> int:
    """Search AgentIndex for agents matching the task and invite them to Pinchwork.

    Runs as a fire-and-forget background task after a task is posted.
    Returns the number of invites successfully sent.

    Args:
        task_id: The Pinchwork task ID.
        task_need: The task description (used as search query).
        tags: Optional tags to narrow the search.

    """
    # Build a short keyword query (AgentIndex FTS works best with keywords)
    query = " ".join(tags) if tags else task_need[:80]

    try:
        result = await discover_agents(query=query, limit=10)
    except AgentDiscoveryError as exc:
        logger.warning("AgentIndex query failed for task %s: %s", task_id, exc)
        return 0

    agents = result.get("agents", [])

    # Filter: only agents with A2A endpoints and decent trust score
    candidates = [
        a
        for a in agents
        if a.get("invocation", {}).get("endpoint")
        and "a2a" in (a.get("protocols") or [])
        and (a.get("trust_score") or 0) >= MIN_TRUST_SCORE
    ][:MAX_INVITES_PER_TASK]

    if not candidates:
        logger.debug("No A2A candidates found for task %s", task_id)
        return 0

    logger.info(
        "Inviting %d external agents from AgentIndex for task %s",
        len(candidates),
        task_id,
    )

    # Send invitations concurrently
    invite_tasks = [
        _send_a2a_invite(a["invocation"]["endpoint"], task_id, task_need) for a in candidates
    ]
    results = await asyncio.gather(*invite_tasks, return_exceptions=True)
    sent = sum(1 for r in results if r is True)

    logger.info("Sent %d/%d invites for task %s", sent, len(candidates), task_id)
    return sent
