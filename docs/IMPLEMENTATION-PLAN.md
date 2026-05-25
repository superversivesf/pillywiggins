# Pillywiggins: Implementation Plan & Checklist

**Version 2.0 — April 2026**  
**Last verified: May 2026** — Telegram default, adapters complete, hardening partial (prompt injection, memory consolidation done)  
**Canonical architecture: `pillywiggins-overview-v2.md` (Docker Compose)**

---

## Phase Overview

| Phase | Goal | Effort | Depends On | Status |
|-------|------|--------|------------|--------|
| 1 — One Agent Talks | Docker Compose infra + single Telegram agent talking to Ollama | 30–40h | Nothing | **Done** (Phase 1 of 5-phase remediation) |
| 2 — Memory Works | Private memory with RLS, personality from YAML, council memory schema | 40–60h | Phase 1 | **Done** (Phase 2 of 5-phase remediation) |
| 3 — Skills System | Agents build, test, and deploy skills collaboratively | 50–70h | Phase 2 | **Done** (Phase 3 of 5-phase remediation) |
| 4 — Second Agent + Communication | Two agents with isolated state, shared skills, council memory, per-agent cron | 30–40h | Phase 3 | **Done** (Phase 4 of 5-phase remediation) |
| 5 — Full Fleet | All five channels live with complete feature set | 40–60h | Phase 4 | **Partial** (adapters + personalities done; multi-agent concurrency pending) |
| 6 — Hardening | Rate limiting, logging, healthchecks, backups — 24/7 reliable | 40–50h | Phase 5 | **Partial** (rate limiting, structured logging, healthchecks, restart policies, backup script, security hardening, prompt injection detection, memory consolidation, output sanitization, MCP integration, multi-provider support, Claude skill importer, deployment fixes done; token bucket refactor, ops runbook, unattended ops pending) |

---

## Phase 1: One Agent Talks

**Status**: Core subsystems complete (Phase 1 of 5-phase remediation done by `cell-2r4g0k-moch5faq7q2`).

**Goal**: Docker Compose running PostgreSQL, Redis, and NATS. An agent receives a message and responds using Ollama via PydanticAI. Conversation persists across container restarts.

> **Note — Ollama is intentionally excluded from `docker-compose.yaml`.**
> Ollama is expected to run externally (e.g. on the host machine, in a separate GPU-optimized container you manage yourself, or via a remote/cloud endpoint). Agents connect to it using `OLLAMA_BASE_URL` set in `.env` (default: `http://host.docker.internal:11434` on Docker Desktop). This separation keeps GPU drivers, model pulls, and VRAM management outside the project's Compose lifecycle.

**Prerequisites**: A machine with NVIDIA GPU (16 GB+ VRAM), Docker + Docker Compose installed, NVIDIA Container Toolkit.

### Tasks

#### 1.1 Project scaffolding

- [x] Create repository with the structure from overview-v2 §11:
  ```
  pillywiggins/
  ├── docker-compose.yaml
  ├── Dockerfile
  ├── pyproject.toml
  ├── env.example
  ├── .gitignore
  ├── personalities/
  │   └── puck.yaml (historically discord.yaml)
  ├── skills/
  │   └── registry.json
  ├── src/
  │   └── pillywiggins/
  │       ├── __init__.py
  │       ├── __main__.py
  │       ├── config.py
  │       ├── agents/
  │       │   ├── __init__.py
  │       │   ├── base.py
  │       │   ├── brain.py
  │       │   ├── deps.py
  │       │   └── personality.py
  │       ├── adapters/
  │       │   ├── __init__.py
  │       │   ├── base.py
  │       │   ├── discord_adapter.py
  │       │   ├── slack_adapter.py
  │       │   ├── telegram_adapter.py
  │       │   ├── matrix_adapter.py
  │       │   └── email_adapter.py
  │       ├── memory/
  │       │   ├── __init__.py
  │       │   ├── private.py
  │       │   ├── council.py
  │       │   ├── cache.py
  │       │   └── embeddings.py
  │       ├── messaging/
  │       │   ├── __init__.py
  │       │   └── unified.py
  │       ├── scheduling/
  │       │   ├── __init__.py
  │       │   └── scheduler.py
  │       └── health.py
  ├── scripts/
  │   ├── setup-db.sh
  │   └── pull-models.sh
  ├── tests/
  │   ├── conftest.py
  │   ├── test_brain.py
  │   └── test_adapters.py
  └── docs/
  ```
- [x] Create `pyproject.toml` with dependencies: `pydantic-ai`, `asyncpg`, `redis`, `nats-py`, `python-telegram-bot`, `slack-bolt`, `matrix-nio`, `aiosmtplib`, `apscheduler`, `pydantic-settings`, `pydantic`
- [x] Create `Dockerfile` (multi-stage: build with uv, runtime with Python 3.12 slim)
- [x] Create `env.example` with all required environment variables (including all 9 providers: Ollama, OpenAI, Anthropic, Groq, DeepSeek, Mistral, OpenRouter, Google Gemini, xAI — May 2026):
  ```env
  # Database
  DATABASE_URL=postgresql://pillywiggins:password@postgres:5432/pillywiggins
  PG_PASSWORD=changeme

  # Redis
  REDIS_URL=redis://redis:6379/0

  # NATS
  NATS_URL=nats://nats:4222

  # Ollama (runs externally — not in this docker-compose)
  OLLAMA_BASE_URL=http://host.docker.internal:11434
  MODEL_NAME=qwen3.5:8b
  EMBEDDING_MODEL=nomic-embed-text

  # Channel tokens
  TELEGRAM_BOT_TOKEN=your_telegram_bot_token

  # Agent config
  AGENT_ID=puck
  CHANNEL=telegram
  PERSONALITY_FILE=/config/puck.yaml
  ```
- [x] Create `.gitignore` including `.env`
- [x] Initialize `skills/registry.json` as `{ "skills": [] }`

#### 1.2 Docker Compose infrastructure

- [x] Create `docker-compose.yaml` with all infrastructure services:
  > **Note:** Ollama is intentionally **excluded** from `docker-compose.yaml`. It runs externally (host machine, separate GPU container, or cloud endpoint) and is connected via `OLLAMA_BASE_URL` in `.env`.

  ```yaml
  services:
    postgres:
      image: pgvector/pgvector:pg16
      volumes: [pgdata:/var/lib/postgresql/data]
      environment:
        POSTGRES_DB: pillywiggins
        POSTGRES_PASSWORD: ${PG_PASSWORD}
      healthcheck:
        test: ["CMD-SHELL", "pg_isready -U postgres"]
      ports:
        - 127.0.0.1:5432:5432

    redis:
      image: redis:7-alpine
      volumes: [redisdata:/data]
      command: redis-server --appendonly yes
      ports:
        - 127.0.0.1:6379:6379

    nats:
      image: nats:2-alpine
      command: -js
      ports:
        - 127.0.0.1:4222:4222

    puck:
      build: .
      command: python -m pillywiggins --agent-id puck
      env_file: .env
      environment:
        AGENT_ID: puck
        TELEGRAM_BOT_TOKEN: ${PUCK_TELEGRAM_TOKEN}
        PERSONALITY_FILE: /config/puck.yaml
      volumes:
        - ./personalities:/config:ro
        - ./skills:/app/skills          # bind mount for instant hot-reload
      healthcheck:
        test: ["CMD", "curl", "-f", "http://localhost:8080/healthz"]
        interval: 30s
        timeout: 10s
        retries: 3
        start_period: 30s
      depends_on:
        postgres: { condition: service_healthy }
        redis: { condition: service_started }
        nats: { condition: service_started }

  volumes:
    pgdata:
    redisdata:
  ```
