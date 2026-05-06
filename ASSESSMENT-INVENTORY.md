# Pillywiggins Codebase Assessment Inventory

**Generated:** 2026-04-27  
**Scope:** `src/pillywiggins/` and supporting project files  
**Cross-references:** `docs/IMPLEMENTATION-PLAN.md` (phases 1–6), `docs/pillywiggins-overview-v2.md` (§11 Project Structure Target)

---

## Summary

| Category | Count |
|----------|-------|
| **COMPLETE** | 34 |
| **PARTIAL / STUB** | 0 |
| **MISSING** | 0 |
| **Total expected modules** | 34 |

All 34 expected source modules are fully implemented.

---

## Root-Level Source Files

### `src/pillywiggins/__init__.py`
- **Status:** COMPLETE
- **Purpose:** Package init. Declares `__version__ = "0.1.0"`.
- **Notes:** Minimal, standard Python package marker.

### `src/pillywiggins/__main__.py`
- **Status:** COMPLETE
- **Purpose:** CLI entrypoint. Parses `--channel` and `--agent-id`, supports `onboard` subcommand, dynamically loads adapter classes, instantiates `PillywigginAgent`, starts health server, and runs the event loop.
- **Cross-ref:** IMPLEMENTATION-PLAN §1.5, overview-v2 §11

### `src/pillywiggins/config.py`
- **Status:** COMPLETE
- **Purpose:** Pydantic `BaseSettings` class loading all environment variables (DB, Redis, NATS, LLM, tokens, sandbox settings, agent config path, timezone).
- **Cross-ref:** IMPLEMENTATION-PLAN §1.5

### `src/pillywiggins/health.py`
- **Status:** COMPLETE
- **Purpose:** `/healthz` HTTP endpoint (aiohttp) checking PostgreSQL, Redis, LLM (Ollama/OpenAI), and NATS connectivity. Includes URL normalization for Ollama `/v1` suffix.
- **Cross-ref:** IMPLEMENTATION-PLAN §1.5, §6.2

### `src/pillywiggins/onboard.py`
- **Status:** COMPLETE
- **Purpose:** Interactive onboarding wizard (`pillywiggins onboard`). Discovers personalities, validates Telegram tokens, polls LLM models, writes `agents.yaml`, `docker-compose.yaml`, and `.env`. Supports add/remove/reconfigure/start flows. Only Telegram is exposed in the UI (Discord/Slack choices are disabled); the core logic is channel-agnostic.
- **Notes:** Not explicitly in §11 structure target, but referenced in onboard flow. UI currently limits channel selection to Telegram for ease of first setup.

### `src/pillywiggins/agents_config.py`
- **Status:** COMPLETE
- **Purpose:** `AgentConfig` dataclass and parser for `agents.yaml`. Expands `${ENV_VAR}` references and applies per-agent environment overrides.
- **Notes:** Not explicitly in §11 structure target, but essential for multi-agent deployment.

---

## `agents/` Package

### `src/pillywiggins/agents/__init__.py`
- **Status:** COMPLETE
- **Purpose:** Empty package init.

### `src/pillywiggins/agents/base.py`
- **Status:** COMPLETE
- **Purpose:** `PillywigginAgent` — the core runtime class. Holds `asyncio.Lock`, manages brain, private memory, council memory, NATS bus, scheduler, conversation history (Redis + PostgreSQL), history compaction, status reporting, and message processing pipeline.
- **Cross-ref:** IMPLEMENTATION-PLAN §1.5, overview-v2 §2, §6

### `src/pillywiggins/agents/brain.py`
- **Status:** COMPLETE
- **Purpose:** PydanticAI `Agent` factory (`create_brain`). Registers all built-in tools: `recall_private_memory`, `save_to_private_memory`, `query_council_memory`, `share_to_council`, `build_skill`, `test_skill_code`, `review_skill_code`, `deploy_skill_code`, `schedule_task`, `unschedule_task`, `list_scheduled_tasks`, `send_message_to_agent`, `get_current_time`, `get_conversation_info`. Dynamically registers skill tools from `SkillRegistry`. Handles Ollama and OpenAI provider setup.
- **Cross-ref:** IMPLEMENTATION-PLAN §1.5, §2.1, §2.4, §3.2, §3.4

### `src/pillywiggins/agents/deps.py`
- **Status:** COMPLETE
- **Purpose:** `AgentDeps` dataclass injected into every tool call. Carries `agent_id`, `channel`, `personality`, `private_memory`, `skill_registry`, `council_memory`, `nats_bus`, `scheduler`, `conversation_key`, and `conversation_info` callable.
- **Cross-ref:** IMPLEMENTATION-PLAN §1.5, overview-v2 §2

