"""
Marketplace Activity Seeder - Drip Feed Mode

Continuously creates realistic background activity to make the marketplace look active.
Runs as a background task, creating 0-3 tasks every 10 minutes based on time of day.

All seeded data is marked with `seeded=true` for easy filtering and cleanup.
"""

import asyncio
import hashlib
import json
import logging
import random
import secrets
from datetime import datetime, timedelta

import numpy as np
from nanoid import generate
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from pinchwork.config import settings
from pinchwork.database import SessionLocal
from pinchwork.db_models import Agent, CreditLedger, Rating, Task, TaskStatus

logger = logging.getLogger(__name__)

# Global status tracking
_seeder_status = {
    "enabled": False,
    "last_run": None,
    "tasks_created": 0,
    "errors": 0,
    "last_error": None,
}


def get_seeder_status() -> dict:
    """Return seeder health status for /health endpoint."""
    return _seeder_status.copy()


# Agent personas (50 total)
AGENT_PERSONAS = [
    {
        "name": "CodeGuardian",
        "skills": "security audits, OWASP Top 10, penetration testing",
        "source": "GitHub",
    },
    {
        "name": "DocScribe",
        "skills": "technical writing, API documentation, tutorials",
        "source": "Dev.to",
    },
    {
        "name": "DataWrangler",
        "skills": "data analysis, pandas, visualization, ETL",
        "source": "Kaggle",
    },
    {
        "name": "TestMaster",
        "skills": "integration testing, load testing, test automation",
        "source": "HN",
    },
    {
        "name": "InfraOps",
        "skills": "DevOps, Docker, Kubernetes, CI/CD, monitoring",
        "source": "Reddit",
    },
    {
        "name": "PixelPerfect",
        "skills": "UI/UX review, design feedback, accessibility",
        "source": "Twitter",
    },
    {
        "name": "PolyglotBot",
        "skills": "translation, i18n, localization, multilingual docs",
        "source": "LinkedIn",
    },
    {
        "name": "ResearchRover",
        "skills": "competitive analysis, market research, tech evaluation",
        "source": "Moltbook",
    },
    {
        "name": "SQLSage",
        "skills": "database optimization, query tuning, schema design",
        "source": "GitHub",
    },
    {
        "name": "APIArchitect",
        "skills": "REST API design, GraphQL, API documentation",
        "source": "Dev.to",
    },
    {
        "name": "BugBasher",
        "skills": "debugging, root cause analysis, bug reproduction",
        "source": "HN",
    },
    {
        "name": "PerformancePro",
        "skills": "profiling, optimization, load testing",
        "source": "Reddit",
    },
    {
        "name": "SecuritySentinel",
        "skills": "security audits, vulnerability scanning, SAST",
        "source": "Twitter",
    },
    {
        "name": "ContentCrafter",
        "skills": "blog posts, social media, marketing copy",
        "source": "LinkedIn",
    },
    {
        "name": "CodeReviewer",
        "skills": "PR reviews, code quality, best practices",
        "source": "GitHub",
    },
    {
        "name": "AutomationAce",
        "skills": "Python scripting, automation, workflow optimization",
        "source": "Dev.to",
    },
    {"name": "CloudNative", "skills": "AWS, GCP, Azure, cloud architecture", "source": "HN"},
    {"name": "FrontendFixer", "skills": "React, Vue, CSS, responsive design", "source": "Reddit"},
    {
        "name": "BackendBuilder",
        "skills": "FastAPI, Django, microservices, databases",
        "source": "GitHub",
    },
    {
        "name": "MLEngineer",
        "skills": "machine learning, model deployment, MLOps",
        "source": "Kaggle",
    },
    {"name": "QAAutomator", "skills": "Selenium, Cypress, E2E testing", "source": "HN"},
    {"name": "MobileDev", "skills": "iOS, Android, React Native, Flutter", "source": "Reddit"},
    {"name": "BlockchainBuilder", "skills": "Solidity, smart contracts, Web3", "source": "Twitter"},
    {
        "name": "GameDevGuru",
        "skills": "Unity, Unreal, game mechanics, performance",
        "source": "Reddit",
    },
    {
        "name": "CyberDefender",
        "skills": "incident response, threat hunting, forensics",
        "source": "HN",
    },
    {"name": "NetworkNinja", "skills": "TCP/IP, routing, firewalls, VPN", "source": "LinkedIn"},
    {"name": "DatabaseDBA", "skills": "PostgreSQL, MySQL, replication, backup", "source": "GitHub"},
    {
        "name": "SearchOptimizer",
        "skills": "Elasticsearch, search relevance, ranking",
        "source": "Dev.to",
    },
    {"name": "CacheKing", "skills": "Redis, Memcached, caching strategies", "source": "HN"},
    {"name": "QueueMaster", "skills": "RabbitMQ, Kafka, event streaming", "source": "GitHub"},
    {"name": "VideoEncoder", "skills": "FFmpeg, video transcoding, streaming", "source": "Reddit"},
    {"name": "AudioEngineer", "skills": "audio processing, codecs, streaming", "source": "Twitter"},
    {"name": "ImageProcessor", "skills": "PIL, OpenCV, image optimization", "source": "GitHub"},
    {"name": "PDFWizard", "skills": "PDF generation, parsing, manipulation", "source": "Dev.to"},
    {"name": "CSVParser", "skills": "data import, ETL, data validation", "source": "Kaggle"},
    {"name": "JSONValidator", "skills": "schema validation, API contracts", "source": "GitHub"},
    {
        "name": "XMLParser",
        "skills": "SOAP, XML processing, legacy integration",
        "source": "LinkedIn",
    },
    {
        "name": "MarkdownMaster",
        "skills": "documentation, static sites, content",
        "source": "Dev.to",
    },
    {
        "name": "LaTeXExpert",
        "skills": "academic writing, typesetting, publishing",
        "source": "Twitter",
    },
    {"name": "RegexNinja", "skills": "pattern matching, text processing", "source": "Reddit"},
    {"name": "ShellScripter", "skills": "bash, zsh, automation scripts", "source": "HN"},
    {
        "name": "WindowsAdmin",
        "skills": "PowerShell, Active Directory, Windows Server",
        "source": "LinkedIn",
    },
    {
        "name": "LinuxSysAdmin",
        "skills": "Linux, systemd, shell, server management",
        "source": "Reddit",
    },
    {"name": "MacOSGuru", "skills": "macOS, Homebrew, Apple ecosystem", "source": "Twitter"},
    {
        "name": "GitExpert",
        "skills": "Git workflows, branching strategies, hooks",
        "source": "GitHub",
    },
    {"name": "CIEngineer", "skills": "Jenkins, CircleCI, GitHub Actions", "source": "Dev.to"},
    {"name": "TerraformPro", "skills": "IaC, Terraform, CloudFormation", "source": "HN"},
    {
        "name": "AnsibleAutomator",
        "skills": "configuration management, provisioning",
        "source": "GitHub",
    },
    {"name": "PrometheusOps", "skills": "monitoring, alerting, observability", "source": "Reddit"},
    {"name": "GrafanaDasher", "skills": "dashboards, visualization, metrics", "source": "LinkedIn"},
]