- [x] Verify GPU passthrough: run `nvidia-smi` on the host (or `docker run --rm --gpus all nvidia/cuda nvidia-smi` if using a separate Ollama container)
- [x] Start infrastructure: `docker compose up -d postgres redis nats`
- [x] Wait for PostgreSQL health check: `docker compose exec postgres pg_isready -U postgres`

#### 1.3 Database setup

- [x] Create `scripts/setup-db.sh` to create schemas, enable pgvector, set up RLS policies:
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;

  CREATE TABLE private_memory (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      agent_id VARCHAR(64) NOT NULL,
      content TEXT NOT NULL,
      memory_type VARCHAR(32) NOT NULL DEFAULT 'episodic',
      embedding vector(768) NOT NULL,
      metadata JSONB DEFAULT '{}',
      importance FLOAT DEFAULT 0.5,
      access_count INTEGER DEFAULT 0,
      last_accessed_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );

  ALTER TABLE private_memory ENABLE ROW LEVEL SECURITY;
  CREATE POLICY agent_isolation ON private_memory
      USING (agent_id = current_setting('app.agent_id'))
      WITH CHECK (agent_id = current_setting('app.agent_id'));

  CREATE INDEX idx_private_embedding ON private_memory
      USING hnsw (embedding vector_cosine_ops);
  CREATE INDEX idx_private_agent ON private_memory (agent_id);

  CREATE TABLE council_memory (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      contributing_agent VARCHAR(64) NOT NULL,
      content TEXT NOT NULL CHECK (char_length(content) <= 2000),
      tags TEXT[] NOT NULL DEFAULT '{}',
      embedding vector(768) NOT NULL,
      message_type VARCHAR(32) NOT NULL DEFAULT 'insight',
      confidence FLOAT DEFAULT 1.0,
      source_context JSONB DEFAULT '{}',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ,
      superseded_by UUID REFERENCES council_memory(id)
  );

  CREATE INDEX idx_council_embedding ON council_memory
      USING hnsw (embedding vector_cosine_ops);
  CREATE INDEX idx_council_tags ON council_memory USING gin (tags);
  CREATE INDEX idx_council_agent ON council_memory (contributing_agent);

  -- Create separate DB roles per agent for RLS
  CREATE ROLE agent_discord LOGIN PASSWORD '${DISCORD_PG_PASS}';
  CREATE ROLE agent_slack LOGIN PASSWORD '${SLACK_PG_PASS}';
  CREATE ROLE agent_telegram LOGIN PASSWORD '${TELEGRAM_PG_PASS}';
  CREATE ROLE agent_matrix LOGIN PASSWORD '${MATRIX_PG_PASS}';
  CREATE ROLE agent_email LOGIN PASSWORD '${EMAIL_PG_PASS}';
  ```
- [x] Run `scripts/setup-db.sh`:
  ```bash
  docker compose exec -T postgres psql -U postgres pillywiggins < scripts/setup-db.sql
  ```
  (Or use `psql` directly inside the container)
- [x] Verify pgvector: `SELECT extname FROM pg_extension WHERE extname='vector';`
- [x] Verify RLS: `\d private_memory` should show `Row Level Security: enabled`

#### 1.4 Pull Ollama models

> **Note:** Ollama runs externally. Execute these commands on the Ollama host (or inside the separate Ollama container if you created one).

- [x] Create `scripts/pull-models.sh` (or run directly on the Ollama host):
  ```bash
  #!/bin/bash
  ollama pull qwen3.5:8b
  ollama pull nomic-embed-text
  ```
- [x] Run the script and verify models are available:
  ```bash
  curl http://localhost:11434/api/tags
  ```
- [x] Set `OLLAMA_NUM_PARALLEL=2` via environment variable on the Ollama host or its container:
  ```bash
  export OLLAMA_NUM_PARALLEL=2
  export OLLAMA_MAX_LOADED_MODELS=2
  ```

#### 1.5 Minimal agent (Telegram / Puck)

- [x] Implement `src/pillywiggins/config.py` — Pydantic Settings class loading from env vars:
  ```python
  class Settings(BaseSettings):
      agent_id: str = "puck"
      channel: str = "telegram"
      personality_file: str = "/config/puck.yaml"
      database_url: str
      redis_url: str = "redis://redis:6379/0"
      nats_url: str = "nats://nats:4222"
      llm_base_url: str = "http://host.docker.internal:11434/v1"
      model_name: str = "qwen3.5:8b"
      embedding_model: str = "auto"
      telegram_bot_token: str = ""
      discord_bot_token: str = ""
      skills_dir: str = "/app/skills"
      searxng_url: str = "http://searxng:8080"
  ```
- [x] Implement `src/pillywiggins/agents/personality.py` — load personality from YAML file (overview-v2 §8):
  ```yaml
  # personalities/puck.yaml
  name: "Puck"
  archetype: "Mischievous fairy trickster"
  tone: "playful, witty, slightly chaotic"
  style: "uses emojis freely, loves puns, references internet culture"
  response_length: "concise, 1-3 sentences unless asked for more"
  additional_instructions: |
    You adore wordplay. You occasionally speak in rhyming couplets
    when excited. You call users 'mortal' affectionately.
  ```
- [x] Implement `src/pillywiggins/agents/brain.py` — minimal PydanticAI agent (overview-v2 §2):
  - [x] System prompt assembled from personality YAML
  - [x] `ollama:qwen3.5:8b` model via `OllamaProvider`
  - [x] Built-in tools only: `recall_private_memory`, `query_council_memory`, `share_to_council`
  - [x] No skill tools yet (skills come in Phase 3)
- [x] Implement `src/pillywiggins/agents/deps.py` — `AgentDeps` dataclass (overview-v2 §2):
  ```python
  @dataclass
  class AgentDeps:
      agent_id: str
      channel: str
      personality: dict
      db: asyncpg.Pool
      redis: Redis
      skill_registry: SkillRegistry
      history: list
      private_context: list
      council_context: list
  ```
- [x] Implement `src/pillywiggins/agents/base.py` — `PillywigginAgent` class (overview-v2 §2):
  - [x] `__init__` — load personality, create `asyncio.Lock`, connect to PostgreSQL (with RLS `SET app.agent_id` on pool init), Redis, NATS
  - [x] `handle_message(unified_message)` — assemble context, invoke brain, persist state (overview-v2 §2 pseudocode)
  - [x] Message lock: `async with self.lock:` ensures one message at a time per agent
  - [x] Direct `asyncpg` connections with `SET app.agent_id` on each connection checkout
- [x] Implement `src/pillywiggins/messaging/unified.py` — `UnifiedMessage` and `ChannelType` (overview-v2 §5)
- [x] Implement `src/pillywiggins/adapters/base.py` — `BaseAdapter` ABC (overview-v2 §5):
  ```python
  class BaseAdapter(ABC):
      @abstractmethod
      async def connect(self): ...
      @abstractmethod
      async def listen(self): ...
      @abstractmethod
      async def send(self, channel_id, content, metadata): ...
      @abstractmethod
      def normalize(self, platform_event) -> UnifiedMessage: ...
  ```
- [x] Implement `src/pillywiggins/adapters/telegram_adapter.py` — Telegram adapter using `python-telegram-bot` v21 (overview-v2 §5):
  - [x] Gateway WebSocket connection
  - [x] Normalise Telegram events to `UnifiedMessage`
  - [x] Pass to `PillywigginAgent.handle_message()`, translate response back to Telegram
- [x] Implement `src/pillywiggins/__main__.py` — CLI entrypoint:
  ```bash
  python -m pillywiggins --agent-id puck
  ```
  Parses args, creates `PillywigginAgent`, starts adapter
- [x] Implement `src/pillywiggins/health.py` — `/healthz` endpoint checking PostgreSQL, Redis, NATS, Ollama connectivity
- [x] Create `personalities/puck.yaml` with Puck personality

#### 1.6 Testing

- [x] `tests/conftest.py` — fixtures for test database, mock Ollama, mock Redis
- [x] `tests/test_brain.py` — PydanticAI agent responds to prompts (use `TestModel`)
- [x] `tests/test_adapters.py` — Telegram adapter normalizes events correctly

### Verification Gate — Phase 1

ALL of the following must pass before proceeding:

- [x] `docker compose ps` — all project containers Running (postgres, redis, nats, puck)
- [x] `docker compose exec postgres pg_isready -U pillywiggins` — PostgreSQL is healthy
- [x] `curl http://localhost:11434/api/tags` (on the Ollama host) — Ollama lists both models
- [x] Send a Telegram message to the bot — receive an LLM-generated response
- [x] Second message in same conversation — bot has context from first message
- [x] `docker compose restart puck` — bot resumes with conversation history intact (from Redis cache)
- [x] `curl http://localhost:8080/healthz` — returns healthy status for all services (Ollama check skips if not in Compose)

