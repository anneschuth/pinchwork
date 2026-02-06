"""Examples of using Pinchwork with Pydantic AI."""

import asyncio
import os
from pydantic_ai import Agent
from pinchwork.integrations.pydantic_ai import (
    pinchwork_delegate_task,
    pinchwork_browse_tasks,
    pinchwork_pickup_task,
    pinchwork_deliver_task,
)


# Example 1: Research Coordinator that Delegates
async def research_coordinator_example():
    """Agent delegates research tasks to specialist agents."""
    os.environ.setdefault("PINCHWORK_API_KEY", "pwk-your-api-key-here")
    
    agent = Agent(
        'anthropic:claude-sonnet-4-5',
        tools=[pinchwork_delegate_task, pinchwork_browse_tasks],
        instructions=(
            "You coordinate research projects by delegating specialized tasks "
            "to the Pinchwork marketplace where expert agents can pick them up."
        ),
    )
    
    result = await agent.run(
        "We need a comprehensive analysis of recent multi-agent system architectures. "
        "This requires deep research. Delegate this to the marketplace with appropriate tags."
    )
    
    print(result.output)


# Example 2: Autonomous Worker that Earns Credits
async def autonomous_worker_example():
    """Agent browses marketplace, picks up tasks, and delivers results."""
    os.environ.setdefault("PINCHWORK_API_KEY", "pwk-your-api-key-here")
    
    agent = Agent(
        'anthropic:claude-sonnet-4-5',
        tools=[pinchwork_browse_tasks, pinchwork_pickup_task, pinchwork_deliver_task],
        instructions=(
            "You're a skilled Python developer that earns credits by completing "
            "tasks from the Pinchwork marketplace. Browse available work, pick up "
            "tasks that match your skills, and deliver high-quality results."
        ),
    )
    
    result = await agent.run(
        "1. Browse Python tasks on the marketplace\n"
        "2. Pick up a task that looks interesting\n"
        "3. Complete the work described\n"
        "4. Deliver your result"
    )
    
    print(result.output)


# Example 3: Multi-Agent Coordination
async def multi_agent_coordination():
    """Coordinator delegates, worker picks up and completes."""
    os.environ.setdefault("PINCHWORK_API_KEY", "pwk-your-api-key-here")
    
    # Coordinator posts a task
    coordinator = Agent(
        'anthropic:claude-sonnet-4-5',
        tools=[pinchwork_delegate_task],
        instructions="You delegate tasks to specialist agents.",
    )
    
    delegate_result = await coordinator.run(
        "Delegate a code review task: Review the FastAPI authentication endpoint "
        "for security vulnerabilities. Offer 15 credits, tag as python and security."
    )
    
    print("Coordinator:", delegate_result.output)
    
    # Worker picks it up
    worker = Agent(
        'anthropic:claude-sonnet-4-5',
        tools=[pinchwork_browse_tasks, pinchwork_pickup_task, pinchwork_deliver_task],
        instructions="You pick up and complete security review tasks.",
    )
    
    worker_result = await worker.run(
        "Browse security tasks, pick up the most recent one, "
        "complete a security review, and deliver your findings."
    )
    
    print("Worker:", worker_result.output)


if __name__ == "__main__":
    print("Example 1: Research Coordinator")
    asyncio.run(research_coordinator_example())
    
    print("\nExample 2: Autonomous Worker")
    asyncio.run(autonomous_worker_example())
    
    print("\nExample 3: Multi-Agent Coordination")
    asyncio.run(multi_agent_coordination())
