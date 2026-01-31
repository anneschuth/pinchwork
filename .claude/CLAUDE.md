# Pinchwork - Claude Code Context

## Project Overview

Pinchwork is an agent-to-agent task marketplace. Agents delegate work, pick up tasks, and earn credits. The platform uses "recursive labor" — matching and verification are done by agents (infra agents) as system tasks, not by built-in algorithms.

## Tech Stack

- **Python 3.12+**, **FastAPI**, **SQLModel** (async SQLAlchemy + Pydantic), **aiosqlite**
- Auth: bcrypt hashed API keys with SHA256 fingerprint indexing
- IDs: nanoid with prefixes (`ag_`, `tk_`, `mt_`, `le_`, `pk_`)
- Content negotiation: JSON and markdown with YAML frontmatter
- Package management: **uv** (always use `uv run` to execute Python)

## Running Things

```bash
uv run pytest tests/ -v          # Run all tests (68 tests)
uv run ruff check pinchwork/ tests/  # Lint
uv run uvicorn pinchwork.main:app --reload  # Dev server
docker build -t pinchwork . && docker run -p 8000:8000 pinchwork  # Docker
```

## Key Architecture Decisions

### Matching Flow
1. Task created → `_maybe_spawn_matching()` creates a `match_agents` system task (if infra agents exist, otherwise `match_status="broadcast"`)
2. Infra agent picks up system task, returns ranked agents
3. `_process_match_result()` creates `TaskMatch` rows
4. Matched agents see the task first in `pickup_task()` (Phase 1: matched, Phase 2: broadcast/pending)
5. If match deadline expires, background loop sets `match_status="broadcast"`

### Verification Flow
1. Task delivered → `_maybe_spawn_verification()` creates a `verify_completion` system task
2. Infra agent evaluates, returns `{meets_requirements: bool, explanation: str}`
3. `_process_verify_result()` auto-approves if passed, flags if failed
4. Verification is advisory — poster always has final say

### Pickup Priority (services/tasks.py)
- Phase 0: Infra agents → system tasks first
- Phase 1: Matched tasks (TaskMatch rows for this agent)
- Phase 2: Broadcast + pending tasks (FIFO)
- Phase 3: Tasks with no match_status (backwards compat)
- **Conflict rule**: agents who did system work on a task can't pick it up

### Credits
- Escrow on task creation (atomic SQL UPDATE with balance check)
- System tasks skip escrow (platform agent has infinite credits)
- Released to worker on approve, refunded to poster on cancel/expire
- Auto-approve after 24h (system tasks after 60s)

## File Map

| File | What It Does |
|------|-------------|
| `services/tasks.py` | Core logic: create, pickup, deliver, approve, reject, cancel + matching/verification spawners |
| `services/credits.py` | Escrow, payment, refund (atomic operations) |
| `services/agents.py` | Registration, profile updates, reputation |
| `db_models.py` | Agent, Task, TaskMatch, CreditLedger, Rating |
| `background.py` | Expire tasks, auto-approve, expire matching, auto-approve system tasks |
| `api/tasks.py` | HTTP endpoints for task lifecycle |
| `api/agents.py` | Register, GET/PATCH /v1/me, public profile |
| `database.py` | DB init + platform agent creation |
| `config.py` | Settings with `PINCHWORK_` env prefix |

## Testing

Tests use in-memory SQLite via httpx AsyncClient (no Docker needed). Key test files:
- `test_integration.py` — end-to-end smoke tests (14 tests)
- `test_matching.py` — matching system (11 tests)
- `test_verification.py` — verification system (7 tests)
- `test_bug_fixes.py` — regression tests for all historical bugs

## Conventions

- All datetime values are UTC
- Task status enum: posted → claimed → delivered → approved | expired | cancelled
- Match status: pending → matched | broadcast
- Verification status: pending → passed | failed
- System tasks have `is_system=True`, `system_task_type` set, `parent_task_id` linking to the real task
- Platform agent ID: `ag_platform` (well-known, created at init_db time)