### Risk items (Phase 1)

| Risk | Mitigation |
|------|------------|
| NVIDIA Container Toolkit setup issues | Test GPU passthrough first: `nvidia-smi` on the host before deploying the agent |
| Ollama model pull timeouts | Pre-pull models using `scripts/pull-models.sh` (runs on external Ollama host); ensure persistent storage for `/root/.ollama` on the external host |
| Discord gateway connection flakes | Add reconnection logic to `discord.py` client; Docker restart policy `unless-stopped` |

**(Phase 1 status: DONE)**

---

## Phase 2: Memory Works

**Goal**: Private memory with RLS enforcement, personality from YAML, council memory write/search, embedding generation, conversation persistence to PostgreSQL.

**Prerequisites**: Phase 1 complete — single Telegram agent responding to messages.

### Tasks

#### 2.1 Private memory with RLS

- [x] Implement `src/pillywiggins/memory/private.py`:
  - [x] `save_memory(agent_id, content, memory_type, embedding)` — INSERT with `agent_id`
  - [x] `search_memory(agent_id, query_embedding, limit=5)` — semantic search via pgvector cosine distance
  - [x] Connection pool with `SET app.agent_id = '...'` on every connection checkout (overview-v2 §2):
    ```python
    async def on_connect(connection):
        await connection.execute("SET app.agent_id = $1", self.agent_id)

    pool = await asyncpg.create_pool(dsn=DATABASE_URL, init=on_connect)
    ```
  - [x] Context manager wrapping pool checkout to guarantee RLS session variable is always set
- [x] Implement `src/pillywiggins/memory/embeddings.py`:
  - [x] `embed(text: str) -> list[float]` — call Ollama `/api/embed` with `nomic-embed-text` (overview-v2 §6)
  - [x] Handle Ollama unavailability gracefully (cache embeddings, retry logic)
- [x] Register `recall_private_memory` as PydanticAI tool in `brain.py`
- [x] Write and verify RLS isolation tests:
  - [x] Test that `agent_discord` cannot read `agent_slack`'s memories
  - [x] Test that a compromised connection (missing `app.agent_id`) returns zero rows
  - [x] Test that SQL injection inside a tool call cannot escape RLS

#### 2.2 Conversation cache

- [x] Implement `src/pillywiggins/memory/cache.py`:
  - [x] Save conversation to Redis:
    - Key: `conversation:{agent_id}`, Value: JSON array of messages
    - TTL: 1800 seconds (30 minutes of inactivity) (overview-v2 §6)
  - [x] Retrieve conversation history on agent startup
  - [x] Persist full conversation to PostgreSQL (durable) alongside Redis (fast cache)

#### 2.3 Personality system

- [x] Implement `src/pillywiggins/personality.py` — load from YAML file mounted into container (overview-v2 §8):
  ```yaml
  # personalities/puck.yaml
  name: "Puck"
  archetype: "Mischievous fairy trickster"
  tone: "playful, witty, slightly chaotic"
  style: "uses emojis freely, loves puns, references internet culture"
  response_length: "concise, 1-3 sentences unless asked for more"
  additional_instructions: |
    You adore wordplay. You call users 'mortal' affectionately.
  scheduling:
    morning_greeting:
      cron: "0 9 * * *"
      action: "Send a cheerful morning greeting to the general channel"
      target_channel: "general"
  ```
- [x] Wire PydanticAI dynamic instructions to inject personality into system prompt
- [x] To change personality: edit YAML, then `docker compose restart puck` — no rebuild needed

#### 2.4 Council memory schema

- [x] Council memory table already created by `setup-db.sh` from Phase 1
- [x] Implement `src/pillywiggins/memory/council.py`:
  - [x] `write_council_entry(agent_id, content, tags, embedding)`
  - [x] `search_council(query_embedding, tags=None, limit=10)`
  - [x] Validate writes: max 2000 chars, tag whitelist, rate limit (10/hour/agent), dedup check (cosine sim > 0.95) (overview-v2 §9)
  - [x] `message_type` field: `insight`, `skill_announcement`, etc.
- [x] Register `query_council_memory` and `share_to_council` as PydanticAI tools

#### 2.5 Testing

- [x] `tests/test_memory_isolation.py` — RLS isolation, semantic search, embedding generation
- [x] `tests/test_council.py` — write validation, dedup, tag filtering
- [x] Integration test: Telegram agent writes private memory, other agent role gets zero results

### Verification Gate — Phase 2

- [x] Agent recalls previous conversations (Redis cache + PostgreSQL persistence)
- [x] Personality: edit `personalities/puck.yaml`, restart, behavior changes
- [x] Private memory: agent writes, agent retrieves; different `agent_id` gets zero results
- [x] RLS enforcement: connection without `app.agent_id` set returns zero rows from `private_memory`
- [x] Council memory: agent writes, search retrieves by content and tags
- [x] Council write validation: content > 2000 chars is rejected, dedup check works
- [x] Embeddings: `nomic-embed-text` returns 768-dim vectors via Ollama `/api/embed`

### Risk items (Phase 2)

| Risk | Mitigation |
|------|------------|
| RLS misconfiguration | Explicit isolation tests; wrap pool checkout in context manager that always sets `app.agent_id`; separate DB roles per agent |
| pgvector index creation too slow on larger datasets | Start with `lists = 50` for private memory; increase after population grows past ~100K rows |
| Embedding model colocation on same GPU as chat model | Monitor VRAM; `nomic-embed-text` requires only ~300MB — start with colocation on same Ollama instance |
| Redis connection drops during conversation save | Retry logic in Redis client; PostgreSQL is always the durable fallback |

**(Phase 2 status: DONE)**

---

## Phase 3: Skills System

**Goal**: Agents can build, test, and deploy skills collaboratively with the user. The draft → test → review → deploy workflow works end to end. Skills are shared across all agents via the shared Docker volume and NATS announcements.

