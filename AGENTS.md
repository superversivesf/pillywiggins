# Pillywiggins — Agent Instructions

## Quickstart

```bash
# 1. Clone
git clone <repo-url> && cd pillywiggins

# 2. Install (requires pipx — apt install pipx or brew install pipx)
pipx install -e .

# 3. Configure agents (interactive wizard)
pillywiggins onboard

# 4. Deploy
docker compose up -d --build
```

Config files (`agents.yaml`, `docker-compose.yaml`, `.env`) are copied from `.example` templates on first run of `pillywiggins onboard`. They are gitignored — your local config is never committed.

## Workflow Rules

### Small-Step Workflow (MANDATORY)

All agents **MUST** follow a strict small-step workflow:

1. **Do ONE small step at a time** — Make a single, focused change.
2. **Verify it works** — Run tests, check for errors, confirm the change is correct.
3. **ONLY THEN move to the next step** — Never chain multiple unverified changes together.

This is essential for stability and must never be forgotten. Violating this rule leads to cascading failures, lost memory, and broken deployments.

## Project State

**Post-implementation.** The onboard wizard (`pillywiggins onboard`) is the entry point for adding agents. Install via `pipx install -e .`. Config files (`agents.yaml`, `docker-compose.yaml`, `.env`) are generated from `.example` templates on first run and are gitignored.

## Which Architecture Is Canonical

Two architecture docs exist with different approaches:

- **`docs/pillywiggins-overview-v2.md`** — **Canonical.** Docker Compose deployment, single Python process per agent, shared `skills/` volume, APScheduler + Redis for scheduling. This is the implementation target.
- **`docs/outdated/pillywiggins-design-v2.md`** — Dapr/K8s alternative (moved to `docs/outdated/`). Useful for actor-model concepts and as a future migration path, but not what we're building now.

When docs conflict, trust **overview-v2**.

## Key Architecture Decisions

These are non-obvious and took research to arrive at:

- **One Python process per agent, not Dapr actors** — Each agent (Discord, Slack, etc.) is a `PillywigginAgent` class with `asyncio.Lock` for turn-based concurrency. Runs as a Docker Compose service. No Dapr sidecars, no K8s pods. See overview-v2 §2.
- **PydanticAI as the agent brain** — `PydanticAI.Agent` with injected `AgentDeps`, system prompt from personality YAML. Tools are registered from the shared `SkillRegistry`. See overview-v2 §2.
- **Memory isolation is enforced by PostgreSQL Row-Level Security, not application code** — Every agent connection sets `app.agent_id`; RLS policies block cross-agent reads at the database level. This is the core security boundary. See overview-v2 §6 and §9.
- **Skills are Python files in a shared Docker volume, not MCP servers** — `skills/` directory mounted into all agent containers. `SkillRegistry` loads and watches skill files. Collaborative draft → test → review → deploy flow. See overview-v2 §3.
- **Scheduling via APScheduler + Redis job store** — Per-agent `AsyncIOScheduler` with `RedisJobStore`. Schedules loaded from personality YAML. `misfire_grace_time=300` for restart tolerance. See overview-v2 §4.
- **Inter-agent communication via NATS directly** — `nats-py` connects to NATS JetStream for council broadcasts (`council.broadcast`) and direct messages (`council.direct.{agent_id}`). No Dapr pub/sub layer. See overview-v2 §7.
- **Model: Qwen 3.5 8B on RTX 5060 Ti (16GB VRAM)** — This is the binding hardware constraint. `OLLAMA_NUM_PARALLEL=2`. The 32B model requires aggressive quantization or a second GPU. See overview-v2 §13.
- **Deployment: `docker compose up`** — All services (PostgreSQL, Redis, NATS, Ollama, agents) defined in a single `docker-compose.yaml`. No k3s, Helm, or ConfigMaps.
- **Secrets: `.env` file (not committed to Git)** — Channel tokens, DB credentials, etc. in `.env`. Not SOPS, not K8s Secrets.
- **Config files are gitignored, generated from `.example` templates** — `agents.yaml`, `docker-compose.yaml`, and `.env` are created from their `.example` counterparts by the onboard wizard on first run. Edit the `.example` files for defaults; edit the real files for deployment.

## Technology Stack

