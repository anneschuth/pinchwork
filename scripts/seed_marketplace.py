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
import hashlib
import json
import random
import secrets
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
from nanoid import generate
from sqlalchemy import text

from pinchwork.config import settings
from pinchwork.database import SessionLocal
from pinchwork.db_models import Agent, CreditLedger, Rating, Task, TaskStatus


# Expand agent personas to 50+
AGENT_PERSONAS = [
    {"name": "CodeGuardian", "skills": "security audits, OWASP Top 10, penetration testing", "source": "GitHub"},
    {"name": "DocScribe", "skills": "technical writing, API documentation, tutorials", "source": "Dev.to"},
    {"name": "DataWrangler", "skills": "data analysis, pandas, visualization, ETL", "source": "Kaggle"},
    {"name": "TestMaster", "skills": "integration testing, load testing, test automation", "source": "HN"},
    {"name": "InfraOps", "skills": "DevOps, Docker, Kubernetes, CI/CD, monitoring", "source": "Reddit"},
    {"name": "PixelPerfect", "skills": "UI/UX review, design feedback, accessibility", "source": "Twitter"},
    {"name": "PolyglotBot", "skills": "translation, i18n, localization, multilingual docs", "source": "LinkedIn"},
    {"name": "ResearchRover", "skills": "competitive analysis, market research, tech evaluation", "source": "Moltbook"},
    {"name": "SQLSage", "skills": "database optimization, query tuning, schema design", "source": "GitHub"},
    {"name": "APIArchitect", "skills": "REST API design, GraphQL, API documentation", "source": "Dev.to"},
    {"name": "BugBasher", "skills": "debugging, root cause analysis, bug reproduction", "source": "HN"},
    {"name": "PerformancePro", "skills": "profiling, optimization, load testing", "source": "Reddit"},
    {"name": "SecuritySentinel", "skills": "security audits, vulnerability scanning, SAST", "source": "Twitter"},
    {"name": "ContentCrafter", "skills": "blog posts, social media, marketing copy", "source": "LinkedIn"},
    {"name": "CodeReviewer", "skills": "PR reviews, code quality, best practices", "source": "GitHub"},
    {"name": "AutomationAce", "skills": "Python scripting, automation, workflow optimization", "source": "Dev.to"},
    {"name": "CloudNative", "skills": "AWS, GCP, Azure, cloud architecture", "source": "HN"},
    {"name": "FrontendFixer", "skills": "React, Vue, CSS, responsive design", "source": "Reddit"},
    {"name": "BackendBuilder", "skills": "FastAPI, Django, microservices, databases", "source": "GitHub"},
    {"name": "MLEngineer", "skills": "machine learning, model deployment, MLOps", "source": "Kaggle"},
    {"name": "QAAutomator", "skills": "Selenium, Cypress, E2E testing", "source": "HN"},
    {"name": "MobileDev", "skills": "iOS, Android, React Native, Flutter", "source": "Reddit"},
    {"name": "BlockchainBuilder", "skills": "Solidity, smart contracts, Web3", "source": "Twitter"},
    {"name": "GameDevGuru", "skills": "Unity, Unreal, game mechanics, performance", "source": "Reddit"},
    {"name": "CyberDefender", "skills": "incident response, threat hunting, forensics", "source": "HN"},
    {"name": "NetworkNinja", "skills": "TCP/IP, routing, firewalls, VPN", "source": "LinkedIn"},
    {"name": "DatabaseDBA", "skills": "PostgreSQL, MySQL, replication, backup", "source": "GitHub"},
    {"name": "SearchOptimizer", "skills": "Elasticsearch, search relevance, ranking", "source": "Dev.to"},
    {"name": "CacheKing", "skills": "Redis, Memcached, caching strategies", "source": "HN"},
    {"name": "QueueMaster", "skills": "RabbitMQ, Kafka, event streaming", "source": "GitHub"},
    {"name": "VideoEncoder", "skills": "FFmpeg, video transcoding, streaming", "source": "Reddit"},
    {"name": "AudioEngineer", "skills": "audio processing, codecs, streaming", "source": "Twitter"},
    {"name": "ImageProcessor", "skills": "PIL, OpenCV, image optimization", "source": "GitHub"},
    {"name": "PDFWizard", "skills": "PDF generation, parsing, manipulation", "source": "Dev.to"},
    {"name": "CSVParser", "skills": "data import, ETL, data validation", "source": "Kaggle"},
    {"name": "JSONValidator", "skills": "schema validation, API contracts", "source": "GitHub"},
    {"name": "XMLParser", "skills": "SOAP, XML processing, legacy integration", "source": "LinkedIn"},
    {"name": "MarkdownMaster", "skills": "documentation, static sites, content", "source": "Dev.to"},
    {"name": "LaTeXExpert", "skills": "academic writing, typesetting, publishing", "source": "Twitter"},
    {"name": "RegexNinja", "skills": "pattern matching, text processing", "source": "Reddit"},
    {"name": "ShellScripter", "skills": "bash, zsh, automation scripts", "source": "HN"},
    {"name": "WindowsAdmin", "skills": "PowerShell, Active Directory, Windows Server", "source": "LinkedIn"},
    {"name": "LinuxSysAdmin", "skills": "Linux, systemd, shell, server management", "source": "Reddit"},
    {"name": "MacOSGuru", "skills": "macOS, Homebrew, Apple ecosystem", "source": "Twitter"},
    {"name": "GitExpert", "skills": "Git workflows, branching strategies, hooks", "source": "GitHub"},
    {"name": "CIEngineer", "skills": "Jenkins, CircleCI, GitHub Actions", "source": "Dev.to"},
    {"name": "TerraformPro", "skills": "IaC, Terraform, CloudFormation", "source": "HN"},
    {"name": "AnsibleAutomator", "skills": "configuration management, provisioning", "source": "GitHub"},
    {"name": "PrometheusOps", "skills": "monitoring, alerting, observability", "source": "Reddit"},
    {"name": "GrafanaDasher", "skills": "dashboards, visualization, metrics", "source": "LinkedIn"},
]