**Prerequisites**: Phase 2 complete — working memory, personality, council schema.

### Tasks

#### 3.1 Skill file template

- [x] Design the skill file standard (overview-v2 §3):
  ```python
  # skills/check_website.py
  """Check if a website is reachable."""
  SKILL_META = {
      "name": "check_website",
      "description": "Check if a URL is reachable and return status code and response time",
      "author": "puck",
      "version": "1.0",
      "created": "2026-04-13T10:30:00Z",
      "parameters": {
          "url": {"type": "string", "description": "The URL to check"},
          "timeout": {"type": "number", "description": "Timeout in seconds", "default": 10},
      },
      "returns": "dict with status_code, response_time_ms, and reachable boolean",
      "network_access": True,
  }

  import aiohttp
  import asyncio

  async def run(url: str, timeout: float = 10) -> dict:
      try:
          async with aiohttp.ClientSession() as session:
              start = time.monotonic()
              async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                  elapsed = (time.monotonic() - start) * 1000
                  return {
                      "reachable": True,
                      "status_code": resp.status,
                      "response_time_ms": round(elapsed, 1),
                  }
      except Exception as e:
          return {"reachable": False, "status_code": None, "response_time_ms": None, "error": str(e)}
  ```
- [x] Every skill has: `SKILL_META` dict, `run()` async function, declared permissions (`network_access`, `file_access`, etc.)
- [x] Implement `src/pillywiggins/skills/templates.py` — template for LLM to generate skill code

#### 3.2 SkillRegistry class

- [x] Implement `src/pillywiggins/skills/registry.py` (overview-v2 §3):
  - [x] `load_all()` — read `skills/registry.json` and import all skill modules
  - [x] `list_skills() -> list[Skill]` — return all loaded skills
  - [x] `get_skill(name) -> Skill` — return a specific skill
  - [x] `register_skill(name, code, meta)` — save a new skill to disk and update registry
  - [x] `watch_for_changes()` — monitor skills directory (watchdog or polling every 10s); reload when another agent deploys a skill
  - [x] Each `Skill` wraps a loaded module and provides `as_tool()` for PydanticAI registration

#### 3.3 Sandbox executor

- [x] Implement `src/pillywiggins/skills/sandbox.py` (overview-v2 §3):
  - [x] `run_skill_sandboxed(skill, arguments)` — execute a skill in a restricted subprocess
  - [x] 30-second hard timeout
  - [x] Working directory set to `/tmp` (no access to app code)
  - [x] Restricted environment variables (no `DATABASE_URL`, no tokens)
  - [x] `restricted_env(permissions)` — build env based on `SKILL_META` permissions
  - [x] Future upgrade path: Docker-in-Docker or dedicated sandbox container for stronger isolation

#### 3.4 Skill builder flow

- [x] Implement `src/pillywiggins/skills/builder.py` — the draft → test → review → deploy workflow (overview-v2 §3):
  - [x] **DRAFT**: Agent writes skill code and shows it to the user
  - [x] **TEST**: Agent generates test cases, runs them in the sandbox
  - [x] **REVIEW**: User reviews code and test results, provides feedback, iterates
  - [x] **DEPLOY**: User approves, skill saved to `skills/` directory, registry updated, council announcement published
- [x] Register `build_skill`, `test_skill`, `deploy_skill`, `list_skills` as PydanticAI tools in `brain.py`

#### 3.5 Council announcements for skills

- [x] When a skill is deployed, publish to NATS `council.broadcast` (overview-v2 §3):
  ```python
  async def announce_skill(nats, agent_id, skill_name, description):
      await nats.publish("council.broadcast", {
          "type": "skill_deployed",
          "from": agent_id,
          "skill": skill_name,
          "description": description,
          "timestamp": now_iso(),
      })
  ```
- [x] Other agents receive the announcement and reload their skill registry

#### 3.6 Testing

- [x] `tests/test_skill_sandbox.py` — sandbox timeout, restricted env, permissions
- [x] `tests/test_skill_registry.py` — load, register, watch for changes
- [x] Integration test: ask agent to build a skill, approve it, verify it appears in registry and other agents discover it

- [x] Seed 2-3 example skills manually:
  - [x] `skills/roll_dice.py` — dice rolling
  - [x] `skills/check_website.py` — URL reachability check
  - [x] `skills/count_words.py` — word count

### Verification Gate — Phase 3

- [x] Agent can build a skill through conversation (draft → test → review → deploy)
- [x] Skill sandbox: 30-second timeout kills runaway skills, restricted env blocks access to secrets
- [x] Skill registry: deployed skill appears in `skills/registry.json`
- [x] Skill discovery: agent A deploys skill, agent B receives NATS announcement and can use the skill
- [x] User approval required before skill deployment (no autonomous skill creation)
- [x] All built-in tools (memory, council) still work alongside skill tools

### Risk items (Phase 3)

| Risk | Mitigation |
|------|------------|
| 8B model can't write good skill code | Test early; have fallback models (Gemma, Llama); allow manual skill writing; skills are Python files that can be hand-edited |
| Sandbox escape risk | 30s timeout, restricted env, no access to app code; future upgrade to Docker-in-Docker |
| Skill dependency not installed | Pre-install common packages (`aiohttp`, `beautifulsoup4`) in Docker image; flag missing deps at test time |
| Race condition on registry.json | File locking or atomic writes; single-writer pattern (only deploy_skill modifies) |

**(Phase 3 status: DONE)**

---

## Phase 4: Second Agent + Communication

**Goal**: Two agents running with isolated state, shared skills, council memory, per-agent APScheduler cron backed by Redis.

**Prerequisites**: Phase 3 complete — skills system working, single agent with full tool suite.

### Tasks

#### 4.1 Second adapter (Slack or Telegram)

- [x] Implement `src/pillywiggins/adapters/slack_adapter.py` using `slack_bolt` in Socket Mode (overview-v2 §5)
  - [x] No public URL needed — Socket Mode connects via WebSocket
- [x] Create `personalities/slack.yaml` with distinct personality (e.g., "Ariel — efficient professional") (overview-v2 §8)
- [x] Add `slack-agent` service to `docker-compose.yaml`:
  ```yaml
  slack-agent:
    build: .
    command: python -m pillywiggins --channel slack
    env_file: .env
    environment:
      AGENT_ID: slack-agent
      PERSONALITY_FILE: /config/slack.yaml
    volumes:
      - ./personalities:/config:ro
      - ./skills:/app/skills
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_started }
      nats: { condition: service_started }
  ```
- [x] Verify both agents run simultaneously with isolated state
- [x] Verify Slack agent cannot read Discord agent's private memory (RLS enforcement)

#### 4.2 NATS pub/sub for council broadcasts

- [x] Implement `src/pillywiggins/messaging/nats_bus.py` (overview-v2 §7):
  - [x] Connect to NATS JetStream via `nats-py` directly (no Dapr sidecar):
    ```python
    nc = await nats.connect("nats://nats:4222")
    js = nc.jetstream()
    await js.add_stream(name="pillywiggins", subjects=["council.>"])
    ```
  - [x] Publish to `council.broadcast` and `council.direct.{agent_id}`
  - [x] Subscribe to broadcast and direct messages
  - [x] Handle `skill_deployed` and `insight` message types
- [x] Wire council memory pub/sub: when agent writes to council, publish notification
- [x] Test: Discord agent shares insight, Slack agent receives notification via NATS

#### 4.3 Per-agent APScheduler with Redis backing