# Task templates grouped by category
TASK_TEMPLATES = {
    "code-review": [
        {
            "need": "Review authentication endpoint for JWT validation",
            "credits_range": (12, 22),
            "tags": ["security", "code-review", "auth"],
            "result": "Security review complete. Found 3 issues (1 high, 1 med, 1 low).",
        },
        {
            "need": "Code review for payment module",
            "credits_range": (18, 35),
            "tags": ["code-review", "payments", "critical"],
            "result": "Reviewed payment logic. Idempotency good, needs retry logic.",
        },
        {
            "need": "PR review: GraphQL subscriptions",
            "credits_range": (15, 28),
            "tags": ["code-review", "graphql", "real-time"],
            "result": "Architecture looks good. Add tests and docs before merge.",
        },
    ],
    "writing": [
        {
            "need": "Write API documentation for webhooks",
            "credits_range": (22, 45),
            "tags": ["writing", "documentation", "api"],
            "result": "Webhooks API docs complete with examples and error codes.",
        },
        {
            "need": "Blog post: REST to GraphQL migration",
            "credits_range": (35, 60),
            "tags": ["writing", "blog", "graphql"],
            "result": "Published 620-word blog with code examples. Word count: 620.",
        },
    ],
    "research": [
        {
            "need": "Research AI agent frameworks",
            "credits_range": (30, 60),
            "tags": ["research", "competitive-analysis", "ai"],
            "result": "Compared 12 frameworks. Recommend LangChain for Python teams.",
        },
    ],
    "testing": [
        {
            "need": "Load test the API - 10K concurrent users, find breaking points",
            "credits_range": (30, 60),
            "tags": ["testing", "load-test", "performance"],
            "result": (
                "# Load Test Results\n\n## Breaking Point: 7,200 concurrent users\n"
                "- P50: 450ms → 2.1s\n- Errors: 0.1% → 8.3%\n"
                "- Cause: DB connection pool exhaustion\n\n## Recommendations\n"
                "- Increase pool to 200\n- Add Redis caching\n- Fix N+1 queries"
            ),
        },
    ],
}

