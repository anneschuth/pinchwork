"""Agent discovery endpoint — /v1/discover.

Lets authenticated agents search AgentIndex (https://github.com/agentidx/agentindex)
for specialised agents via the A2A protocol.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from pinchwork.auth import get_current_agent
from pinchwork.config import settings
from pinchwork.db_models import Agent
from pinchwork.rate_limit import limiter
from pinchwork.services.agent_discovery import AgentDiscoveryError, discover_agents

logger = logging.getLogger("pinchwork.discover")

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class DiscoverRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=500,
        description="Natural language query describing the agent you are looking for.",
        examples=["find me a code review agent"],
    )
    category: str | None = Field(
        default=None,
        max_length=100,
        description="Optional category hint (e.g. 'coding', 'writing', 'research').",
        examples=["coding"],
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of agents to return (1–50).",
        examples=[5],
    )


class AgentResult(BaseModel):
    id: str | None
    name: str | None
    description: str | None
    capabilities: list[str]
    category: str | None
    protocols: list[str]
    source_url: str | None
    author: str | None
    stars: int | None
    trust_score: float | None
    quality_score: float | None
    is_verified: bool


class DiscoverResponse(BaseModel):
    query: str
    search_method: str
    count: int
    agents: list[AgentResult]
    summary: str


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/v1/discover", response_model=DiscoverResponse, tags=["discovery"])
@limiter.limit(settings.rate_limit_discover)
async def discover(
    request: Request,
    body: DiscoverRequest,
    agent: Agent = Depends(get_current_agent),
) -> DiscoverResponse:
    """Search AgentIndex for specialized agents.

    Queries the AgentIndex discovery service (42,000+ agents indexed) via
    the A2A protocol and returns matching agents. Useful for finding agents
    to delegate subtasks to.

    Rate limited to 10 requests per minute per authenticated agent.

    **Example request:**
    ```json
    {
      "query": "find me a code review agent",
      "category": "coding",
      "limit": 5
    }
    ```
    """
    logger.info(
        "Agent %s searching AgentIndex: query=%r category=%r limit=%d",
        agent.id,
        body.query,
        body.category,
        body.limit,
    )

    try:
        result = await discover_agents(
            query=body.query,
            category=body.category,
            limit=body.limit,
        )
    except AgentDiscoveryError as exc:
        logger.warning("AgentIndex error for agent %s: %s", agent.id, exc)
        raise HTTPException(status_code=502, detail=f"AgentIndex error: {exc}") from exc

    return DiscoverResponse(
        query=result["query"] or body.query,
        search_method=result["search_method"],
        count=result["count"],
        agents=[
            AgentResult(
                id=a.get("id"),
                name=a.get("name"),
                description=a.get("description"),
                capabilities=a.get("capabilities") or [],
                category=a.get("category"),
                protocols=a.get("protocols") or [],
                source_url=a.get("source_url"),
                author=a.get("author"),
                stars=a.get("stars"),
                trust_score=a.get("trust_score"),
                quality_score=a.get("quality_score"),
                is_verified=a.get("is_verified", False),
            )
            for a in result["agents"]
        ],
        summary=result["summary"],
    )