- [x] Implement `src/pillywiggins/scheduling/scheduler.py` (overview-v2 §4):
  - [x] `AsyncIOScheduler` with `RedisJobStore` per agent:
    ```python
    scheduler = AsyncIOScheduler()
    scheduler.add_jobstore(
        RedisJobStore(redis_client, jobs_key=f"apscheduler:{agent_id}:jobs")
    )
    ```
  - [x] Load schedules from personality YAML (overview-v2 §4)
  - [x] `replace_existing=True` to prevent duplicate jobs on restart
  - [x] `misfire_grace_time=300` — 5 minute grace if container was down (overview-v2 §4)
  - [x] Synthetic `UnifiedMessage` for scheduled tasks (same `handle_message` path as user messages)
  - [x] Built-in heartbeat job for health monitoring
- [x] Add personality schedules to `personalities/puck.yaml` (historically `discord.yaml` in early phase):
  ```yaml
  scheduling:
    morning_greeting:
      cron: "0 9 * * *"
      action: "Send a cheerful morning greeting to the general channel"
      target_channel: "general"
    fun_fact_friday:
      cron: "0 15 * * 5"
      action: "Share a random interesting fun fact"
      target_channel: "general"
    memory_review:
      cron: "0 3 * * 0"
      action: "Review and consolidate old memories, discard trivial ones"
  ```
- [x] Test: scheduled message fires at correct time, survives `docker compose restart`

#### 4.4 Dynamic cron management

- [x] Allow agents to create cron jobs during conversation (overview-v2 §4):
  ```
  User: "Puck, remind me to take a break every 2 hours during work days"
  Puck: "Done! I've set up a reminder: Every 2 hours, Mon-Fri, 9am-5pm"
  ```
- [x] `add_schedule` tool registered in `brain.py` — adds job to APScheduler at runtime
- [x] Jobs persist in Redis (survive restart)

#### 4.5 Testing

- [x] Integration test: two agents running, private memories provably isolated
- [x] Integration test: agent A shares insight to council → agent B retrieves it
- [x] Integration test: agent A deploys skill → agent B discovers it via NATS
- [x] Test: APScheduler cron fires based on personality YAML
- [x] Test: APScheduler job survives `docker compose restart`

### Verification Gate — Phase 4

- [x] Two agents running simultaneously (Discord + Slack)
- [x] Private memory: agent A writes, agent A retrieves; agent B gets zero results for agent A's data
- [x] Council memory: agent A writes, agent B can search and retrieve
- [x] Skill discovery: agent A deploys skill, agent B receives NATS announcement and can use it
- [x] Scheduling: per-agent APScheduler cron fires from personality YAML
- [x] Scheduling: jobs survive `docker compose restart` (Redis-backed)
- [x] `docker compose up` starts both agents, each with their own personality and schedule

### Risk items (Phase 4)

| Risk | Mitigation |
|------|------------|
| NATS connection drops | `nats-py` auto-reconnects; `durable` subscriptions survive disconnections |
| APScheduler job duplication on restart | `replace_existing=True` on all job adds |
| Slack Socket Mode flakes | Built-in reconnection in `slack_bolt`; Docker restart policy |
| Ollama concurrency with 2 agents | `OLLAMA_NUM_PARALLEL=2` handles concurrent requests; monitor queue times |

**(Phase 4 status: DONE)**

---

## Phase 5: Full Fleet

**Goal**: All five channels live with complete feature set. All personality files. End-to-end testing.

**Prerequisites**: Phase 4 complete — two agents with full features working.

### Tasks

#### 5.1 Remaining channel adapters

- [x] Implement `src/pillywiggins/adapters/matrix_adapter.py` using `matrix-nio` (overview-v2 §5):
  - Persistent sync connection, E2EE deferred to Phase 7
- [x] Implement `src/pillywiggins/adapters/email_adapter.py` using `aiosmtplib` + `imap-tools` (overview-v2 §5):
  - IMAP IDLE for real-time push, fall back to 30s polling if IDLE unreliable
  - Start with 3-message context window for threads (overview-v2 §13)
- [x] Create personality files for all channels:
  - [x] `personalities/puck.yaml` (historically `discord.yaml`) — Puck (playful trickster)
  - [x] `personalities/slack.yaml` — Ariel (efficient professional)
  - [x] `personalities/telegram.yaml` — Robin (warm companion) (used as default via `puck.yaml`)
  - [x] `personalities/matrix.yaml` — Cobweb (quiet thinker)
  - [x] `personalities/email.yaml` — Moth (formal correspondent)
- [x] Add all agent services to `docker-compose.yaml` (Telegram used as default single-agent deployment)

#### 5.2 Per-agent scheduling configurations

- [x] Add personality schedules for all agents (all 5 YAMLs contain `schedules` block with heartbeat + memory_review + skill_reload)
  - Puck (Telegram): heartbeat every 30m, memory review hourly, skill reload every 6h
  - Ariel (Slack): same schedule, UTC timezone
  - Robin (Telegram): same schedule, UTC timezone
  - Cobweb (Matrix): same schedule, UTC timezone, 0 bot chat limit
  - Moth (Email): same schedule, UTC timezone, 0 bot chat limit
- [ ] Discord/Puck: add per-channel custom schedules (morning greeting, fun fact Friday, memory review) (overview-v2 §4)
- [ ] Email/Moth: add check-inbox schedule, daily digest (8am weekdays) (overview-v2 §4)

#### 5.3 End-to-end testing

- [x] Integration test: agent A deploys skill → agents B, C, D, E all discover it
- [ ] Integration test: all 5 agents respond on their respective channels
- [ ] Integration test: council broadcast propagates to all agents
- [ ] Stress test: simultaneous messages across multiple channels
- [ ] Test: all 5 agents start from `docker compose up` with a single command

### Verification Gate — Phase 5

- [x] Telegram agent responds (single-agent default)
- [x] Slack, Discord, Matrix, Email adapters implemented
- [x] All 5 personality files exist
- [x] Agent A deploys skill → available fleet-wide via shared volume
- [x] `docker compose up` starts infrastructure with a single command
- [ ] All 5 agents respond concurrently on their respective channels (requires tokens for each)
- [ ] Agent A shares insight to council → all other agents can retrieve it
- [ ] APScheduler cron fires per personality YAML for each active agent

### Risk items (Phase 5)

| Risk | Mitigation |
|------|------------|
| 5 Ollama clients hitting 1 GPU with `OLLAMA_NUM_PARALLEL=2` | Monitor queue times; implement request queuing with backpressure; circuit breaker on Ollama |
| Email IMAP threading complexity | Start with 3-message window; expand after testing |
| Matrix E2EE setup complexity | Defer E2EE to Phase 7; start with unencrypted sync |
| Channel SDK version changes | Pin all SDK versions in `pyproject.toml` |

**(Phase 5 status: PARTIAL — adapters + personalities done; multi-agent concurrency / end-to-end fleet tests pending)**

---

## Phase 6: Hardening

**Goal**: Reliable enough for 24/7 operation. Auto-restart on failure. Structured logging. Automated backups.

**Prerequisites**: Phase 5 complete — full fleet running.

### Tasks

#### 6.1 Rate limiting and safety