# Flatten all templates
ALL_TEMPLATES = []
for category_templates in TASK_TEMPLATES.values():
    ALL_TEMPLATES.extend(category_templates)


def check_migration_applied(db) -> bool:
    """Check if migration 006 (seeded column) has been applied."""
    try:
        db.execute(text("SELECT seeded FROM agents LIMIT 1"))
        return True
    except OperationalError:
        return False


def ensure_seeded_agents(db) -> list[str]:
    """
    Ensure seeded agent pool exists. Creates on first run, loads on subsequent runs.
    Returns list of seeded agent IDs.
    Uses deterministic IDs to prevent duplicates on crash/restart.
    """
    # Check if seeded agents already exist
    result = db.execute(text("SELECT id FROM agents WHERE seeded = true"))
    existing_ids = [row[0] for row in result.fetchall()]

    if existing_ids:
        logger.debug(f"Loaded {len(existing_ids)} existing seeded agents")
        return existing_ids

    # Create initial agent pool with deterministic IDs
    logger.info(f"Creating initial pool of {len(AGENT_PERSONAS)} seeded agents...")
    agent_ids = []

    for i, persona in enumerate(AGENT_PERSONAS):
        # Deterministic ID based on index (prevents duplicates)
        agent_id = f"ag-seed{i:03d}{hashlib.sha256(persona['name'].encode()).hexdigest()[:8]}"

        # Check if already exists (idempotency)
        existing = db.execute(
            text("SELECT id FROM agents WHERE id = :id"), {"id": agent_id}
        ).first()

        if existing:
            logger.debug(f"Agent {agent_id} already exists, skipping")
            agent_ids.append(agent_id)
            continue

        api_key = f"pwk-seed{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        key_fingerprint = api_key[:16]
        referral_code = f"ref-seed{secrets.token_urlsafe(8)}"

        agent = Agent(
            id=agent_id,
            key_hash=key_hash,
            key_fingerprint=key_fingerprint,
            name=persona["name"],
            good_at=persona["skills"],
            credits=1000,
            referral_code=referral_code,
            referral_source=persona.get("source", "organic"),
            seeded=True,
        )
        db.add(agent)
        agent_ids.append(agent_id)

    db.commit()
    logger.info(f"✓ Created {len(agent_ids)} seeded agents")
    return agent_ids


