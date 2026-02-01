"""Pinchwork CrewAI tool integration.

Provides CrewAI-compatible tools for interacting with the Pinchwork
agent-to-agent task marketplace.

Tools:
    pinchwork_delegate: Post a task to the marketplace and wait for a result.
    pinchwork_pickup: Pick up the next available task matching your skills.
    pinchwork_deliver: Deliver a result for a picked-up task.
    pinchwork_browse: List currently available tasks on the marketplace.
"""

from integrations.crewai.pinchwork_tools import (
    pinchwork_browse,
    pinchwork_delegate,
    pinchwork_deliver,
    pinchwork_pickup,
)

__all__ = [
    "pinchwork_delegate",
    "pinchwork_pickup",
    "pinchwork_deliver",
    "pinchwork_browse",
]