### `src/pillywiggins/agents/personality.py`
- **Status:** COMPLETE
- **Purpose:** `Personality` dataclass and `load_personality()` YAML loader. Supports both old schema (`description`, `system_prompt`, `traits`) and new schema (`archetype`, `tone`, `style`, `response_length`, `additional_instructions`). Assembles system prompt dynamically.
- **Cross-ref:** IMPLEMENTATION-PLAN §1.5, §2.3, overview-v2 §8

---

## `adapters/` Package

### `src/pillywiggins/adapters/__init__.py`
- **Status:** COMPLETE
- **Purpose:** Empty package init.

### `src/pillywiggins/adapters/base.py`
- **Status:** COMPLETE
- **Purpose:** `BaseAdapter` ABC defining `connect()`, `listen()`, `send()`, `normalize()`.
- **Cross-ref:** IMPLEMENTATION-PLAN §1.5, overview-v2 §5

### `src/pillywiggins/adapters/discord_adapter.py`
- **Status:** COMPLETE
- **Purpose:** Discord adapter using `discord.py`. Gateway WebSocket connection, message normalization to `UnifiedMessage`, command handlers (`!help`, `!status`, `!models`, `!model`, `!skills`, `!compact`, `!reset`), authorized user filtering, bot-chat limit enforcement, typing indicator.
- **Cross-ref:** IMPLEMENTATION-PLAN §1.5, overview-v2 §5

### `src/pillywiggins/adapters/telegram_adapter.py`
- **Status:** COMPLETE
- **Purpose:** Telegram adapter using `python-telegram-bot`. Polling mode, message normalization, same command set as Discord, group vs. private chat handling, authorized user filtering, bot-chat limit enforcement, typing action.
- **Cross-ref:** IMPLEMENTATION-PLAN §5.1, overview-v2 §5

### `src/pillywiggins/adapters/models.py`
- **Status:** COMPLETE
- **Purpose:** `ModelInfo` dataclass and `list_models()` helper. Polls Ollama `/api/tags` or OpenAI-compatible `/models` endpoints.
- **Notes:** Used by `__main__.py`, Discord adapter, Telegram adapter, and onboard wizard.

### `src/pillywiggins/adapters/slack_adapter.py`
- **Status:** COMPLETE
- **Purpose:** Slack adapter using `slack_bolt` in Socket Mode (no public URL needed). Normalizes Slack events to `UnifiedMessage`, sends responses via Slack API.
- **Cross-ref:** IMPLEMENTATION-PLAN §4.1, overview-v2 §5.
- **Note:** Not yet wired in `__main__.py` default mapping; accessible via `--channel slack` if token is configured.

### `src/pillywiggins/adapters/matrix_adapter.py`
- **Status:** COMPLETE
- **Purpose:** Matrix adapter using `matrix-nio`. Persistent sync connection. E2EE deferred.
- **Cross-ref:** IMPLEMENTATION-PLAN §5.1, overview-v2 §5.
- **Note:** Not yet wired in `__main__.py` default mapping; accessible via `--channel matrix` if credentials are configured.

### `src/pillywiggins/adapters/email_adapter.py`
- **Status:** COMPLETE
- **Purpose:** Email adapter using `aiosmtplib` + `imap-tools`. IMAP IDLE for real-time push, fallback to 30s polling. 3-message context window for threads.
- **Cross-ref:** IMPLEMENTATION-PLAN §5.1, overview-v2 §5.
- **Note:** Not yet wired in `__main__.py` default mapping; accessible via `--channel email` if credentials are configured.

---

## `memory/` Package

### `src/pillywiggins/memory/__init__.py`
- **Status:** COMPLETE
- **Purpose:** Empty package init.

### `src/pillywiggins/memory/private.py`
- **Status:** COMPLETE
- **Purpose:** `PrivateMemory` class. Asyncpg connection pool with `SET app.agent_id` on init for RLS enforcement. `save()`, `search()` via pgvector cosine distance, `delete()`, `close()`.
- **Cross-ref:** IMPLEMENTATION-PLAN §2.1, overview-v2 §6, §9

