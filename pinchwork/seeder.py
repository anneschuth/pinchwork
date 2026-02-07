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
from collections import deque
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

# Track recently used templates to avoid duplicates (last 5 templates)
_recent_templates = deque(maxlen=5)


def get_seeder_status() -> dict:
    """Return seeder health status for /health endpoint."""
    status = _seeder_status.copy()
    # Always read live config value, not cached status
    status["enabled"] = settings.seed_marketplace_drip
    return status


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
# Expanded task templates - 80+ unique realistic tasks
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
        {
            "need": "Review React component performance optimizations",
            "credits_range": (20, 35),
            "tags": ["code-review", "frontend", "performance"],
            "result": "Memo usage good. Consider virtualizing the list (1000+ items).",
        },
        {
            "need": "Security audit of file upload handler",
            "credits_range": (25, 45),
            "tags": ["security", "code-review", "uploads"],
            "result": "Found MIME type bypass. Add magic number validation.",
        },
        {
            "need": "Review database migration scripts",
            "credits_range": (15, 30),
            "tags": ["code-review", "database", "migrations"],
            "result": "3 migrations reviewed. Add rollback logic for migration 005.",
        },
        {
            "need": "Code review: WebSocket connection handling",
            "credits_range": (18, 32),
            "tags": ["code-review", "websocket", "real-time"],
            "result": "Reconnection logic solid. Add exponential backoff.",
        },
        {
            "need": "Review Terraform infrastructure code",
            "credits_range": (22, 40),
            "tags": ["code-review", "devops", "terraform"],
            "result": "State management good. Lock S3 bucket for safety.",
        },
        {
            "need": "API rate limiting implementation review",
            "credits_range": (16, 28),
            "tags": ["code-review", "api", "rate-limiting"],
            "result": "Token bucket approach works. Add per-user tracking.",
        },
        {
            "need": "Review Kubernetes deployment manifests",
            "credits_range": (20, 38),
            "tags": ["code-review", "kubernetes", "devops"],
            "result": "Resource limits set. Add liveness probe for worker pods.",
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
            "result": "Published 620-word blog with code examples.",
        },
        {
            "need": "Create onboarding guide for new developers",
            "credits_range": (40, 70),
            "tags": ["writing", "documentation", "onboarding"],
            "result": "10-page guide covering setup, architecture, and workflows.",
        },
        {
            "need": "Write technical RFC for caching strategy",
            "credits_range": (30, 55),
            "tags": ["writing", "rfc", "architecture"],
            "result": "RFC draft complete. Proposes Redis + CDN two-tier approach.",
        },
        {
            "need": "Document incident postmortem for 2hr outage",
            "credits_range": (25, 45),
            "tags": ["writing", "postmortem", "incident"],
            "result": "Postmortem published. Root cause: DB connection pool exhaustion.",
        },
        {
            "need": "Create README for open source library",
            "credits_range": (18, 35),
            "tags": ["writing", "documentation", "opensource"],
            "result": "README with quickstart, API reference, and contribution guide.",
        },
        {
            "need": "Write changelog for v2.0 release",
            "credits_range": (12, 22),
            "tags": ["writing", "changelog", "release"],
            "result": "Changelog covers 47 changes across 3 categories.",
        },
        {
            "need": "Technical comparison: Postgres vs MySQL for our use case",
            "credits_range": (28, 50),
            "tags": ["writing", "research", "database"],
            "result": "Comparison complete. Recommend Postgres for JSON support.",
        },
        {
            "need": "Write runbook for production deployment",
            "credits_range": (35, 60),
            "tags": ["writing", "documentation", "devops"],
            "result": "Deployment runbook with rollback procedures and healthchecks.",
        },
        {
            "need": "Create API migration guide for v1 to v2",
            "credits_range": (30, 50),
            "tags": ["writing", "documentation", "api"],
            "result": "Migration guide with code examples for 12 breaking changes.",
        },
    ],
    "research": [
        {
            "need": "Research AI agent frameworks",
            "credits_range": (30, 60),
            "tags": ["research", "competitive-analysis", "ai"],
            "result": "Compared 12 frameworks. Recommend LangChain for Python teams.",
        },
        {
            "need": "Evaluate cloud providers for Kubernetes hosting",
            "credits_range": (35, 65),
            "tags": ["research", "cloud", "kubernetes"],
            "result": "Analyzed AWS EKS, GCP GKE, Azure AKS. Recommend GKE.",
        },
        {
            "need": "Research real-time sync solutions for mobile app",
            "credits_range": (28, 50),
            "tags": ["research", "mobile", "sync"],
            "result": "Compared 5 solutions. Recommend Replicache for offline-first.",
        },
        {
            "need": "Competitive analysis: top 5 SaaS competitors",
            "credits_range": (40, 70),
            "tags": ["research", "competitive-analysis", "saas"],
            "result": "Detailed feature matrix. We lack mobile app and SSO.",
        },
        {
            "need": "Research best practices for API versioning",
            "credits_range": (22, 40),
            "tags": ["research", "api", "versioning"],
            "result": "Recommend URL versioning with 2-year deprecation window.",
        },
        {
            "need": "Evaluate monitoring tools: Datadog vs New Relic",
            "credits_range": (30, 55),
            "tags": ["research", "monitoring", "tooling"],
            "result": "Both solid. Datadog better APM, New Relic cheaper for our scale.",
        },
        {
            "need": "Research GDPR compliance requirements for EU users",
            "credits_range": (45, 80),
            "tags": ["research", "legal", "gdpr"],
            "result": "12-point compliance checklist. Need data export API.",
        },
        {
            "need": "Investigate cause of 30% latency spike last week",
            "credits_range": (35, 60),
            "tags": ["research", "performance", "debugging"],
            "result": "Found N+1 query in new feature. Patch ready.",
        },
        {
            "need": "Research authentication providers: Auth0 vs Clerk",
            "credits_range": (25, 45),
            "tags": ["research", "auth", "saas"],
            "result": "Clerk better DX, Auth0 more enterprise features.",
        },
        {
            "need": "Study accessibility standards (WCAG 2.1 AA)",
            "credits_range": (30, 50),
            "tags": ["research", "accessibility", "standards"],
            "result": "Gap analysis complete. Need keyboard nav + screen reader fixes.",
        },
    ],
    "testing": [
        {
            "need": "Load test the API - 10K concurrent users, find breaking points",
            "credits_range": (30, 60),
            "tags": ["testing", "load-test", "performance"],
            "result": "Breaking point: 7,200 concurrent. DB pool exhaustion.",
        },
        {
            "need": "Write E2E tests for checkout flow",
            "credits_range": (35, 60),
            "tags": ["testing", "e2e", "playwright"],
            "result": "12 E2E tests covering happy path + 5 edge cases.",
        },
        {
            "need": "Security penetration test for API endpoints",
            "credits_range": (50, 90),
            "tags": ["testing", "security", "pentesting"],
            "result": "Found 2 medium-severity issues. SQL injection risk on search.",
        },
        {
            "need": "Create unit tests for payment processing module",
            "credits_range": (28, 50),
            "tags": ["testing", "unit-tests", "payments"],
            "result": "85% coverage achieved. 32 unit tests added.",
        },
        {
            "need": "Test mobile app on 10 device+OS combinations",
            "credits_range": (40, 70),
            "tags": ["testing", "mobile", "compatibility"],
            "result": "All devices tested. Layout bug on iPhone SE.",
        },
        {
            "need": "Accessibility testing with screen readers",
            "credits_range": (25, 45),
            "tags": ["testing", "accessibility", "a11y"],
            "result": "Found 8 issues. Main nav not keyboard accessible.",
        },
        {
            "need": "Chaos engineering: test failure scenarios",
            "credits_range": (45, 80),
            "tags": ["testing", "chaos-engineering", "reliability"],
            "result": "Tested 5 failure modes. DB failover takes 8s.",
        },
        {
            "need": "Regression test suite for API v2 changes",
            "credits_range": (30, 55),
            "tags": ["testing", "regression", "api"],
            "result": "147 regression tests pass. 3 minor deprecation warnings.",
        },
        {
            "need": "Performance test: optimize page load times",
            "credits_range": (35, 60),
            "tags": ["testing", "performance", "frontend"],
            "result": "Reduced LCP from 3.2s to 1.4s via code splitting.",
        },
        {
            "need": "Fuzz testing for file parser",
            "credits_range": (28, 50),
            "tags": ["testing", "fuzzing", "security"],
            "result": "1 crash found with malformed UTF-8. Patch applied.",
        },
    ],
    "devops": [
        {
            "need": "Set up CI/CD pipeline for monorepo",
            "credits_range": (40, 75),
            "tags": ["devops", "ci-cd", "github-actions"],
            "result": "Pipeline complete. Build + test + deploy in 8 minutes.",
        },
        {
            "need": "Configure Kubernetes autoscaling",
            "credits_range": (35, 60),
            "tags": ["devops", "kubernetes", "autoscaling"],
            "result": "HPA configured. Scales 2-10 pods based on CPU.",
        },
        {
            "need": "Migrate from Docker Compose to Kubernetes",
            "credits_range": (50, 90),
            "tags": ["devops", "kubernetes", "migration"],
            "result": "Migration complete. 6 services deployed to k8s cluster.",
        },
        {
            "need": "Set up monitoring with Prometheus + Grafana",
            "credits_range": (45, 80),
            "tags": ["devops", "monitoring", "observability"],
            "result": "Dashboards live. Alerting for CPU, memory, error rate.",
        },
        {
            "need": "Implement blue-green deployment strategy",
            "credits_range": (38, 65),
            "tags": ["devops", "deployment", "reliability"],
            "result": "Blue-green deploys working. Zero-downtime releases.",
        },
        {
            "need": "Configure backup automation for databases",
            "credits_range": (30, 55),
            "tags": ["devops", "backup", "database"],
            "result": "Daily backups to S3. 30-day retention. Tested restore.",
        },
        {
            "need": "Set up log aggregation with ELK stack",
            "credits_range": (42, 70),
            "tags": ["devops", "logging", "elk"],
            "result": "Centralized logging live. 7-day retention.",
        },
        {
            "need": "Create Terraform modules for infrastructure",
            "credits_range": (35, 60),
            "tags": ["devops", "terraform", "iac"],
            "result": "5 modules created. VPC, ECS, RDS, S3, CloudFront.",
        },
        {
            "need": "Optimize Docker image build times",
            "credits_range": (22, 40),
            "tags": ["devops", "docker", "optimization"],
            "result": "Build time reduced from 12min to 3min via multi-stage.",
        },
        {
            "need": "Set up secrets management with Vault",
            "credits_range": (40, 70),
            "tags": ["devops", "security", "secrets"],
            "result": "Vault integrated. All secrets rotated. Zero plain text.",
        },
    ],
    "design": [
        {
            "need": "Design dashboard UI for analytics platform",
            "credits_range": (50, 90),
            "tags": ["design", "ui", "dashboard"],
            "result": "Figma mockups complete. 8 screens + component library.",
        },
        {
            "need": "Create mobile app wireframes for iOS/Android",
            "credits_range": (40, 70),
            "tags": ["design", "mobile", "wireframes"],
            "result": "Wireframes for 12 key screens. User flow documented.",
        },
        {
            "need": "Redesign landing page for better conversion",
            "credits_range": (35, 65),
            "tags": ["design", "landing-page", "conversion"],
            "result": "New hero section + social proof. A/B test ready.",
        },
        {
            "need": "Design component library for design system",
            "credits_range": (55, 95),
            "tags": ["design", "design-system", "components"],
            "result": "32 components designed. Tokens for color, spacing, type.",
        },
        {
            "need": "Create user journey map for onboarding flow",
            "credits_range": (30, 50),
            "tags": ["design", "ux", "onboarding"],
            "result": "Journey map shows 3 drop-off points. Improvements proposed.",
        },
        {
            "need": "Design email templates for transactional emails",
            "credits_range": (25, 45),
            "tags": ["design", "email", "templates"],
            "result": "6 email templates. Mobile-responsive. Dark mode support.",
        },
        {
            "need": "UX research: conduct 10 user interviews",
            "credits_range": (60, 100),
            "tags": ["design", "ux-research", "interviews"],
            "result": "10 interviews complete. Key insight: search is too slow.",
        },
        {
            "need": "Design icon set for product features",
            "credits_range": (28, 50),
            "tags": ["design", "icons", "ui"],
            "result": "24 icons designed. SVG format. Light + dark variants.",
        },
        {
            "need": "Create accessibility color palette (WCAG AA)",
            "credits_range": (22, 40),
            "tags": ["design", "accessibility", "color"],
            "result": "Palette meets 4.5:1 contrast. 8 primary + 16 semantic colors.",
        },
        {
            "need": "Design data visualization for metrics dashboard",
            "credits_range": (35, 60),
            "tags": ["design", "data-viz", "dashboard"],
            "result": "Charts designed. Line, bar, pie, heatmap. Color-blind safe.",
        },
    ],
    "data": [
        {
            "need": "Analyze user churn: identify top 5 reasons",
            "credits_range": (45, 75),
            "tags": ["data", "analysis", "churn"],
            "result": "Churn analysis complete. #1 reason: slow onboarding (28%).",
        },
        {
            "need": "Build SQL dashboard for customer metrics",
            "credits_range": (35, 60),
            "tags": ["data", "sql", "dashboard"],
            "result": "Dashboard shows MRR, churn, LTV. Refreshes hourly.",
        },
        {
            "need": "Clean and normalize 500K customer records",
            "credits_range": (40, 70),
            "tags": ["data", "cleaning", "etl"],
            "result": "Data cleaning complete. 12% duplicates removed.",
        },
        {
            "need": "Create ML model for churn prediction",
            "credits_range": (60, 110),
            "tags": ["data", "ml", "prediction"],
            "result": "Random forest model. 82% accuracy. Top features identified.",
        },
        {
            "need": "Analyze A/B test results for new feature",
            "credits_range": (25, 45),
            "tags": ["data", "ab-test", "statistics"],
            "result": "Variant B wins. 18% lift in conversion (p<0.01).",
        },
        {
            "need": "Build ETL pipeline for data warehouse",
            "credits_range": (50, 90),
            "tags": ["data", "etl", "pipeline"],
            "result": "Airflow pipeline live. 5 sources → Snowflake. Daily refresh.",
        },
        {
            "need": "Exploratory data analysis on user behavior logs",
            "credits_range": (35, 60),
            "tags": ["data", "eda", "analysis"],
            "result": "EDA complete. Found usage spike at 2pm UTC daily.",
        },
        {
            "need": "Create cohort analysis for retention metrics",
            "credits_range": (30, 55),
            "tags": ["data", "cohort", "retention"],
            "result": "Cohort analysis shows 40% D30 retention for Jan cohort.",
        },
        {
            "need": "Optimize slow SQL queries in production",
            "credits_range": (28, 50),
            "tags": ["data", "sql", "performance"],
            "result": "3 queries optimized. Added indexes. 10x speedup.",
        },
        {
            "need": "Build automated reporting pipeline",
            "credits_range": (42, 70),
            "tags": ["data", "reporting", "automation"],
            "result": "Weekly reports auto-generated. Sent via email + Slack.",
        },
    ],
    "integration": [
        {
            "need": "Integrate Stripe payment processing",
            "credits_range": (40, 70),
            "tags": ["integration", "stripe", "payments"],
            "result": "Stripe integrated. Supports cards, ACH, subscriptions.",
        },
        {
            "need": "Build Slack bot for team notifications",
            "credits_range": (35, 60),
            "tags": ["integration", "slack", "bot"],
            "result": "Slack bot live. Posts alerts for deploys, errors, signups.",
        },
        {
            "need": "Integrate SendGrid for transactional emails",
            "credits_range": (25, 45),
            "tags": ["integration", "sendgrid", "email"],
            "result": "SendGrid integrated. Templates migrated. 99.2% delivery.",
        },
        {
            "need": "Connect app to Google Analytics 4",
            "credits_range": (22, 40),
            "tags": ["integration", "analytics", "ga4"],
            "result": "GA4 connected. Custom events for signup, purchase, churn.",
        },
        {
            "need": "Implement SSO with Okta",
            "credits_range": (45, 80),
            "tags": ["integration", "sso", "okta"],
            "result": "SAML SSO working. Tested with Okta + Azure AD.",
        },
        {
            "need": "Build webhook integration with Zapier",
            "credits_range": (30, 55),
            "tags": ["integration", "webhooks", "zapier"],
            "result": "Zapier integration published. 8 triggers, 4 actions.",
        },
        {
            "need": "Integrate Twilio for SMS notifications",
            "credits_range": (28, 50),
            "tags": ["integration", "twilio", "sms"],
            "result": "Twilio SMS working. 2FA + order confirmations.",
        },
        {
            "need": "Connect to Salesforce CRM via API",
            "credits_range": (50, 85),
            "tags": ["integration", "salesforce", "crm"],
            "result": "Salesforce sync live. Bidirectional contact sync.",
        },
        {
            "need": "Implement OAuth 2.0 login with GitHub",
            "credits_range": (32, 55),
            "tags": ["integration", "oauth", "github"],
            "result": "GitHub OAuth working. Profile import + team sync.",
        },
        {
            "need": "Build REST API wrapper for legacy SOAP service",
            "credits_range": (55, 95),
            "tags": ["integration", "api", "soap"],
            "result": "REST wrapper complete. 12 endpoints. OpenAPI spec.",
        },
    ],
    "bug-fixes": [
        {
            "need": "Fix memory leak in background worker",
            "credits_range": (35, 60),
            "tags": ["bug-fix", "memory-leak", "performance"],
            "result": "Leak fixed. Event listeners properly cleaned up.",
        },
        {
            "need": "Debug race condition in payment flow",
            "credits_range": (45, 75),
            "tags": ["bug-fix", "concurrency", "payments"],
            "result": "Race condition fixed. Added DB-level locking.",
        },
        {
            "need": "Fix broken image uploads on mobile Safari",
            "credits_range": (28, 50),
            "tags": ["bug-fix", "mobile", "safari"],
            "result": "HEIC format support added. Works on all iOS versions.",
        },
        {
            "need": "Resolve CORS errors for cross-domain API calls",
            "credits_range": (20, 35),
            "tags": ["bug-fix", "cors", "api"],
            "result": "CORS headers fixed. Supports credentials + preflight.",
        },
        {
            "need": "Fix timezone bug in scheduled reports",
            "credits_range": (25, 45),
            "tags": ["bug-fix", "timezone", "datetime"],
            "result": "Now respects user timezone. Tested across 12 zones.",
        },
        {
            "need": "Debug intermittent 500 errors on checkout",
            "credits_range": (40, 70),
            "tags": ["bug-fix", "debugging", "checkout"],
            "result": "Found timeout in payment gateway. Added retry logic.",
        },
        {
            "need": "Fix broken pagination on search results",
            "credits_range": (18, 32),
            "tags": ["bug-fix", "pagination", "search"],
            "result": "Pagination working. Handles 10K+ results.",
        },
        {
            "need": "Resolve database deadlock issues",
            "credits_range": (35, 60),
            "tags": ["bug-fix", "database", "deadlock"],
            "result": "Deadlock fixed. Reordered lock acquisition.",
        },
        {
            "need": "Fix email delivery failures for certain domains",
            "credits_range": (30, 50),
            "tags": ["bug-fix", "email", "deliverability"],
            "result": "SPF + DKIM records fixed. 99% delivery now.",
        },
        {
            "need": "Debug WebSocket disconnection issues",
            "credits_range": (32, 55),
            "tags": ["bug-fix", "websocket", "real-time"],
            "result": "Keepalive ping added. Reconnect on network change.",
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

    # Avoid duplicate templates by filtering out recently used ones
    available_templates = [t for t in ALL_TEMPLATES if t["need"] not in _recent_templates]
    # Fallback to full list if all templates were recently used
    if not available_templates:
        available_templates = ALL_TEMPLATES

    template = random.choice(available_templates)
    _recent_templates.append(template["need"])  # Track this template

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
                platform_update = db.execute(
                    text("UPDATE agents SET credits = credits + :amount WHERE id = :id"),
                    {"amount": platform_fee, "id": settings.platform_agent_id},
                )
                if platform_update.rowcount == 0:
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

                # Calculate tasks to create based on time of day (CET aligned)
                hour = datetime.utcnow().hour

                if 7 <= hour < 21:  # 8-22 CET (extended business day)
                    lambda_rate = settings.seed_drip_rate_business
                elif 21 <= hour < 23:  # 22-24 CET (short evening)
                    lambda_rate = settings.seed_drip_rate_evening
                else:  # 0-8 CET (night)
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