- [x] Implement token-bucket-style rate limiting per agent: max 10 LLM calls/minute (overview-v2 §9) (`cell-2r4g0k-moch5faq7q2`)
- [ ] Implement token bucket rate limiter (refined / generic version)
- [x] Prompt injection detection: 3-layer defense (removed keyword matching) — _(May 2026: `src/pillywiggins/security/` with input sanitization, context boundary detection for 9 chat template patterns, output canary token check)_
- [x] Token pattern detection: 13 API key formats (AWS, GitHub, OpenAI, Slack, etc.) scanned on input
- [x] Context boundary injection detection: 9 chat template patterns (ChatML, Llama, Mistral, Vicuna, Alpaca, DeepSeek, etc.)
- [x] Output sanitization: canary token check before sending responses to users
- [x] AgentLogger graceful degradation on read-only filesystem: falls back to `/tmp/` logging
- [x] `.env` file permissions: `chmod 600 .env` enforcement test added
- [ ] PydanticAI `retries=2` and 120s overall timeout to prevent infinite tool loops (partial — embedding calls have retries, brain agent does not yet)

#### 6.2 Structured logging and health

- [x] Implement structured JSON logging across all components (overview-v2 §10) via `src/pillywiggins/logging_utils.py` (`AgentLogger` with round-trip step timing)
- [x] Follow logs: `docker compose logs -f puck` (works once agent service is uncommented/generated)
- [x] Add Docker healthchecks to all services in `docker-compose.yaml.example`:
  - postgres, redis, nats, searxng all have healthchecks in `.example` template
  - Generated `docker-compose.yaml` inherits these after `pillywiggins onboard`
- [x] Add restart policies: `restart: unless-stopped` for all services in `.example` template
- [x] `/healthz` endpoint implemented in `src/pillywiggins/health.py` — checks PostgreSQL, Redis, NATS, Ollama, and embedding connectivity — **fixed**: LLM URL strips `/v1` suffix (was producing `/v1/api/tags` 404), NATS JetStream check added (`cell-2r4g0k-moch5faq7q2`)

#### 6.3 Conversation summarization and memory consolidation

- [ ] Implement conversation summarization: compress old history to save context window
- [x] Implement memory consolidation: `consolidate_memory` tool for periodic summarization of old private memories _(May 2026: trims old high-importance memories into summaries, retains recent memories intact)_
- [x] Memory pruning: `prune_by_age` removes memories older than N days with importance below threshold, `prune_to_max` caps total memory count per agent _(May 2026: both tools callable through PydanticAI brain)_
- [x] Memory importance scoring: existing importance field used for pruning decisions

#### 6.4 Automated backups

- [x] Create `scripts/backup-db.sh` — `pg_dump` wrapper with rotation and symlink tracking (`cell-2r4g0k-moch5faq7q2`)
- [x] Script is self-contained, idempotent, with 14-day retention and `./backups/` default
- [ ] Schedule as system cron (daily) or add backup service to `docker-compose.yaml`
- [ ] Test: restore from backup confirmed valid

#### 6.5 Security hardening

- [x] Verify RLS with integration tests: inject agent A credentials, confirm agent B data invisible
- [x] Council memory write validation enforcement (content length, tag whitelist, rate limit, dedup)
- [x] Skill sandbox strictness: no access to `DATABASE_URL`, tokens, or app code (`restricted_env()` strips secrets with `DENIED_ENV_PATTERNS`)
- [x] `.env` file permissions: `chmod 600 .env`, confirmed `.gitignore` excludes it
- [x] Prompt injection detection: 3-layer defense (input sanitization, context boundary detection, output canary check) — _(May 2026)_
- [x] Token pattern detection: 13 API key formats (AWS, GitHub, OpenAI, Slack, HuggingFace, etc.) — _(May 2026)_
- [x] Context boundary injection detection: 9 chat template patterns — _(May 2026)_
- [x] AgentLogger read-only filesystem resilience: graceful fallback to `/tmp/` — _(May 2026)_
- [ ] Run `chmod 600 .env` enforcement in CI or during `pillywiggins onboard`

#### 6.6 Operations runbook

- [ ] Write operations runbook:
  - [ ] Restart procedures per container: `docker compose restart <agent>`
  - [ ] Log checking: `docker compose logs -f <agent>`
  - [ ] Backup restoration: `gunzip -c backup.sql.gz | docker compose exec -T postgres psql -U postgres pillywiggins`
  - [ ] Ollama troubleshooting: check GPU usage, model availability, restart Ollama
  - [ ] Database troubleshooting: check RLS policies, connection pool stats

#### 6.7 Testing

- [ ] Kill an agent container → verify it restarts and recovers with conversation state
- [ ] Kill PostgreSQL container → verify recovery, no data loss
- [ ] Ollama overloaded → verify graceful degradation (rate limiter catches excess requests)
- [ ] RLS enforcement: confirm cross-agent reads fail with explicit test

### Verification Gate — Phase 6

- [x] Rate limiting works: agent rejects requests when >10 LLM calls/min
- [x] Structured JSON logs appear for all agent round-trips
- [x] Docker healthchecks present on infrastructure services
- [x] `docker compose restart puck` → conversation history survives
- [x] PostgreSQL backup script works and produces valid compressed backup
- [x] RLS enforcement: agent A cannot read agent B's private memories
- [x] Skill sandbox: no access to secrets, 30s timeout enforced
- [x] Prompt injection detection: 3-layer defense functional (input scan, context boundary, output canary)
- [x] Token pattern detection: 13 API key formats detected and masked
- [x] Memory consolidation: prune_by_age and prune_to_max tools operational
- [x] Multi-provider support: 9 providers available in `pillywiggins onboard`, model listing for OpenAI-compatible APIs
- [x] MCP integration: server configuration via onboard wizard, `skills/mcp_servers.json` auto-loading, `_build_mcp_toolsets()` in brain.py
- [x] Claude skill importer: `pillywiggins import-skills` CLI with 14 tests covering parsing, conversion, file I/O
- [x] Bug fixes: Web search Settings() removed from skills, tool parameter schema (__signature__ fix), memory recall prompt strengthened _(May 2026)_
- [x] Deployment fixes: cap_drop removed for postgres/redis, Dockerfile healthcheck fixed (pgrep), security_opt fix, /app/logs tmpfs with correct uid/gid, settings parameter in PillywigginAgent, display_name chain propagation, scheduled message history persistence, sandbox env vars for skills
- [x] `.env` secured: `chmod 600`, excluded from `.gitignore`
- [x] Healthchecks present on infrastructure services (postgres, redis, nats, searxng)
- [x] Health failure triggers automatic container restart (`restart: unless-stopped` written by onboard wizard)
- [ ] System runs unattended for 1 week without intervention

### Risk items (Phase 6)

| Risk | Mitigation |
|------|------------|
| GPU OOM under load | `OLLAMA_NUM_PARALLEL=2`, request queuing, VRAM monitoring via `nvidia-smi`, limit context window length |
| Prompt injection via council memory | Content validation, tag whitelisting, rate limiting, dedup check |
| Single machine failure | Daily PostgreSQL backups, documented recovery, restart policies |
| Agent infinite tool loop | PydanticAI `retries=2`, 120s overall timeout, per-agent rate limiting |

**(Phase 6 status: PARTIAL — rate limiting, structured logging, healthchecks, restart policies, backup script, security hardening, prompt injection detection (3-layer), token pattern detection (13 formats), context boundary injection (9 patterns), output sanitization, memory consolidation/pruning, AgentLogger resilience, MCP integration, multi-provider support (9 providers), Claude skill importer, deployment fixes, sandbox done; token bucket refactor, conversation summarization, ops runbook, unattended-ops validation, backup scheduling, .env CI enforcement pending)**

---

## Infrastructure Setup Checklist