def create_seeded_task(db, agent_ids: list[str]) -> None:
    """Create one seeded task with realistic workflow and proper error handling."""
    # Safety check: need at least 2 agents (poster + worker)
    if len(agent_ids) < 2:
        logger.warning(f"Insufficient agents ({len(agent_ids)}), need at least 2")
        return

    template = random.choice(ALL_TEMPLATES)

    min_credits, max_credits = template["credits_range"]
    max_credits_amount = random.randint(min_credits, max_credits)

    poster_id = random.choice(agent_ids)

    # Determine task outcome (weighted toward completion)
    rand = random.random()

    # All timestamps in the PAST (fix #1: future timestamps)
    now = datetime.utcnow()
    created_at = now - timedelta(minutes=random.randint(10, 120))  # 10-120 min ago
    task_id = f"tk-seed{generate(size=12)}"

    try:
        if rand < 0.75:  # 75% complete quickly
            status = TaskStatus.approved
            claimed_at = created_at + timedelta(minutes=random.randint(5, 60))
            delivered_at = claimed_at + timedelta(minutes=random.randint(10, 120))
            approved_at = delivered_at + timedelta(minutes=random.randint(1, 30))
            expires_at = created_at + timedelta(hours=72)

            # Pick different agent as worker (fix #6: empty pool)
            eligible_workers = [aid for aid in agent_ids if aid != poster_id]
            if not eligible_workers:
                logger.warning("No eligible workers, skipping task")
                return
            worker_id = random.choice(eligible_workers)
            result = template["result"]

            # Credits
            credits_charged = random.randint(int(max_credits_amount * 0.9), max_credits_amount)
            platform_fee = int(credits_charged * 0.1)
            worker_payout = credits_charged - platform_fee

            # Transaction safety (fix #2): all updates in one commit block
            # Credit arithmetic with floor at 0 (fix #3)
            db.execute(
                text("""
                    UPDATE agents
                    SET credits = CASE
                        WHEN credits >= :amount THEN credits - :amount
                        ELSE 0
                    END,
                    tasks_posted = tasks_posted + 1
                    WHERE id = :id
                """),
                {"amount": credits_charged, "id": poster_id},
            )

            db.execute(
                text("""
                    UPDATE agents
                    SET credits = credits + :amount,
                        tasks_completed = tasks_completed + 1
                    WHERE id = :id
                """),
                {"amount": worker_payout, "id": worker_id},
            )

            # Fix #7: Actually credit platform agent
            if settings.platform_agent_id:
                result = db.execute(
                    text("UPDATE agents SET credits = credits + :amount WHERE id = :id"),
                    {"amount": platform_fee, "id": settings.platform_agent_id},
                )
                if result.rowcount == 0:
                    logger.warning(
                        f"Platform agent {settings.platform_agent_id} not found, fee not collected"
                    )

            # Ledger entries
            db.add(
                CreditLedger(
                    id=f"cl-seed{generate(size=12)}",
                    agent_id=poster_id,
                    amount=-credits_charged,
                    reason="task_payment",
                    task_id=task_id,
                    created_at=approved_at,
                )
            )
            db.add(
                CreditLedger(
                    id=f"cl-seed{generate(size=12)}",
                    agent_id=worker_id,
                    amount=worker_payout,
                    reason="task_completed",
                    task_id=task_id,
                    created_at=approved_at,
                )
            )

            if settings.platform_agent_id:
                db.add(
                    CreditLedger(
                        id=f"cl-seed{generate(size=12)}",
                        agent_id=settings.platform_agent_id,
                        amount=platform_fee,
                        reason="platform_fee",
                        task_id=task_id,
                        created_at=approved_at,
                    )
                )

            # Rating
            rating_score = random.choice([3, 4, 4, 4, 5, 5])
            db.add(
                Rating(
                    task_id=task_id,
                    rater_id=poster_id,
                    rated_id=worker_id,
                    score=rating_score,
                    created_at=approved_at + timedelta(minutes=random.randint(1, 15)),
                )
            )

            # Fix #8: Batch reputation updates (done outside this function)
            # We'll update reputation in bulk every hour instead of per-task

        elif rand < 0.90:  # 15% in progress
            status = TaskStatus.claimed
            claimed_at = created_at + timedelta(minutes=random.randint(5, 30))
            delivered_at = None
            approved_at = None
            expires_at = created_at + timedelta(hours=72)

            eligible_workers = [aid for aid in agent_ids if aid != poster_id]
            if not eligible_workers:
                logger.warning("No eligible workers, skipping task")
                return
            worker_id = random.choice(eligible_workers)
            result = None
            credits_charged = None

            # Escrow with floor at 0
            escrow_amount = random.randint(int(max_credits_amount * 0.9), max_credits_amount)
            db.execute(
                text("""
                    UPDATE agents
                    SET credits = CASE
                        WHEN credits >= :amount THEN credits - :amount
                        ELSE 0
                    END,
                    tasks_posted = tasks_posted + 1
                    WHERE id = :id
                """),
                {"amount": escrow_amount, "id": poster_id},
            )

            db.add(
                CreditLedger(
                    id=f"cl-seed{generate(size=12)}",
                    agent_id=poster_id,
                    amount=-escrow_amount,
                    reason="task_escrow",
                    task_id=task_id,
                    created_at=claimed_at,
                )
            )

        else:  # 10% stay open
            status = TaskStatus.posted
            claimed_at = None
            delivered_at = None
            approved_at = None
            expires_at = created_at + timedelta(hours=72)
            worker_id = None
            result = None
            credits_charged = None

            db.execute(
                text("UPDATE agents SET tasks_posted = tasks_posted + 1 WHERE id = :id"),
                {"id": poster_id},
            )

        # Optional context
        context = None
        if random.random() < 0.3:
            env = random.choice(["production", "staging", "development"])
            context = f"Additional context: This is for our {env} environment."

        tags_json = json.dumps(template["tags"])

        task = Task(
            id=task_id,
            poster_id=poster_id,
            worker_id=worker_id,
            need=template["need"],
            context=context,
            max_credits=max_credits_amount,
            credits_charged=credits_charged,
            status=status,
            tags=tags_json,
            created_at=created_at,
            claimed_at=claimed_at,
            delivered_at=delivered_at,
            expires_at=expires_at,
            result=result,
            seeded=True,
        )
        db.add(task)
        db.commit()  # Commit successful task

    except Exception as e:
        # Fix #5: Error handling in task creation
        logger.error(f"Failed to create seeded task: {e}", exc_info=True)
        db.rollback()
        raise  # Re-raise so caller can track errors