### `src/pillywiggins/memory/council.py`
- **Status:** COMPLETE
- **Purpose:** `CouncilMemory` class. Write validation: max 2000 chars, tag whitelist (`VALID_MESSAGE_TYPES`, `TAG_WHITELIST`), rate limit (10/hour/agent), dedup check (cosine similarity > 0.95). `search()` with optional tag filtering. `delete_entry()`, `get_entry()`, `list_entries()`.
- **Cross-ref:** IMPLEMENTATION-PLAN §2.4, overview-v2 §9

### `src/pillywiggins/memory/cache.py`
- **Status:** COMPLETE
- **Purpose:** `ConversationCache` using Redis. Serializes/deserializes `ModelMessage` lists with `ModelMessagesTypeAdapter`. TTL = 1800s. Keys: `conversation:{agent_id}(:{conversation_key})`.
- **Cross-ref:** IMPLEMENTATION-PLAN §2.2, overview-v2 §6

### `src/pillywiggins/memory/embeddings.py`
- **Status:** COMPLETE
- **Purpose:** `embed()` and `embed_texts()` with retry/backoff (max 3 retries, exponential delay), in-memory SHA256 cache (1h TTL). Supports Ollama `/api/embed` and OpenAI-compatible `/embeddings`.
- **Cross-ref:** IMPLEMENTATION-PLAN §2.1, overview-v2 §6

### `src/pillywiggins/memory/store.py`
- **Status:** COMPLETE
- **Purpose:** `ConversationStore` — durable PostgreSQL persistence of conversation history with RLS (`SET app.agent_id`). Upserts into `conversation_cache` table with JSONB messages. `save()`, `load()`, `close()`.
- **Notes:** Not explicitly in §11 target but architecturally required for restart recovery. Used by `PillywigginAgent` as fallback after Redis cache.

---

## `messaging/` Package

### `src/pillywiggins/messaging/__init__.py`
- **Status:** COMPLETE
- **Purpose:** Re-exports `NatsBus`, `UnifiedMessage`, `ChannelType`, and NATS subject constants.

### `src/pillywiggins/messaging/unified.py`
- **Status:** COMPLETE
- **Purpose:** `ChannelType` enum (telegram, discord, slack, matrix, email) and `UnifiedMessage` dataclass (channel, user_id, content, conversation_key, timestamp, metadata).
- **Cross-ref:** IMPLEMENTATION-PLAN §1.5, overview-v2 §5

### `src/pillywiggins/messaging/nats_bus.py`
- **Status:** COMPLETE
- **Purpose:** `NatsBus` wrapper around `nats-py` JetStream. Connects to NATS, creates `COUNCIL` stream, publishes to `council.broadcast` and `council.direct.{agent_id}`, subscribes with durable queue names, graceful close with drain.
- **Cross-ref:** IMPLEMENTATION-PLAN §4.2, overview-v2 §7

---

## `scheduling/` Package

### `src/pillywiggins/scheduling/__init__.py`
- **Status:** COMPLETE
- **Purpose:** Empty package init.

### `src/pillywiggins/scheduling/scheduler.py`
- **Status:** COMPLETE
- **Purpose:** `AgentScheduler` wrapping `APScheduler` `AsyncIOScheduler`. Uses `RedisJobStore` with fallback to `MemoryJobStore`. Loads YAML schedules from personality + JSON schedules from `/app/skills/{agent_id}_schedules.json`. Supports cron and interval triggers. `misfire_grace_time=300`, `replace_existing=True`. Built-in handlers: heartbeat, memory_review, skill_reload, custom. Programmatic `add_job()`, `remove_job()`, `list_jobs()`, `reload()`.
- **Cross-ref:** IMPLEMENTATION-PLAN §4.3, overview-v2 §4

---

## `skills/` Package

### `src/pillywiggins/skills/__init__.py`
- **Status:** COMPLETE
- **Purpose:** Empty package init.

### `src/pillywiggins/skills/registry.py`
- **Status:** COMPLETE
- **Purpose:** `SkillRegistry` class. `load_all()` imports `.py` files from `skills/` directory, validates `SKILL_META` and `run()` presence. `register_skill()` writes code to disk and updates `registry.json`. `list_skills()`, `get_skill()`, `has_skill()`. Permission parsing supports legacy `network_access` and new `permissions` dict.
- **Cross-ref:** IMPLEMENTATION-PLAN §3.2, overview-v2 §3

### `src/pillywiggins/skills/builder.py`
- **Status:** COMPLETE
- **Purpose:** Skill builder workflow: `draft_skill()` → `test_skill()` → `review_skill()` → `deploy_skill()`. `SkillDraft` dataclass with status enum (`DRAFT`, `TESTED`, `REVIEWED`, `APPROVED`, `REJECTED`). Code validation via AST parsing, dangerous-pattern detection. Sandbox testing with pass/fail reporting. User approval gate on deploy. NATS broadcast on successful deploy.
- **Cross-ref:** IMPLEMENTATION-PLAN §3.4, overview-v2 §3