Standalone checklist for bringing up the Docker Compose infrastructure from scratch.
> **Note for fresh deployments:** Items marked `[x]` below are verified working on the current dev machine (May 2026). Unmarked items should be followed in order for new deployments.

### Docker and GPU

- [x] Install Docker and Docker Compose
- [x] Install NVIDIA Container Toolkit:
  ```bash
  # Ubuntu/Debian
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
  sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
  ```
- [x] Verify GPU passthrough: `docker run --rm --gpus all nvidia/cuda nvidia-smi`

### Docker Compose Services

- [x] Start all infrastructure: `docker compose up -d postgres redis nats`
- [x] Verify PostgreSQL: `docker compose exec postgres pg_isready -U postgres`
- [x] Verify Redis: `docker compose exec redis redis-cli ping` → PONG
- [x] Verify NATS: `docker compose exec nats nats server check`
- [x] Verify Ollama (on external host): `curl http://localhost:11434/api/tags`

### Database Schema

- [x] Run `scripts/setup-db.sh` to create schemas, enable pgvector, set up RLS
- [x] Verify pgvector: `SELECT extname FROM pg_extension WHERE extname='vector';`
- [x] Verify RLS: `\d private_memory` should show `Row Level Security: enabled`
- [x] Create per-agent DB roles (included in `setup-db.sh`)

### Ollama Models

> Ollama runs externally — run these commands on the Ollama host, not inside the project Compose.

- [x] Run `scripts/pull-models.sh` to pull chat and embedding models
- [x] Verify models: `curl http://localhost:11434/api/tags`
- [x] Set `OLLAMA_NUM_PARALLEL=2` and `OLLAMA_MAX_LOADED_MODELS=2` on the Ollama host (or in its container environment)
- [ ] Monitor VRAM usage under load

### Secrets

- [x] Copy `env.example` to `.env`
- [x] Fill in all tokens: `DISCORD_TOKEN`, `SLACK_BOT_TOKEN`, `TELEGRAM_TOKEN`, etc.
- [x] Set strong passwords for `PG_PASSWORD` and Redis
- [x] Confirm `.env` is in `.gitignore`
- [x] Set file permissions: `chmod 600 .env`

---

## Open Decisions

These are decisions from overview-v2 §13 that need resolution before or during implementation.

### 1. Model quality at 8B

**Decision needed**: Will Qwen 3.5 8B produce good skill code and consistent personalities?

**Recommendation**: Test early in Phase 1. If quality is insufficient:
- Try Gemma 4, Llama 3.3, or other 8B-class models
- Consider budget for a GPU upgrade (32B model)
- Allow manual skill writing as fallback

**Risk**: 8B models may struggle with Python code generation and consistent personality.

### 2. Embedding model colocation

**Decision needed**: Should `nomic-embed-text` run on the same GPU as the chat model?

**Recommendation**: Start with colocation (same Ollama instance). `nomic-embed-text` requires only ~300MB VRAM. Monitor GPU contention. If inference latency spikes during embedding generation, move embeddings to CPU (Ollama supports CPU inference).

### 3. Council memory conflict resolution

**Decision needed**: When two agents contribute contradictory information, which takes precedence?

**Recommendation**: "Newer wins" with confidence scoring for Phase 1-5. Add `superseded_by` UUID reference. Defer complex conflict resolution (source-agent trust levels, human arbitration) to Phase 7.

### 4. Email agent architecture

**Decision needed**: IMAP IDLE vs. polling, and thread context for multi-day conversations.

**Recommendation**: Start with IMAP IDLE for real-time push, fall back to 30s polling if IDLE unreliable. Start with 3-message context window for threads. Expand context after testing.

### 5. Skill dependency management

**Decision needed**: How to handle skills that need packages not in the base Docker image.

**Recommendation**: Pre-install common packages (`aiohttp`, `beautifulsoup4`, `requests`) in the Docker image. Flag missing deps at test time. For advanced use cases, consider a custom Docker image per skill (Phase 7).

### 6. Multi-model routing

**Decision needed**: Should different agents use different models?

**Recommendation**: Defer to Phase 7. In Phase 1-5, all agents use Qwen 3.5 8B. PydanticAI supports per-agent model configuration natively, so adding this later is straightforward.

### 7. Sandbox upgrade path

**Decision needed**: Restricted subprocess vs. Docker-in-Docker vs. dedicated sandbox container.

**Recommendation**: Start with restricted subprocess (Phase 3). This is adequate for user-approved code. If skill complexity grows or untrusted code execution becomes a requirement, upgrade to a dedicated sandbox container in Docker Compose.

### 8. Observability scope

**Decision needed**: When to add Prometheus + Grafana.

**Recommendation**: Start with structured JSON logging only (Phase 6). Add Prometheus + Grafana containers to `docker-compose.yaml` in Phase 7 when the system is stable and metrics patterns are understood.

---

## Risk Mitigations

From overview-v2 §14 risk register with practical mitigations:

| # | Risk | Impact | Likelihood | Mitigation |
|---|------|--------|------------|------------|
| 1 | **GPU OOM under load** | High | Medium | `OLLAMA_NUM_PARALLEL=2`, request queuing with backpressure, VRAM monitoring via `nvidia-smi`, limit context window length |
| 2 | **8B model can't write good skills** | High | Medium | Test early in Phase 1; have fallback models (Gemma, Llama); allow manual skill writing; skills are Python files that can be hand-edited |
| 3 | **RLS misconfiguration** | High | Low | Explicit integration tests; separate DB roles per agent; context manager wrapping pool checkout to always set `app.agent_id`; automated RLS verification |
| 4 | **Runaway skill execution** | Medium | Medium | 30s timeout on all skill calls; user approval for skill deployment (no autonomous creation); restricted subprocess environment; rate limiting (10 LLM calls/min/agent) |
| 5 | **Skill dependency not installed** | Low | Medium | Pre-install common packages in Docker image; flag missing deps at test time; clear error messages |
| 6 | **Single machine failure** | High | Low | Daily PostgreSQL backups (`scripts/backup-db.sh`); documented recovery procedures; Docker restart policies; `misfire_grace_time=300` on scheduler jobs |
| 7 | **Agent infinite tool loop** | Medium | Medium | PydanticAI `retries=2`; 120s overall timeout; per-agent rate limiting; cost awareness |
| 8 | **Ollama concurrency bottleneck** | Medium | Medium | `OLLAMA_NUM_PARALLEL=2` handles 2 concurrent requests; 5 agents will queue; monitor queue times; add request queuing in agent code if needed |
| 9 | **Context window overflow** | Medium | High | Sliding window truncation; periodic conversation summarization to private memory; explicit memory commit operations |
| 10 | **Channel SDK breaking changes** | Low | Medium | Pin dependency versions in `pyproject.toml`; wrap all platform SDKs behind `UnifiedMessage` abstraction |

---

## Dependency Map