| Layer | Choice | Not This |
|-------|--------|----------|
| Agent brain | PydanticAI v1 | LangGraph, CrewAI, DurableAgent |
| Agent runtime | PillywigginAgent with asyncio.Lock | Dapr virtual actors, Orleans |
| LLM inference | Ollama (GPU) | vLLM (production upgrade path) |
| Model | Qwen 3.5 8B | Larger models won't fit |
| Private memory | PostgreSQL + pgvector + RLS | Flat files, shared DB |
| Council memory | PostgreSQL + pgvector (shared read) | — |
| Conversation cache | Redis (direct) | — |
| Message bus | NATS JetStream via nats-py | Kafka (overkill), Dapr pub/sub |
| Skills/tools | Python files in shared Docker volume | MCP servers |
| Scheduling | APScheduler + Redis job store | Dapr Reminders, K8s CronJobs |
| Channel libs | discord.py, slack_bolt, python-telegram-bot, matrix-nio, aiosmtplib+imap-tools | — |
| Deployment | Docker Compose | k3s + Helm (that's design-v2) |
| Secrets | .env file | SOPS, Vault |
| Sandboxing | Restricted subprocess with timeouts | gVisor, Docker-in-Docker |

## Project Structure Target

Defined in overview-v2 §11. Source lives under `src/pillywiggins/`. Key entrypoints:

- `src/pillywiggins/__main__.py` — CLI entrypoint: `pillywiggins --channel discord` (also works as `python -m pillywiggins`)
- `src/pillywiggins/agents/base.py` — `PillywigginAgent` base class with asyncio.Lock
- `src/pillywiggins/agents/brain.py` — PydanticAI agent definition + built-in tools
- `src/pillywiggins/agents/deps.py` — `AgentDeps` dataclass injected into every tool call
- `src/pillywiggins/agents/personality.py` — YAML personality loader
- `src/pillywiggins/adapters/` — One adapter per channel, all producing `UnifiedMessage`
- `src/pillywiggins/memory/private.py` — pgvector + RLS operations
- `src/pillywiggins/memory/council.py` — Shared memory with write validation
- `src/pillywiggins/skills/registry.py` — SkillRegistry (load, register, watch)
- `src/pillywiggins/skills/builder.py` — Skill building/testing flow
- `src/pillywiggins/skills/sandbox.py` — Sandboxed subprocess execution
- `src/pillywiggins/messaging/nats_bus.py` — NATS pub/sub wrapper
- `src/pillywiggins/scheduling/scheduler.py` — APScheduler + Redis per-agent
- `src/pillywiggins/onboard.py` — Interactive onboarding wizard (`pillywiggins onboard`)
- `src/pillywiggins/adapters/models.py` — Model list polling via OpenAI/Ollama APIs
- `personalities/` — Personality YAML files (31 available)
- `skills/` — Shared skill Python files + registry.json
- `agents.yaml.example` — Template for agent config (gitignored when copied to `agents.yaml`)
- `docker-compose.yaml.example` — Template for Docker Compose (gitignored when copied)
- `env.example` — Template for environment variables

## Docs Guide

### Active (trust these)

| File | What It Covers |
|------|---------------|
| `pillywiggins-overview-v2.md` | **Canonical architecture**, code structure, skills system, scheduling, roadmap, risk register |
| `IMPLEMENTATION-PLAN.md` | Staged implementation plan with checklists and verification gates |

### Outdated (in `docs/outdated/`)

These recommend Dapr/K8s — the architecture we chose not to build. Kept for reference only.

| File | Why Outdated |
|------|-------------|
| `pillywiggins-design-v2.md` | Dapr/K8s architecture — contradicts chosen Docker Compose approach |
| `WhatIsDapr.md` | Entirely about Dapr sidecars/actors |
| `Pillywiggins-InitialResearch.md` | Concludes "Python + Dapr" is the answer |
| `Pillywiggins-Roadmap.md` | Older Dapr+K8s design, superseded |
| `Pillywiggins-IdeaOverview.md` | Market research recommending Dapr/K8s stack |
## Gotchas

- **Design-v2 uses k3s+Helm; overview-v2 uses Docker Compose.** Don't mix the two. We're building overview-v2.
- **Entry point is `__main__.py`** — run as `pillywiggins onboard` or `pillywiggins --channel discord`. The `python -m pillywiggins` form also works.
- **vLLM vs Ollama** — Design-v2 mentions vLLM for production. We start with Ollama; vLLM is a future upgrade path if throughput becomes a bottleneck.
- **Personality changes require `docker compose restart`** — YAML files are mounted read-only. Edit the YAML, then restart the agent service. No ConfigMap hot-reload.
- **Docker Compose healthchecks are not K8s probes** — `depends_on: { condition: service_healthy }` uses the Compose healthcheck. Don't rely on K8s-style liveness probes.
- **`.env` must never be committed** — `.gitignore` must include `.env`. Use `env.example` as the template.
- **`agents.yaml` and `docker-compose.yaml` are gitignored** — They're generated from `.example` templates by `pillywiggins onboard`. Edit `.example` files for defaults; edit real files for deployment.
- **Skill sandbox has limits** — Restricted subprocess with timeouts is not as strong as gVisor. Don't run untrusted code without user approval. See overview-v2 §9.
- **Never skip the small-step workflow** — Chaining unverified changes causes cascading failures and silent memory loss. One step, verify, then next.