def update_seeded_reputations(db) -> None:
    """Batch update reputation for all seeded agents (fix #8: efficiency)."""
    try:
        db.execute(
            text("""
            UPDATE agents
            SET reputation = (
                SELECT COALESCE(AVG(score), 0)
                FROM ratings
                WHERE rated_id = agents.id
            )
            WHERE seeded = true
        """)
        )
        db.commit()
    except Exception as e:
        logger.error(f"Failed to update seeded reputations: {e}", exc_info=True)
        db.rollback()


async def drip_seeder_loop():
    """Background task that drips seeded tasks into the marketplace."""
    global _seeder_status

    logger.info("🦞 Marketplace seeder starting...")

    # Fix #9: Check migration applied
    db = SessionLocal()
    try:
        if not check_migration_applied(db):
            logger.error("Migration 006 (seeded column) not applied, seeder disabled")
            _seeder_status["enabled"] = False
            _seeder_status["last_error"] = "Migration 006 not applied"
            return
    finally:
        db.close()

    logger.info("🦞 Marketplace seeder started (drip mode)")
    _seeder_status["enabled"] = True

    reputation_update_counter = 0

    while True:
        try:
            if not settings.seed_marketplace_drip:
                logger.debug("Drip seeding disabled, sleeping...")
                await asyncio.sleep(600)  # Check every 10 min
                continue

            db = SessionLocal()
            try:
                # Ensure agent pool exists (fix #11: idempotency)
                agent_ids = ensure_seeded_agents(db)

                # Calculate tasks to create based on time of day
                hour = datetime.utcnow().hour

                if 9 <= hour < 18:
                    lambda_rate = settings.seed_drip_rate_business
                elif 18 <= hour < 23:
                    lambda_rate = settings.seed_drip_rate_evening
                else:
                    lambda_rate = settings.seed_drip_rate_night

                # Poisson sample for 10-minute interval (capped at 10 to prevent outliers)
                num_tasks = min(np.random.poisson(lambda_rate / 6.0), 10)

                if num_tasks > 0:
                    logger.info(
                        f"Creating {num_tasks} seeded tasks (hour={hour}, rate={lambda_rate}/h)"
                    )

                    created = 0
                    for _ in range(num_tasks):
                        try:
                            create_seeded_task(db, agent_ids)
                            created += 1
                            _seeder_status["tasks_created"] += 1
                        except Exception as e:
                            _seeder_status["errors"] += 1
                            _seeder_status["last_error"] = str(e)
                            # Continue with next task

                    logger.debug(f"✓ Created {created}/{num_tasks} tasks")

                # Update reputations hourly (fix #8: batch instead of per-task)
                reputation_update_counter += 1
                if reputation_update_counter >= 6:  # Every 60 minutes (6 × 10min)
                    update_seeded_reputations(db)
                    reputation_update_counter = 0

                _seeder_status["last_run"] = datetime.utcnow().isoformat()

            finally:
                db.close()

        except Exception as e:
            # Fix #10: Track errors in status
            logger.error(f"Seeder loop error: {e}", exc_info=True)
            _seeder_status["errors"] += 1
            _seeder_status["last_error"] = str(e)

        # Run every 10 minutes
        await asyncio.sleep(600)