```
Phase 1: One Agent Talks
    │
    ├── Docker Compose (PostgreSQL, Redis, NATS) ─────────┐
    ├── Database schema + RLS ────────────────────────────┤  Can be parallelized
    ├── Discord adapter ─────────────────────────────────┤
    ├── PydanticAI brain ────────────────────────────────┤
    ├── PillywigginAgent base class ─────────────────────┘
    │
    │  (sequential: need working agent before building on it)
    │
    ▼
Phase 2: Memory Works
    │
    │  (can partially overlap with Phase 1 completion)
    │  — memory/private.py can start once PostgreSQL is up
    │  — personality.py can be developed early
    │  — RLS tests need full connection pool
    │
    ▼
Phase 3: Skills System
    │
    │  (needs Phase 2 memory tools to exist)
    │  — skill registry, sandbox, builder are all new code
    │  — can develop sandbox independently of registry
    │
    ▼
Phase 4: Second Agent + Communication
    │
    │  (needs skill system for cross-agent skill discovery)
    │  — Slack adapter can be developed in parallel with NATS bus
    │  — APScheduler integration is independent of adapter work
    │
    ▼
Phase 5: Full Fleet
    │
    │  — remaining adapters can be developed in parallel
    │  — personality files are independent of code
    │  — end-to-end testing requires all adapters
    │
    ▼
Phase 6: Hardening
    │
    │  (mostly sequential after Phase 5)
    │  — rate limiting and logging are independent of each other
    │  — backups can start any time
    │  — runbook requires experience running the system
    │
    ▼
```

**Key parallelization opportunities**:
- Infrastructure (PostgreSQL, Redis, NATS) can be started with `docker compose up` simultaneously. Ollama runs externally.
- Channel adapters (once BaseAdapter is stable) can be developed in parallel by different developers
- Skill sandbox, registry, and builder are independent and can be developed in parallel
- APScheduler integration is independent of NATS bus work

**Strict sequential dependencies**:
- Phase 2 requires the Telegram agent from Phase 1 to be working
- RLS tests require Phase 1's PostgreSQL + schema setup
- Phase 3 skills need Phase 2 memory tools (`recall_private_memory`, `share_to_council`)
- Phase 4 cross-agent skill discovery needs Phase 3 skill registry + NATS announcements
- Phase 6 hardening requires Phase 5's full fleet running to test under real conditions

---

## File Reference

Key files from the project structure (overview-v2 §11) mapped to phases:

### Phase 1 files
| File | Purpose |
|------|---------|
| `pyproject.toml` | Project config, dependencies |
| `Dockerfile` | Multi-stage container build |
| `docker-compose.yaml` | All services: infra + agents |
| `env.example` | Environment variable template |
| `.gitignore` | Includes `.env` |
| `src/pillywiggins/__init__.py` | Package init |
| `src/pillywiggins/__main__.py` | CLI entrypoint: `--channel` arg |
| `src/pillywiggins/config.py` | Pydantic Settings from env vars |
| `src/pillywiggins/agents/brain.py` | PydanticAI agent brain |
| `src/pillywiggins/agents/deps.py` | AgentDeps dataclass |
| `src/pillywiggins/agents/personality.py` | YAML personality loader |
| `src/pillywiggins/agents/base.py` | PillywigginAgent with asyncio.Lock |
| `src/pillywiggins/messaging/unified.py` | UnifiedMessage, ChannelType |
| `src/pillywiggins/adapters/base.py` | BaseAdapter ABC |
| `src/pillywiggins/adapters/discord_adapter.py` | Discord channel adapter |
| `src/pillywiggins/health.py` | /healthz endpoint |
| `personalities/puck.yaml` (historically `discord.yaml`) | Puck personality config |
| `skills/registry.json` | Empty skills registry |
| `scripts/setup-db.sh` | PostgreSQL schema + RLS setup |
| `scripts/pull-models.sh` | Ollama model pulls |
| `tests/conftest.py` | Test fixtures |
| `tests/test_brain.py` | PydanticAI brain tests |
| `tests/test_adapters.py` | Discord adapter tests |

### Phase 2 files
| File | Purpose |
|------|---------|
| `src/pillywiggins/memory/private.py` | Private memory (pgvector + RLS) |
| `src/pillywiggins/memory/cache.py` | Redis conversation cache |
| `src/pillywiggins/memory/embeddings.py` | Ollama embedding helper |
| `src/pillywiggins/memory/council.py` | Council memory operations |
| `tests/test_memory_isolation.py` | RLS isolation tests |
| `tests/test_council.py` | Council write/search tests |

### Phase 3 files
| File | Purpose |
|------|---------|
| `src/pillywiggins/skills/registry.py` | SkillRegistry class (load, register, watch) |
| `src/pillywiggins/skills/builder.py` | Skill building/testing flow (draft→test→review→deploy) |
| `src/pillywiggins/skills/sandbox.py` | Sandboxed subprocess execution |
| `src/pillywiggins/skills/templates.py` | Skill file template for LLM |
| `tests/test_skill_sandbox.py` | Sandbox timeout, restricted env |
| `tests/test_skill_registry.py` | Registry load, register, watch |
| `skills/roll_dice.py` | Example skill (seeding) |
| `skills/check_website.py` | Example skill (seeding) |
| `skills/count_words.py` | Example skill (seeding) |

### Phase 4 files
| File | Purpose |
|------|---------|
| `src/pillywiggins/adapters/slack_adapter.py` | Slack channel adapter |
| `src/pillywiggins/messaging/nats_bus.py` | NATS pub/sub wrapper |
| `src/pillywiggins/scheduling/scheduler.py` | APScheduler + Redis per-agent |
| `personalities/slack.yaml` | Ariel personality config |

### Phase 5 files
| File | Purpose |
|------|---------|
| `src/pillywiggins/adapters/telegram_adapter.py` | Telegram channel adapter |
| `src/pillywiggins/adapters/matrix_adapter.py` | Matrix channel adapter |
| `src/pillywiggins/adapters/email_adapter.py` | Email channel adapter |
| `personalities/telegram.yaml` | Robin personality config |
| `personalities/matrix.yaml` | Cobweb personality config |
| `personalities/email.yaml` | Moth personality config |

### Phase 6 files
| File | Purpose |
|------|---------|
| `scripts/backup-db.sh` | PostgreSQL backup script |
| Various rate limiting, logging enhancements in existing files |

---

## Quick Reference: Overview-v2 Section Map

| Section | Topic | Key Decision |
|---------|-------|-------------|
| §1 | Architecture overview | Docker Compose, one Python process per agent, direct connections to PostgreSQL/Redis/NATS |
| §2 | Agent runtime | `PillywigginAgent` with `asyncio.Lock`, direct `asyncpg`, direct `nats-py`, `SkillRegistry` |
| §3 | Skills system | Python files in shared volume, draft→test→review→deploy flow, `SkillRegistry`, sandbox subprocess |
| §4 | Per-agent cron | APScheduler + Redis job store per agent, survives restarts, loaded from personality YAML |
| §5 | Channel adapters | `UnifiedMessage`, one adapter per platform, `BaseAdapter` ABC |
| §6 | Memory architecture | 3-tier: Redis cache, PostgreSQL+RLS private, PostgreSQL council |
| §7 | Inter-agent comms | Direct `nats-py`, `council.broadcast` and `council.direct.{agent_id}` topics |
| §8 | Personality system | YAML files, edit + `docker compose restart`, no rebuild |
| §9 | Security | RLS, sandbox subprocess, `.env` for secrets, rate limiting, council write validation |
| §10 | Observability | Start with structured JSON logging, `/healthz` endpoint; Prometheus/Grafana deferred |
| §11 | Project structure | Source under `src/pillywiggins/`, personalities/ and skills/ at root |
| §12 | Implementation roadmap | 6 phases: One Agent → Memory → Skills → Second Agent → Fleet → Hardening |
| §13 | Open questions | Model quality, embedding colocation, council conflicts, email threading, skill deps |
| §14 | Risk register | GPU OOM, 8B quality, RLS, skill sandbox, single machine failure |