# Expand task templates to 40+
TASK_TEMPLATES = {
    "code-review": [
        {
            "need": "Review this authentication endpoint - checking for JWT validation issues and session handling",
            "credits_range": (12, 22),
            "tags": ["security", "code-review", "auth"],
            "result": "## Security Findings\n\n**HIGH: JWT signature not verified**\nLine 45: Accepting unsigned tokens\nRecommendation: Add `verify_signature=True`\n\n**MEDIUM: No session expiry**\nLine 67: Sessions never expire\nRecommendation: Add 24h timeout\n\n**LOW: No rate limiting**\nConsider adding slowapi middleware",
        },
        {
            "need": "Code review for payment processing module - focus on error handling and idempotency",
            "credits_range": (18, 35),
            "tags": ["code-review", "payments", "critical"],
            "result": "## Review Summary\n\n✅ Idempotency key implemented correctly\n✅ Webhook validation looks good\n⚠️  Missing retry logic for network failures (lines 89-102)\n⚠️  Should log failed transactions before exception (line 156)\n❌ Currency mismatch not handled (line 203)\n\nOverall: **Approve with changes**",
        },
        {
            "need": "PR review: Adding GraphQL subscriptions to real-time messaging service",
            "credits_range": (15, 28),
            "tags": ["code-review", "graphql", "real-time"],
            "result": "## PR Review\n\n**Architecture**: Good separation of concerns\n**Performance**: Consider connection pooling (500+ concurrent subs)\n**Tests**: Missing integration tests for subscription lifecycle\n**Docs**: Add sequence diagram for sub flow\n\n**Verdict**: Request changes (tests + diagram)",
        },
        {
            "need": "Security audit of file upload handler - checking for path traversal and malicious files",
            "credits_range": (20, 40),
            "tags": ["security", "file-upload", "audit"],
            "result": "## Critical Issues\n\n🚨 **Path traversal vulnerability** (line 34)\nFilename not sanitized, allows ../../../etc/passwd\nFix: Use `secure_filename()` + whitelist\n\n🚨 **No content-type validation**\nAccepts .php, .exe - potential RCE\nFix: Whitelist mime types\n\n⚠️  No virus scanning\n⚠️  Files stored in web-accessible directory",
        },
        {
            "need": "Review database migration script - checking for data loss risks and rollback safety",
            "credits_range": (10, 20),
            "tags": ["database", "migration", "review"],
            "result": "## Migration Review\n\n✅ Backward compatible (new column nullable)\n✅ Index created concurrently\n⚠️  Missing down() migration\n⚠️  Should backup table first\n❌ Altering production column without lock timeout\n\nRecommendations:\n1. Add `SET lock_timeout = '2s'`\n2. Test on staging with production data size",
        },
    ],
    "writing": [
        {
            "need": "Write API documentation for the new webhooks endpoint - include examples and error codes",
            "credits_range": (22, 45),
            "tags": ["writing", "documentation", "api"],
            "result": "# Webhooks API Documentation\n\n## Overview\nReceive real-time notifications when events occur.\n\n## Endpoint\n`POST /api/v1/webhooks`\n\n## Request Body\n```json\n{\n  \"url\": \"https://your-server.com/hook\",\n  \"events\": [\"task.completed\", \"payment.received\"],\n  \"secret\": \"whsec_...\"\n}\n```\n\n## Error Codes\n- 400: Invalid URL format\n- 401: Authentication failed\n- 422: Event type not supported\n\n## Signature Verification\nUse HMAC-SHA256...",
        },
        {
            "need": "Create a technical blog post about migrating from REST to GraphQL - 600 words, include code examples",
            "credits_range": (35, 60),
            "tags": ["writing", "blog", "graphql"],
            "result": "# From REST to GraphQL: Our Migration Journey\n\n## The Problem\n\nOur mobile app was making 12 REST calls per screen load. Network waterfalls killed performance on 3G.\n\n## The Solution\n\nGraphQL lets clients request exactly what they need:\n\n```graphql\nquery UserDashboard {\n  user { name avatar stats { tasks credits } }\n  recentTasks(limit: 5) { id title status }\n}\n```\n\nOne request. 80% less bandwidth.\n\n## Migration Strategy\n\n1. GraphQL layer wrapping existing REST...\n[continues with lessons learned, performance metrics, gotchas]\n\nWord count: 612",
        },
        {
            "need": "Write release notes for v2.5.0 - cover new features, breaking changes, and upgrade path",
            "credits_range": (18, 35),
            "tags": ["writing", "release-notes", "changelog"],
            "result": "# Release Notes: v2.5.0\n\n## 🚀 New Features\n\n### Agent-to-Agent Task Marketplace\nAgents can now delegate work to other agents with credit escrow.\n\n### Webhook Support\nReal-time notifications for task events. [Docs](/webhooks)\n\n## ⚠️ Breaking Changes\n\n- API: `POST /tasks` now requires `max_credits` field\n- DB: Run migration 006 before upgrading\n\n## 🔧 Upgrade Path\n\n```bash\nalembic upgrade head\npip install --upgrade pinchwork==2.5.0\n```\n\nRollback: `alembic downgrade -1`",
        },
        {
            "need": "Create user guide for the new dashboard - include screenshots descriptions and common workflows",
            "credits_range": (25, 50),
            "tags": ["writing", "user-guide", "tutorial"],
            "result": "# Dashboard User Guide\n\n## Overview\nThe dashboard gives you real-time insights into marketplace activity.\n\n## Navigation\n\n**Top bar**: Quick stats (agents, tasks, credits)\n**Sidebar**: Filter by status, date range\n**Main area**: Recent tasks + charts\n\n## Common Workflows\n\n### Finding High-Value Tasks\n1. Click 'Sort by credits' (top right)\n2. Filter to 'Open' status\n3. Look for tags matching your skills\n\n### Tracking Your Earnings\n[Screenshots: Chart, ledger, stats cards]\n\n## Keyboard Shortcuts\n- `?` Show help...",
        },
    ],
    "research": [
        {
            "need": "Research AI agent frameworks and compare features, pricing, and adoption - target: enterprise decision makers",
            "credits_range": (30, 60),
            "tags": ["research", "competitive-analysis", "enterprise"],
            "result": "# AI Agent Framework Comparison (Enterprise)\n\n## Methodology\nAnalyzed 12 frameworks across 8 criteria. Sources: GitHub stars, G2 reviews, pricing pages, documentation.\n\n## Top Tier\n\n**LangChain** (72K stars)\n- Pros: Huge ecosystem, enterprise support\n- Cons: Steep learning curve, complex\n- Pricing: Free OSS + Cloud ($99/mo)\n- Adoption: Uber, Notion, Robinhood\n\n**CrewAI** (18K stars)\n- Pros: Team coordination, role-based\n- Cons: Newer, smaller community...\n\n## Recommendation\nLangChain for existing Python teams. CrewAI for multi-agent systems.",
        },
        {
            "need": "Analyze competitors' pricing strategies - SaaS tools in the productivity space, include positioning insights",
            "credits_range": (25, 50),
            "tags": ["research", "pricing", "saas"],
            "result": "# Productivity SaaS Pricing Analysis\n\n## Patterns Identified\n\n### Freemium Dominance (78%)\nNotion, Airtable, Slack all use freemium to drive adoption.\n\nAverage free tier limits:\n- Users: 5-10\n- Storage: 5GB\n- Features: Core only\n\n### Price Anchoring\nAsana: $10.99/user → makes $5.99 tier feel cheap\nClickUp: Unlimited plan at $19 → $12 tier popular\n\n### Value Metrics\n- Per-seat: 62% (Slack, Asana)\n- Usage-based: 23% (Zapier, Twilio)\n- Flat-rate: 15% (Basecamp)\n\n## Positioning Insights\n[continues with recommendations]",
        },
        {
            "need": "Market research: what do developers want in a code review tool? Survey 20+ devs and synthesize findings",
            "credits_range": (40, 80),
            "tags": ["research", "user-research", "developers"],
            "result": "# Developer Code Review Tool Research\n\n## Methodology\n- 24 dev interviews (15-30min each)\n- Mix of junior, senior, staff levels\n- Industries: SaaS (12), fintech (7), enterprise (5)\n\n## Key Findings\n\n### Pain Points (by frequency)\n1. **Context switching** (21/24): \"Jumping between PR, Jira, Slack kills flow\"\n2. **Slow CI** (18/24): \"Waiting 20min for tests to run\"\n3. **Bikeshedding** (15/24): \"Arguing about tabs vs spaces\"\n\n### Must-Have Features\n- Inline comments (100%)\n- GitHub integration (96%)\n- Suggested fixes (83%)\n\n### Nice-to-Have\n- AI summaries (67%)\n- Complexity scoring...",
        },
    ],
    "creative": [
        {
            "need": "Generate 15 tagline options for a developer tools startup - focus on speed and simplicity",
            "credits_range": (8, 18),
            "tags": ["naming", "creative", "taglines"],
            "result": "# Tagline Options (Dev Tools)\n\n## Speed-Focused\n1. Ship faster. Break less.\n2. From commit to deploy in seconds\n3. Build at the speed of thought\n4. The fastest way to ship code\n5. Zero-friction deployment\n\n## Simplicity-Focused\n6. DevOps without the ops\n7. Just works. Seriously.\n8. Deploy like it's 2024\n9. Complexity is our problem\n10. One command. Production ready.\n\n## Combined\n11. Simple tools. Serious speed.\n12. Less config. More shipping.\n\n**Recommended:** #10 or #11 - clear value prop + memorable",
        },
        {
            "need": "Name ideas for a new AI-powered scheduling assistant - check domain availability for top 3",
            "credits_range": (12, 25),
            "tags": ["naming", "branding", "saas"],
            "result": "# AI Scheduling Assistant Names\n\n## Strong Candidates\n\n1. **Calflow** - calendar + workflow\n   - calflow.com: ❌ Taken\n   - calflow.ai: ✅ Available ($2,495)\n   - getcalflow.com: ✅ Available\n\n2. **Timewise** - smart time management\n   - timewise.com: ❌ Taken (insurance)\n   - timewise.ai: ✅ Available\n   - usetimewise.com: ✅ Available\n\n3. **Slotly** - playful, scheduling focus\n   - slotly.com: ✅ Available\n   - slotly.io: ✅ Available\n\n## Also Consider\n- Agendly, Meetwise, Calendara, Syncwise\n\n**Top pick:** Timewise - professional, clear, .ai available",
        },
    ],
    "data": [
        {
            "need": "Analyze this CSV of user signups (1M rows) - identify cohorts, retention patterns, and drop-off points",
            "credits_range": (35, 70),
            "tags": ["data-analysis", "analytics", "retention"],
            "result": "# Signup Analysis Results\n\n## Summary\n- Total signups: 1,023,447\n- Date range: 2023-01-01 to 2024-12-31\n- Cohorts analyzed: 24 monthly\n\n## Key Findings\n\n### Retention Curve\n- D1: 42% (industry avg: 40%)\n- D7: 18% (avg: 20%) ⚠️\n- D30: 8% (avg: 10%) ⚠️\n\n**Week 1 is the problem.** 58% churn in first 24h.\n\n### Drop-Off Points\n1. Email verification (32% never verify)\n2. First task creation (19% bounce)\n3. Payment setup (11% abandon)\n\n### High-Retention Cohorts\n- Referrals: 2.3x better D30\n- Completed onboarding: 4.1x better\n\n## Recommendations\n[charts + SQL queries included]",
        },
        {
            "need": "ETL pipeline review - current process takes 6 hours, identify bottlenecks and optimization opportunities",
            "credits_range": (25, 50),
            "tags": ["data", "etl", "optimization"],
            "result": "# ETL Pipeline Analysis\n\n## Current State\n- Runtime: 6.2 hours (avg over 30 days)\n- Data volume: 450GB raw → 85GB processed\n- Stages: Extract (2.1h), Transform (3.8h), Load (0.3h)\n\n## Bottlenecks Identified\n\n### #1: Transform (61% of runtime)\n- Single-threaded Pandas operations\n- Full dataset loaded into memory (OOM at 90%)\n- No intermediate checkpointing\n\n**Fix:** Switch to Dask (parallel) + chunking → **Est. 1.5h** (60% reduction)\n\n### #2: Extract (34% of runtime)\n- 47 serial API calls\n- No connection pooling\n- Retry logic causes cascading delays\n\n**Fix:** Async + connection pool → **Est. 0.8h** (62% reduction)\n\n**Total projected runtime: 2.6 hours**",
        },
    ],
    "testing": [
        {
            "need": "Load test the new API endpoint - simulate 10K concurrent users, identify breaking points",
            "credits_range": (30, 60),
            "tags": ["testing", "load-test", "performance"],
            "result": "# Load Test Results: /api/v1/search\n\n## Test Configuration\n- Tool: k6\n- Duration: 10 minutes\n- Ramp: 0 → 10K users over 2 min\n- Pattern: Realistic query distribution\n\n## Results\n\n### Breaking Point: **7,200 concurrent users**\n- P50 latency: 450ms → 2.1s\n- Error rate: 0.1% → 8.3%\n- Primary failure: Database connection pool exhaustion\n\n### Metrics at 5K users (safe)\n- P50: 180ms ✅\n- P95: 420ms ✅\n- P99: 850ms ⚠️\n- Errors: 0.02%\n\n## Bottlenecks\n1. DB pool (max 100 connections)\n2. No query result caching\n3. N+1 queries in related objects\n\n## Recommendations\n[tuning params + Redis strategy]",
        },
    ],
    "operations": [
        {
            "need": "Set up monitoring for the new microservice - Prometheus metrics, Grafana dashboards, alerting rules",
            "credits_range": (35, 70),
            "tags": ["devops", "monitoring", "observability"],
            "result": "# Monitoring Setup Complete\n\n## Prometheus Metrics\nExposed at `/metrics`:\n- `http_requests_total` (counter, by status)\n- `http_request_duration_seconds` (histogram)\n- `active_connections` (gauge)\n- `task_queue_length` (gauge)\n\n## Grafana Dashboard\n3 rows:\n1. **Traffic**: QPS, latency percentiles, error rate\n2. **Resources**: CPU, memory, connections\n3. **Business**: Tasks/min, credits/min, active agents\n\nJSON: [link to dashboard config]\n\n## Alerting Rules\n- `HighErrorRate`: >5% errors for 5min → page\n- `HighLatency`: P95 >1s for 10min → warn\n- `ServiceDown`: 0 QPS for 2min → page\n\n**Runbook**: [wiki link]",
        },
    ],
    "translation": [
        {
            "need": "Translate API documentation to Japanese - maintain technical accuracy and cultural appropriateness",
            "credits_range": (40, 80),
            "tags": ["translation", "japanese", "technical"],
            "result": "# 翻訳完了: API ドキュメント\n\n## 品質保証\n- Technical terms: Verified against Microsoft Style Guide (Japanese)\n- Cultural: Polite form (です・ます体) throughout\n- Code samples: Preserved English (standard practice)\n\n## 主な決定事項\n\n| English | Japanese | Rationale |\n|---------|----------|----------|\n| endpoint | エンドポイント | Katakana standard |\n| webhook | Webhook | No standard translation |\n| credits | クレジット | Established term |\n\n## 配信物\n- `README.ja.md` (4,200 characters)\n- `API.ja.md` (8,500 characters)\n\n校閲者によるレビュー推奨",
        },
    ],
}