### `src/pillywiggins/skills/sandbox.py`
- **Status:** COMPLETE
- **Purpose:** `run_sandboxed()` executes skill code in a restricted subprocess. 30s hard timeout, working dir `/tmp`, filtered environment variables (no secrets/tokens), stdout JSON parsing. `SandboxResult` dataclass.
- **Cross-ref:** IMPLEMENTATION-PLAN §3.3, overview-v2 §3, §9

### `src/pillywiggins/skills/templates.py`
- **Status:** COMPLETE
- **Purpose:** `generate_skill_boilerplate()` produces standard skill scaffold. `validate_skill_code()` checks AST-valid, `SKILL_META` present, `async def run(**kwargs)`, try/except block, `logging.getLogger` call.
- **Cross-ref:** IMPLEMENTATION-PLAN §3.1, overview-v2 §3

### `src/pillywiggins/skills/url_filter.py`
- **Status:** COMPLETE
- **Purpose:** `is_safe_url()` blocks private/internal IP ranges (10/8, 172.16/12, 192.168/16, 127/8, link-local, etc.) to prevent SSRF in skills.
- **Notes:** Not explicitly in §11 target but part of sandbox security.

---

## Supporting Project Files (Non-`src/`)

| File / Directory | Status | Notes |
|-----------------|--------|-------|
| `pyproject.toml` | COMPLETE | Dependencies, scripts, hatch build, pytest config, ruff |
| `Dockerfile` | COMPLETE | Multi-stage build with `uv`, runtime `python:3.12-slim`, pre-installed skill deps |
| `docker-compose.yaml.example` | COMPLETE | Template with postgres, redis, nats, searxng |
| `docker-compose.yaml` | COMPLETE | Generated by onboard wizard |
| `env.example` | COMPLETE | Environment variable template |
| `.env` | COMPLETE | Generated by onboard (gitignored) |
| `agents.yaml.example` | COMPLETE | Template for multi-agent config |
| `agents.yaml` | COMPLETE | Generated by onboard |
| `personalities/*.yaml` (33 files) | COMPLETE | Full set of personality YAMLs including `puck.yaml` and `discord.yaml` |
| `skills/*.py` (4 files) | COMPLETE | `roll_dice.py`, `check_website.py`, `count_words.py`, `web_search.py` |
| `skills/registry.json` | COMPLETE | Registry index |
| `scripts/setup-db.sh` | COMPLETE | PostgreSQL schema + pgvector + RLS setup |
| `scripts/init-db.sql` | COMPLETE | SQL executed by setup-db.sh |
| `scripts/pull-models.sh` | COMPLETE | Ollama model pull script |
| `tests/` (~40 files) | COMPLETE | Extensive test coverage across all modules |

---

## Missing Modules Detail

> **No modules are missing.** All 34 expected source modules are present and complete. The previously flagged adapter files (`slack_adapter.py`, `matrix_adapter.py`, `email_adapter.py`) were implemented after the initial assessment date.

---

## Feature Gaps Within Complete Modules

The following are architectural expectations from Phase 6 (Hardening). Items marked ~~strikethrough~~ were implemented after the initial assessment date and are now present in the codebase.

1. ~~​**Rate limiting** (10 LLM calls/min/agent) — Implemented in `base.py` via `_check_rate_limit()` with tests in `tests/test_rate_limit.py`.~~
2. ~~​**Structured JSON logging** — Implemented in `src/pillywiggins/logging_utils.py` via `AgentLogger` with per-step timing.~~
3. ~~​**PydanticAI timeout/retries** — `brain.py` sets `retries=2` and `tool_timeout=120` on `Agent` creation.~~
4. **Conversation summarization / memory consolidation** — `compact_history()` exists but periodic automatic consolidation is not scheduled.
5. ~~​**Automated backups** — `scripts/backup-db.sh` exists with 14-day rotation.~~
6. ~~​**Docker healthchecks in compose** — Generated `docker-compose.yaml` by onboard wizard includes healthchecks and restart policies.~~
7. ~~​**Restart policies** — Generated `docker-compose.yaml` by onboard wizard includes `restart: unless-stopped`.~~

These remaining gaps (conversation summarization / periodic memory consolidation) should be addressed when work resumes on Phase 6.
