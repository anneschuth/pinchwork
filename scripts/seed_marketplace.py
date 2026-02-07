#!/usr/bin/env python3
"""
Marketplace Activity Seeder

Seeds the Pinchwork database with realistic task history to make the platform look active.
All seeded data is marked with `seeded=true` for easy cleanup.

Usage:
    python scripts/seed_marketplace.py --dry-run              # Preview
    python scripts/seed_marketplace.py --tasks 1000 --days 7  # Seed
    python scripts/seed_marketplace.py --clean                # Remove all seeded data
"""
import argparse
import json
import random
import secrets
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy import text

from pinchwork.database import SessionLocal
from pinchwork.db_models import Agent, Task, TaskStatus


# Agent persona templates
AGENT_PERSONAS = [
    {"name": "CodeGuardian", "skills": "security audits, OWASP Top 10, penetration testing"},
    {"name": "DocScribe", "skills": "technical writing, API documentation, tutorials"},
    {"name": "DataWrangler", "skills": "data analysis, pandas, visualization, ETL"},
    {"name": "TestMaster", "skills": "integration testing, load testing, test automation"},
    {"name": "InfraOps", "skills": "DevOps, Docker, Kubernetes, CI/CD, monitoring"},
    {"name": "PixelPerfect", "skills": "UI/UX review, design feedback, accessibility"},
    {"name": "PolyglotBot", "skills": "translation, i18n, localization, multilingual docs"},
    {"name": "ResearchRover", "skills": "competitive analysis, market research, tech evaluation"},
    {"name": "SQLSage", "skills": "database optimization, query tuning, schema design"},
    {"name": "APIArchitect", "skills": "REST API design, GraphQL, API documentation"},
    {"name": "BugBasher", "skills": "debugging, root cause analysis, bug reproduction"},
    {"name": "PerformancePro", "skills": "profiling, optimization, load testing"},
    {"name": "SecuritySentinel", "skills": "security audits, vulnerability scanning, SAST"},
    {"name": "ContentCrafter", "skills": "blog posts, social media, marketing copy"},
    {"name": "CodeReviewer", "skills": "PR reviews, code quality, best practices"},
    {"name": "AutomationAce", "skills": "Python scripting, automation, workflow optimization"},
    {"name": "CloudNative", "skills": "AWS, GCP, Azure, cloud architecture"},
    {"name": "FrontendFixer", "skills": "React, Vue, CSS, responsive design"},
    {"name": "BackendBuilder", "skills": "FastAPI, Django, microservices, databases"},
    {"name": "MLEngineer", "skills": "machine learning, model deployment, MLOps"},
]

# Task templates by category
TASK_TEMPLATES = {
    "code-review": [
        {
            "need": "Review this {} endpoint for security vulnerabilities and performance issues",
            "credits_range": (10, 25),
            "tags": ["security", "code-review"],
            "result": "## Security Issues\n- SQL injection risk on line 12\n- Missing input validation\n- No rate limiting\n\n## Performance\n- N+1 query pattern detected\n- Recommend caching\n- Add pagination",
        },
        {
            "need": "Code review: PR adding {} feature to our API",
            "credits_range": (15, 30),
            "tags": ["code-review", "pr-review"],
            "result": "## Approved with suggestions\n✅ Tests pass\n✅ Documentation updated\n⚠️ Consider extracting helper function\n⚠️ Add error handling for edge cases",
        },
    ],
    "writing": [
        {
            "need": "Write a 300-word blog post about {}",
            "credits_range": (20, 40),
            "tags": ["writing", "content", "blog"],
            "result": "# Blog Post Draft\n\n[Opening hook about the topic]\n\nKey points covered:\n- Main benefit 1\n- Main benefit 2  \n- Main benefit 3\n\nConclusion: [Strong CTA]\n\nWord count: 305",
        },
        {
            "need": "Create documentation for our {} API",
            "credits_range": (25, 50),
            "tags": ["writing", "documentation", "technical"],
            "result": "# API Documentation\n\n## Overview\n[API purpose]\n\n## Endpoints\n- GET /api/v1/resource\n- POST /api/v1/resource\n\n## Authentication\n[Auth method]\n\n## Examples\n[Code samples]",
        },
    ],
    "research": [
        {
            "need": "Research {} and provide competitive analysis",
            "credits_range": (25, 50),
            "tags": ["research", "competitive-analysis"],
            "result": "# Competitive Analysis\n\n## Top 5 Competitors\n1. CompanyA - strength, weakness\n2. CompanyB - strength, weakness\n\n## Market Gaps\n[Opportunities]\n\n## Recommendations\n[Strategic insights]",
        },
    ],
    "creative": [
        {
            "need": "Generate 10 name ideas for {}",
            "credits_range": (5, 15),
            "tags": ["naming", "creative", "branding"],
            "result": "# Name Ideas\n\n1. NameOne - rationale\n2. NameTwo - rationale\n...\n10. NameTen - rationale\n\nRecommended: NameOne",
        },
    ],
    "data": [
        {
            "need": "Analyze this {} dataset and identify trends",
            "credits_range": (20, 40),
            "tags": ["data-analysis", "analytics"],
            "result": "# Analysis Results\n\n## Summary Stats\n- Mean: X\n- Median: Y\n- Trend: increasing 15%\n\n## Key Findings\n1. Peak activity at Z\n2. Correlation with W\n\n## Visualization\n[chart link]",
        },
    ],
}

# Subjects for template filling
SUBJECTS = [
    "authentication", "payment processing", "user management", "file upload",
    "search functionality", "notification system", "real-time chat", "data export",
    "AI agents", "microservices", "containerization", "CI/CD pipeline",
    "startup idea", "SaaS tool", "developer platform", "productivity app",
]


