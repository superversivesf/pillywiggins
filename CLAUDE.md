# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pillywiggins is a multi-agent AI system where each agent runs as an independent Docker container with its own personality, private memory, and cron schedule. Agents communicate through NATS JetStream, store memories in PostgreSQL with pgvector, and cache conversations in Redis. The LLM backend is pluggable (Ollama by default, any OpenAI-compatible API).

## Common Commands

```bash
# Install (requires pipx)
pipx install -e .

# Run the interactive setup wizard
pillywiggins onboard

# Deploy all services
docker compose up -d --build

# Run tests
python3 -m pytest tests/ -q                          # all tests
python3 -m pytest tests/test_brain.py -q             # single file
python3 -m pytest tests/ -q -m "not integration"     # unit tests only (default marker)
python3 -m pytest tests/ -q -m integration           # integration tests (require Docker)
python3 -m pytest tests/ -q -m smoke                 # infrastructure smoke tests

# Lint
ruff check src/ tests/

# View logs
docker compose logs -f puck                          # single agent
docker compose logs -f --tail=100                    # all services
```

## Architecture

### Core data flow

Every message follows: **Adapter** (channel-specific) → `normalize()` → `UnifiedMessage` → **PillywigginAgent.process_message()** → **brain** (pydantic-ai Agent) → LLM → tool calls → response → adapter sends back.

The brain is built in `agents/brain.py` via `create_brain()` which registers system prompt, built-in tools (memory, skills, scheduling, inter-agent messaging), and dynamically loaded skill tools.

### Key abstractions

- **PillywigginAgent** (`agents/base.py`): Central orchestrator. Holds personality, infrastructure refs, brain, message history, rate limiting (10 LLM calls/60s). Routes NATS messages, manages skill hot-reload via `_refresh_brain_tools()`.
- **BaseAdapter** (`adapters/base.py`): ABC with `connect()`, `listen()`, `send()`, `normalize()`. Implementations: Telegram, Discord, Slack, Matrix, Email. Each adds channel-specific command handlers and access control.
- **AgentDeps** (`agents/deps.py`): Dependency injection container passed to every pydantic-ai tool via `RunContext[AgentDeps]`.
- **Personality** (`agents/personality.py`): Loaded from YAML. Supports old schema (description/system_prompt/traits) and new schema (archetype/tone/style).

### Three memory spaces

1. **Private memory** (`memory/private.py`): Per-agent, PostgreSQL + pgvector with RLS. Agent can only access its own rows (enforced by `app.agent_id` GUC). Cosine similarity search via `<=>` operator.
2. **Council memory** (`memory/council.py`): Shared across all agents, PostgreSQL + pgvector. Rate-limited (10 writes/hr/agent), deduplicated (cosine > 0.95), max 2000 chars, whitelisted tags.
3. **Conversation cache** (`memory/cache.py`): Redis-backed, 30-min TTL, per-conversation message history for fast context retrieval.

### Inter-agent communication (NATS)

- **Broadcast**: `council.broadcast` — all agents subscribe (insights, heartbeats, skill_published)
- **Direct**: `council.direct.{target_agent_id}` — point-to-point
- `NatsBus` (`messaging/nats_bus.py`): JetStream with durable consumers, message dedup, auto-reconnect health monitor.

### Skills system

Skills are Python files in `skills/` with a `SKILL_META` dict and `async def run()` coroutine. Lifecycle: draft → test (sandbox subprocess) → review → publish (write .py + update registry.json + NATS broadcast). Other agents hot-reload via file watcher + `_refresh_brain_tools()`.

Sandbox (`skills/sandbox.py`): Isolated subprocess with stripped env vars, permission flags (`SKILL_NETWORK`, `SKILL_SUBPROCESS`, `SKILL_FILE_WRITE`), 30s timeout.

### Scheduling

`AgentScheduler` (`scheduling/scheduler.py`): APScheduler with Redis job store. Built-in actions: heartbeat, memory_review, skill_reload. Dynamic: `send_message` runs the brain to generate proactive output. Schedule sources: personality YAML `schedules` key + persisted JSON at `/app/skills/{agent_id}_schedules.json`.

### Config

`Settings` (`config.py`): pydantic-settings BaseSettings loading from env vars + `.env`. Multi-agent Docker: each container sets `--agent-id`, `agents_config.py` loads per-agent env from `agents.yaml` and injects into `os.environ` before Settings re-instantiation. `resolve_embedding_config()` probes Ollama for embedding models, falls back to HuggingFace sentence-transformers.

### Database schema

`scripts/init-db.sql`: Creates `private_memory` (RLS-isolated), `council_memory` (shared), `conversation_cache` (RLS-isolated) tables with pgvector `vector(768)` columns, HNSW indexes, and per-agent DB roles for RLS.

## Testing conventions

- **Unit tests are the default** — no marker needed (`pytest_collection_modifyitems` auto-applies `unit`).
- **Integration tests**: module-level `pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker_available")]`. Spin up ephemeral Docker containers on random ports.
- **Async**: `asyncio_mode = "auto"` — `async def test_` works without `@pytest.mark.asyncio`.
- **Mocking**: `MagicMock(spec=RealClass)` + `AsyncMock` for async methods. Patch module-level imports (e.g., `patch("pillywiggins.memory.private.asyncpg.create_pool")`), not the original library.
- **Brain tool tests**: Use `_make_ctx()` helper returning `MagicMock(spec=RunContext)` with `AgentDeps`. Test three paths: unavailable dependency, invalid input, success.
- **Memory tests**: Use `_make_pool_mock()` for mocked asyncpg pools. Always `await memory.close()` after assertions.
- pytest timeout is 60 seconds.

## Deployment

- `docker-compose.yaml` is gitignored (generated by `pillywiggins onboard` from `.example` template).
- `.env`, `agents.yaml` are also gitignored (contain secrets + per-machine config).
- Skills directory is a bind mount (`./skills:/app/skills`), not a Docker volume — host edits propagate immediately.
- Ollama runs outside Docker Compose; agents connect via `OLLAMA_BASE_URL` (default `http://host.docker.internal:11434/v1`).
- Infrastructure ports are bound to `127.0.0.1` only.

## Development workflow

The "small-step workflow" is mandatory: make one change, verify, then proceed. Chaining unverified changes causes cascading failures in a multi-service system.

When adding a new adapter: implement `BaseAdapter` ABC, add a personality YAML in `personalities/`, add the adapter module in `adapters/`, and update `onboard.py` with the channel option. Register it in `__main__`'s `_load_adapter_class()`.