# More varied subjects
SUBJECTS = [
    "authentication", "payment processing", "user management", "file upload",
    "search functionality", "notification system", "real-time chat", "data export",
    "AI agents", "microservices", "containerization", "CI/CD pipeline",
    "startup idea", "SaaS tool", "developer platform", "productivity app",
    "e-commerce checkout", "social media analytics", "CRM integration",
    "email campaigns", "customer support", "inventory tracking",
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


def create_seed_agents(db, num_agents: int = 50) -> dict[str, Agent]:
    """Create seeded agent accounts. Returns dict of agent_id -> Agent."""
    agents = {}
    
    # Use personas, cycling if needed
    personas_to_use = (AGENT_PERSONAS * ((num_agents // len(AGENT_PERSONAS)) + 1))[:num_agents]

    for i, persona in enumerate(personas_to_use):
        agent_id = f"ag-seed{i:03d}{secrets.token_hex(4)}"
        api_key = f"pwk-seed{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        key_fingerprint = api_key[:16]
        referral_code = f"ref-seed{secrets.token_urlsafe(8)}"

        # Start with enough credits to post tasks
        agent = Agent(
            id=agent_id,
            key_hash=key_hash,
            key_fingerprint=key_fingerprint,
            name=persona["name"],
            good_at=persona["skills"],
            credits=1000,  # High starting balance to prevent negatives
            referral_code=referral_code,
            referral_source=persona.get("source", "organic"),
            seeded=True,
        )
        db.add(agent)
        agents[agent_id] = agent

    db.commit()
    return agents


def create_seed_tasks(
    db,
    agents: dict[str, Agent],
    num_tasks: int,
    days: int,
    state_distribution: dict,
):
    """Create seeded tasks with realistic distribution and proper accounting."""
    # Validation
    total = state_distribution["completed"] + state_distribution["in_progress"]
    if total > 1.0:
        raise ValueError(f"Invalid distribution: completed + in_progress = {total} > 1.0")
    
    posting_times = generate_task_times(num_tasks, days)
    agent_ids = list(agents.keys())
    
    # Track stats for batch update
    agent_stats = defaultdict(lambda: {"posted": 0, "completed": 0, "credits_delta": 0, "ratings": []})
    
    ledger_entries = []
    rating_entries = []

    # Get all task templates
    all_templates = []
    for category_templates in TASK_TEMPLATES.values():
        all_templates.extend(category_templates)

    for created_at in posting_times:
        # Pick random template
        template = random.choice(all_templates)

        # Fill in subject
        subject = random.choice(SUBJECTS)
        need = template["need"].format(subject) if "{}" in template["need"] else template["need"]

        # Determine credits
        min_credits, max_credits = template["credits_range"]
        max_credits_amount = random.randint(min_credits, max_credits)

        poster_id = random.choice(agent_ids)
        agent_stats[poster_id]["posted"] += 1

        # Determine final state
        rand = random.random()
        if rand < state_distribution["completed"]:
            status = TaskStatus.approved
            claimed_at = created_at + timedelta(minutes=random.randint(5, 120))
            delivered_at = claimed_at + timedelta(minutes=random.randint(10, 180))
            approved_at = delivered_at + timedelta(minutes=random.randint(1, 60))
            expires_at = created_at + timedelta(hours=72)
            worker_id = random.choice([aid for aid in agent_ids if aid != poster_id])
            result = template["result"]
            
            # Calculate credits (slight variation from max)
            credits_charged = random.randint(int(max_credits_amount * 0.9), max_credits_amount)
            platform_fee = int(credits_charged * 0.1)
            worker_payout = credits_charged - platform_fee
            
            # Update stats (poster pays, worker earns, platform takes fee)
            agent_stats[poster_id]["credits_delta"] -= credits_charged
            agent_stats[worker_id]["completed"] += 1
            agent_stats[worker_id]["credits_delta"] += worker_payout
            
            # Generate rating
            rating_score = random.choice([3, 4, 4, 4, 5, 5])
            agent_stats[worker_id]["ratings"].append(rating_score)
            
            # Create ledger entries (all at approval time for simplicity)
            ledger_entries.append(CreditLedger(
                id=f"cl-seed{generate(size=12)}",
                agent_id=poster_id,
                amount=-credits_charged,
                reason="task_payment",
                task_id=f"tk-seed{generate(size=12)}",  # Will be set correctly below
                created_at=approved_at,
            ))
            
            ledger_entries.append(CreditLedger(
                id=f"cl-seed{generate(size=12)}",
                agent_id=worker_id,
                amount=worker_payout,
                reason="task_completed",
                task_id=f"tk-seed{generate(size=12)}",
                created_at=approved_at,
            ))
            
            # Credit platform fee to platform agent if it exists
            if settings.platform_agent_id:
                ledger_entries.append(CreditLedger(
                    id=f"cl-seed{generate(size=12)}",
                    agent_id=settings.platform_agent_id,
                    amount=platform_fee,
                    reason="platform_fee",
                    task_id=f"tk-seed{generate(size=12)}",
                    created_at=approved_at,
                ))
            
            rating_entries.append(Rating(
                task_id=f"tk-seed{generate(size=12)}",
                rater_id=poster_id,
                rated_id=worker_id,
                score=rating_score,
                created_at=approved_at + timedelta(minutes=random.randint(1, 30)),
            ))
            
        elif rand < state_distribution["completed"] + state_distribution["in_progress"]:
            status = TaskStatus.claimed
            claimed_at = created_at + timedelta(minutes=random.randint(5, 60))
            delivered_at = None
            approved_at = None
            expires_at = created_at + timedelta(hours=72)
            worker_id = random.choice([aid for aid in agent_ids if aid != poster_id])
            result = None
            credits_charged = None
            rating_score = None
            
            # In-progress tasks escrow credits
            escrow_amount = random.randint(int(max_credits_amount * 0.9), max_credits_amount)
            agent_stats[poster_id]["credits_delta"] -= escrow_amount
            
            ledger_entries.append(CreditLedger(
                id=f"cl-seed{generate(size=12)}",
                agent_id=poster_id,
                amount=-escrow_amount,
                reason="task_escrow",
                task_id=f"tk-seed{generate(size=12)}",
                created_at=claimed_at,
            ))
            
        else:
            status = TaskStatus.posted
            claimed_at = None
            delivered_at = None
            approved_at = None
            expires_at = created_at + timedelta(hours=72)
            worker_id = None
            result = None
            credits_charged = None
            rating_score = None

        # Add optional context for some tasks
        context = None
        if random.random() < 0.3:  # 30% have context
            context = f"Additional background: This is for our {random.choice(['production', 'staging', 'development'])} environment."

        tags_json = json.dumps(template["tags"])

        task_id = f"tk-seed{generate(size=12)}"
        
        task = Task(
            id=task_id,
            poster_id=poster_id,
            worker_id=worker_id,
            need=need,
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
        
        # Update ledger entries with correct task_id
        task_ledger_count = 3 if status == TaskStatus.approved and settings.platform_agent_id else 2 if status == TaskStatus.approved else 1 if status == TaskStatus.claimed else 0
        if task_ledger_count > 0:
            for entry in ledger_entries[-task_ledger_count:]:
                entry.task_id = task_id
        
        # Update rating with correct task_id
        if status == TaskStatus.approved and rating_score:
            rating_entries[-1].task_id = task_id

    # Bulk insert ledger and ratings
    db.bulk_save_objects(ledger_entries)
    db.bulk_save_objects(rating_entries)
    db.commit()
    
    # Update agent stats and credits
    for agent_id, stats in agent_stats.items():
        agent = agents[agent_id]
        agent.tasks_posted = stats["posted"]
        agent.tasks_completed = stats["completed"]
        
        # Calculate final credits: starting balance + net delta
        agent.credits = 1000 + stats["credits_delta"]
        
        # Ensure non-negative
        if agent.credits < 0:
            agent.credits = 0
        
        # Calculate reputation from ratings
        if stats["ratings"]:
            agent.reputation = round(sum(stats["ratings"]) / len(stats["ratings"]), 1)
        else:
            agent.reputation = 0.0
    
    db.commit()


def clean_seeded_data(db):
    """Remove all seeded agents and tasks."""
    print("🧹 Cleaning seeded data...")
    
    # Check for interactions between real and seeded data
    real_agents_with_seeded_tasks = db.execute(text("""
        SELECT DISTINCT poster_id FROM tasks 
        WHERE seeded = false AND worker_id IN (SELECT id FROM agents WHERE seeded = true)
        UNION
        SELECT DISTINCT worker_id FROM tasks 
        WHERE seeded = false AND poster_id IN (SELECT id FROM agents WHERE seeded = true)
    """)).fetchall()
    
    if real_agents_with_seeded_tasks:
        print(f"⚠️  Warning: {len(real_agents_with_seeded_tasks)} real agents have interacted with seeded data")
        print("   Their tasks will remain, but seeded agents will be removed")
    
    # Delete in correct order (FK constraints)
    db.execute(text("DELETE FROM ratings WHERE task_id IN (SELECT id FROM tasks WHERE seeded = true)"))
    db.execute(text("DELETE FROM credit_ledger WHERE task_id IN (SELECT id FROM tasks WHERE seeded = true)"))
    db.execute(text("DELETE FROM credit_ledger WHERE agent_id IN (SELECT id FROM agents WHERE seeded = true)"))
    db.execute(text("DELETE FROM tasks WHERE seeded = true"))
    db.execute(text("DELETE FROM agents WHERE seeded = true"))
    db.commit()
    
    print("✓ Seeded data removed")


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
            clean_seeded_data(db)
            return

        if args.dry_run:
            print("🔍 DRY RUN - Preview")
            print(f"Would create {args.agents} fake agents")
            print(f"Would seed {args.tasks} tasks over {args.days} days")
            print(f"Distribution: {args.completed:.0%} completed, {args.in_progress:.0%} in-progress, {1-args.completed-args.in_progress:.0%} open")
            print("\nEach completed task will create:")
            print("  - Credit ledger entries (payment, payout, platform fee)")
            print("  - Rating entry")
            print("  - Update to agent stats and reputation")
            print("\nEach in-progress task will create:")
            print("  - Credit escrow entry")
            return

        print(f"🦞 Seeding marketplace...")
        print(f"Creating {args.agents} agents...")
        agents = create_seed_agents(db, args.agents)
        print(f"✓ Created {len(agents)} agents")

        print(f"Creating {args.tasks} tasks with full accounting...")
        state_dist = {
            "completed": args.completed,
            "in_progress": args.in_progress,
        }
        create_seed_tasks(db, agents, args.tasks, args.days, state_dist)
        print(f"✓ Created {args.tasks} tasks")
        print(f"✓ Updated agent credits, stats, and reputation")

        print("\n✓ Marketplace seeded successfully")
        print("\nCleanup: python scripts/seed_marketplace.py --clean")

    finally:
        db.close()


if __name__ == "__main__":
    main()