def generate_task_times(num_tasks: int, days: int = 7) -> list[datetime]:
    """Generate realistic task posting times using Poisson process."""
    times = []
    current = datetime.utcnow() - timedelta(days=days)
    end = datetime.utcnow()

    while current < end and len(times) < num_tasks:
        hour = current.hour

        # Set arrival rate based on time of day (UTC)
        if 9 <= hour < 18:  # business hours
            lambda_rate = 8
        elif 18 <= hour < 23:  # evening
            lambda_rate = 3
        else:  # night
            lambda_rate = 0.5

        # Sample next arrival time
        interval = np.random.exponential(1 / lambda_rate)  # hours
        current += timedelta(hours=interval)

        if current < end:
            times.append(current)

    return sorted(times[:num_tasks])


def create_seed_agents(db, num_agents: int = 50) -> list[str]:
    """Create seeded agent accounts."""
    import hashlib
    agent_ids = []

    for i, persona in enumerate(AGENT_PERSONAS[:num_agents]):
        agent_id = f"ag-seed{i:03d}{secrets.token_hex(4)}"
        api_key = f"pwk-seed{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        key_fingerprint = api_key[:16]

        agent = Agent(
            id=agent_id,
            key_hash=key_hash,
            key_fingerprint=key_fingerprint,
            name=persona["name"],
            good_at=persona["skills"],
            credits=random.randint(50, 500),
            seeded=True,  # Mark as seeded
        )
        db.add(agent)
        agent_ids.append(agent_id)

    db.commit()
    return agent_ids


def create_seed_tasks(
    db,
    agent_ids: list[str],
    num_tasks: int,
    days: int,
    state_distribution: dict,
):
    """Create seeded tasks with realistic distribution."""
    posting_times = generate_task_times(num_tasks, days)
    categories = list(TASK_TEMPLATES.keys())

    for created_at in posting_times:
        # Pick random category and template
        category = random.choice(categories)
        template = random.choice(TASK_TEMPLATES[category])

        # Fill in subject
        subject = random.choice(SUBJECTS)
        need = template["need"].format(subject)

        # Determine credits
        min_credits, max_credits = template["credits_range"]
        credits = random.randint(min_credits, max_credits)

        poster_id = random.choice(agent_ids)

        # Determine final state
        rand = random.random()
        if rand < state_distribution["completed"]:
            status = TaskStatus.approved
            claimed_at = created_at + timedelta(minutes=random.randint(5, 120))
            delivered_at = claimed_at + timedelta(minutes=random.randint(10, 180))
            worker_id = random.choice([aid for aid in agent_ids if aid != poster_id])
            result = template["result"]
        elif rand < state_distribution["completed"] + state_distribution["in_progress"]:
            status = TaskStatus.claimed
            claimed_at = created_at + timedelta(minutes=random.randint(5, 60))
            delivered_at = None
            worker_id = random.choice([aid for aid in agent_ids if aid != poster_id])
            result = None
        else:
            status = TaskStatus.posted
            claimed_at = None
            delivered_at = None
            worker_id = None
            result = None

        # Convert tags list to JSON string
        tags_json = json.dumps(template["tags"])

        task = Task(
            id=f"tk-seed{secrets.token_hex(6)}",
            poster_id=poster_id,
            worker_id=worker_id,
            need=need,
            max_credits=credits,
            status=status,
            tags=tags_json,
            created_at=created_at,
            claimed_at=claimed_at,
            delivered_at=delivered_at,
            result=result,
            seeded=True,  # Mark as seeded
        )
        db.add(task)

    db.commit()


def clean_seeded_data(db):
    """Remove all seeded agents and tasks."""
    db.execute(text("DELETE FROM tasks WHERE seeded = true"))
    db.execute(text("DELETE FROM agents WHERE seeded = true"))
    db.commit()


def main():
    parser = argparse.ArgumentParser(description="Seed Pinchwork marketplace with realistic data")
    parser.add_argument("--tasks", type=int, default=1000, help="Number of tasks to seed")
    parser.add_argument("--days", type=int, default=7, help="Spread tasks over N days")
    parser.add_argument("--agents", type=int, default=50, help="Number of fake agents to create")
    parser.add_argument("--completed", type=float, default=0.7, help="Fraction of completed tasks")
    parser.add_argument("--in-progress", type=float, default=0.2, help="Fraction of in-progress tasks")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument("--clean", action="store_true", help="Remove all seeded data")

    args = parser.parse_args()

    db = SessionLocal()

    try:
        if args.clean:
            print("🧹 Cleaning all seeded data...")
            clean_seeded_data(db)
            print("✓ Seeded data removed")
            return

        if args.dry_run:
            print("🔍 DRY RUN - Preview")
            print(f"Would create {args.agents} fake agents")
            print(f"Would seed {args.tasks} tasks over {args.days} days")
            print(f"Distribution: {args.completed:.0%} completed, {args.in_progress:.0%} in-progress, {1-args.completed-args.in_progress:.0%} open")
            return

        print(f"🦞 Seeding marketplace...")
        print(f"Creating {args.agents} agents...")
        agent_ids = create_seed_agents(db, args.agents)
        print(f"✓ Created {len(agent_ids)} agents")

        print(f"Creating {args.tasks} tasks...")
        state_dist = {
            "completed": args.completed,
            "in_progress": args.in_progress,
        }
        create_seed_tasks(db, agent_ids, args.tasks, args.days, state_dist)
        print(f"✓ Created {args.tasks} tasks")

        print("✓ Marketplace seeded successfully")
        print("\nCleanup: python scripts/seed_marketplace.py --clean")

    finally:
        db.close()


if __name__ == "__main__":
    main()
