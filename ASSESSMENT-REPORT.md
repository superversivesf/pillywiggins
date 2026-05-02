# ASSESSMENT-REPORT.md — Pillywiggins Project Synthesis

**Date:** 2026-04-27  
**Synthesized from:** `ASSESSMENT-INVENTORY.md`, `ASSESSMENT-DEPLOYABILITY.md`, `ASSESSMENT-BEHAVIORS.md`, `docs/pillywiggins-overview-v2.md`  
**Auditor:** swarm-worker-synthesizer

---

## 1. Executive Summary

Pillywiggins is a remarkably complete implementation of its canonical Docker-Compose-based council-of-agents architecture. Thirty-one of thirty-four expected source modules are fully implemented, and the functional count is higher still when counting behaviors. The core runtime — `PillywigginAgent` with `asyncio.Lock`, PydanticAI brain, PostgreSQL private memory with RLS, NATS JetStream council bus, APScheduler + Redis persistence, and a collaborative skill builder — is production-grade code. The onboarding wizard generates valid, runnable configurations, but only for Telegram.

However, the project sits at a "mostly complete but not yet safely deployable" inflection point. Three channel adapters are entirely missing (Slack, Matrix, Email), the `.example` templates have drifted away from the onboard wizard's live output, Docker Compose lacks healthchecks and restart policies on half its services, and first-time deployment carries three CRITICAL blockers that will cause hard failures before the first message can be processed. None of these are deep architectural problems; they are configuration and finishing gaps. The codebase itself is sound.

---

## 2. What's Ready (Functional NOW)

| Component | Status | Key Evidence |
|-----------|--------|------------|
| **CLI Entrypoint** (`__main__.py`) | ✅ Works | `--channel`, `--agent-id`, `onboard` subcommand parsed and executed correctly. |
| **Discord Adapter** | ✅ Works | Full WebSocket gateway, `UnifiedMessage` normalization, commands (`!help`, `!status`, `!models`, `!skills`, `!compact`, `!reset`), authorization, typing indicator, graceful shutdown. |
| **Telegram Adapter** | ✅ Works | Full polling bot, same command set as Discord, group/private handling, authorization, typing action, graceful shutdown. |
| **PillywigginAgent (`base.py`)** | ✅ Works | `asyncio.Lock` turn-based concurrency, full lifecycle (`start`/`shutdown`), model switching, history compaction/clearing, status reporting. |
| **PydanticAI Brain (`brain.py`)** | ✅ Works | `Agent` factory with `AgentDeps` injection, system prompt from personality, 12+ built-in tools + dynamic skill tools, Ollama + OpenAI provider setup. |
| **AgentDeps (`deps.py`)** | ✅ Works | Injected into every tool call with agent_id, channel, personality, memory, registry, council, NATS, scheduler, conversation key. |
| **Personality Loader (`personality.py`)** | ✅ Works | Dual-schema YAML support, timezone, `bot_chat_limit`, schedule parsing. 33 personality files present. |
| **Private Memory (`memory/private.py`)** | ✅ Works | Asyncpg pool + `SET app.agent_id` RLS enforcement, pgvector cosine similarity search, save/delete. |
| **Council Memory (`memory/council.py`)** | ✅ Works | Write validation (length whitelist, tags, rate limit 10/hr, dedup at 0.95 cosine), search with tag filtering, CRUD. |
| **Conversation Cache (`memory/cache.py`)** | ✅ Works | Redis-backed with `ModelMessagesTypeAdapter`, 30-min TTL. |
| **Conversation Store (`memory/store.py`)** | ✅ Works | PostgreSQL JSONB upsert with RLS, used as fallback after Redis. |
| **Embeddings (`memory/embeddings.py`)** | ✅ Works | Retry/backoff, Ollama + OpenAI endpoints, in-memory SHA256 cache (1h TTL). |
| **NATS Bus (`messaging/nats_bus.py`)** | ✅ Works | JetStream `COUNCIL` stream, broadcast + direct pub/sub, durable queues, graceful drain. |
| **UnifiedMessage (`messaging/unified.py`)** | ✅ Works | `ChannelType` enum for all 5 channels, dataclass with metadata. |
| **Scheduling (`scheduling/scheduler.py`)** | ✅ Works | Per-agent `AsyncIOScheduler` + `RedisJobStore` (falls back to memory), YAML + JSON schedule loading, cron + interval triggers, `misfire_grace_time=300`, `replace_existing=True`. |
| **Skill Registry (`skills/registry.py`)** | ✅ Works | Loads `.py` from `skills/` dir, validates `SKILL_META` + `run()`, registers, writes disk + `registry.json`. |
| **Skill Builder (`skills/builder.py`)** | ✅ Works | Draft → test → review → deploy, AST validation, dangerous-pattern detection, user approval gate, NATS broadcast on deploy. |
| **Skill Sandbox (`skills/sandbox.py`)** | ✅ Works | Restricted subprocess, 30s timeout, filtered env (no secrets), stdout JSON parsing. |
| **Skill Templates (`skills/templates.py`)** | ✅ Works | Boilerplate generator, AST-level validation of required structures. |
| **URL Filter (`skills/url_filter.py`)** | ✅ Works | Blocks private/internal IP ranges against SSRF. |
| **Pre-built Skills** | ✅ Works | `web_search.py` (SearXNG), `check_website.py`, `count_words.py`, `roll_dice.py` |
| **Onboard Wizard (`onboard.py`)** | ✅ Works | Interactive agent creation, Telegram token validation, LLM polling, `.env` / `agents.yaml` / `docker-compose.yaml` generation, optional `docker compose up`. |
| **Health Server (`health.py`)** | ✅ Works | `/healthz` checks PostgreSQL, Redis, LLM (Ollama/OpenAI), NATS with URL normalization. |
| **Config Loader (`config.py`)** | ✅ Works | Pydantic `BaseSettings` covers DB, Redis, NATS, LLM, tokens, sandbox, agent config, timezone. |
| **DB Initialization** (`scripts/init-db.sql`, `setup-db.sh`) | ✅ Works | Schema + pgvector + RLS policies created on first run. |
| **Tests** | ✅ Works | ~40 test files across all modules. |

---

## 3. What's Missing / Incomplete

| ID | Gap | Severity | Notes |
|----|-----|----------|-------|
| G1 | **Slack adapter** (`slack_adapter.py`) | **CRITICAL** (Phase 4) | Only `ChannelType.SLACK` exists. Blocks multi-agent fleet verification. IMPLEMENTATION-PLAN §4.1, overview-v2 §5. |
| G2 | **Matrix adapter** (`matrix_adapter.py`) | **CRITICAL** (Phase 5) | Only `ChannelType.MATRIX` exists. Part of full 5-channel fleet. IMPLEMENTATION-PLAN §5.1. |
| G3 | **Email adapter** (`email_adapter.py`) | **CRITICAL** (Phase 5) | Only `ChannelType.EMAIL` exists. Part of full 5-channel fleet. IMPLEMENTATION-PLAN §5.1. |
| G4 | **Rate limiting** (10 LLM calls/min/agent) | **HIGH** | Not present in `brain.py` or `base.py`. Phase 6 hardening expectation. |
| G5 | **Structured JSON logging** | **HIGH** | `logging.basicConfig` in `__main__.py` uses plain text. Phase 6 hardening. |
| G6 | **PydanticAI timeout/retries** | **HIGH** | `Agent` in `brain.py` does not set `retries=2` or 120s overall timeout. Phase 6 hardening. |
| G7 | **Conversation summarization / periodic memory consolidation** | **MEDIUM** | `compact_history()` exists but periodic automatic consolidation is not scheduled. |
| G8 | **Automated backups** | **MEDIUM** | No `scripts/backup-db.sh`. Phase 6 hardening. |
| G9 | **Skill registry file watching (auto-reload)** | **MEDIUM** | No `watchdog`, `inotify`, or polling loop. Skills only reload on restart or NATS `skill_deployed`. |
| G10 | **Scheduler builtin `memory_review`** | **MEDIUM** | Logs only; no actual memory consolidation/pruning logic. |
| G11 | **Scheduler builtin `skill_reload`** | **MEDIUM** | Logs only; does not call `SkillRegistry.load_all()` to refresh filesystem changes. |
| G12 | **Scheduler builtin `custom`** | **LOW** | Generic placeholder; logs args but takes no real action. |
| G13 | **Docker healthchecks in generated compose** | **HIGH** | Missing on redis, nats, and agent services. `.example` has them; live file does not. |
| G14 | **Restart policies in generated compose** | **HIGH** | Missing on postgres, redis, nats, agents. `.example` has `unless-stopped`; live file does not. |

### Deviations from Canonical Architecture

| ID | Deviation | Severity | Canonical Expectation (overview-v2) | Current State |
|----|-----------|----------|--------------------------------------|---------------|
| D1 | **Ollama excluded from `docker-compose.yaml`** | **LOW** (documented) | overview-v2 §6 explicitly says Ollama is intentionally external. | Matches canon. Not a deviation, but a first-time user hazard. |
| D2 | **`.example` vs live compose drift** | **HIGH** | `.example` should be a minimal, safe template that the wizard copies. | `.example` advertises Discord (`puck-discord`) and extra healthchecks that the live file lacks. Divergence confuses manual setup. |
| D3 | **Onboard wizard hardcodes Telegram only** | **HIGH** | Wizard should support all channels or none. | Discord/Slack disabled in UI despite Discord adapter being fully functional. Wizard and CLI disagree on capabilities. |
| D4 | **`agents.yaml` bind-mount creates directory if missing** | **HIGH** | Config files should be safe to mount. | Docker Compose creates a directory at `./agents.yaml` if the file is absent, causing `IsADirectoryError` on app start. |
| D5 | **`registry.json` is empty `{"skills": []}`** | **MEDIUM** | `SkillRegistry` should discover skills from both filesystem and registry. | `load_all()` scans filesystem and populates in-memory registry, so runtime behavior is correct. However, the file being empty is misleading for operators and may confuse external tools. |

---

## 4. Deployability Blockers

Ranked by first-time user impact. All sourced from `ASSESSMENT-DEPLOYABILITY.md`.

### CRITICAL (will cause hard failure on first `docker compose up`)

| Rank | Blocker | Impact | Mitigation |
|------|---------|--------|------------|
| 1 | **Missing `.env` causes Docker Compose failure** | `env_file: .env` referenced in compose. If absent, compose errors out immediately. | Copy `env.example` → `.env` before any compose command. Wizard does this; manual skips fail. |
| 2 | **Missing `agents.yaml` causes directory mount** | Bind mount `./agents.yaml:/app/agents.yaml:ro` creates a directory if absent. App crashes with `IsADirectoryError`. | Copy `agents.yaml.example` → `agents.yaml` before compose. |
| 3 | **Ollama is external and unverified** | No Ollama service in compose. Default `LLM_BASE_URL` points to `host.docker.internal:11434`. If Ollama is not installed, running, and reachable with the chosen model pulled, the agent fails on first message. | Document prerequisite prominently. Optionally add `ollama` service to compose for single-machine deployments. Add healthcheck in wizard that verifies Ollama reachability before completing. |

### HIGH (will degrade reliability or confuse operators)

| Rank | Blocker | Impact | Mitigation |
|------|---------|--------|------------|
| 4 | **`.example` vs live compose drift** | `.example` has `puck-discord`, extra healthchecks, and `restart` policies that the live file lacks. Manual copiers get a different topology than wizard users. | Regenerate `docker-compose.yaml.example` to match the minimal live structure, or remove agent services from `.example` so it only shows infrastructure. |
| 5 | **Discord/Slack advertised but disabled** | `.env.example` defines `PUCK_DISCORD_TOKEN`. `.example` includes a `puck-discord` service. Onboard UI disables these channels. Users expect Discord support and do not get it. | Remove Discord placeholders from `.env.example` and `.example` compose until fully wired, OR enable Discord in wizard UI. |
| 6 | **Weak `depends_on` in live compose** | `redis` and `nats` use `condition: service_started` instead of `service_healthy`. Agents may start and crash-loop before redis/nats accept connections. | Add healthchecks to redis/nats in live compose and use `condition: service_healthy`. |

### MEDIUM (operational friction)

| Rank | Blocker | Impact | Mitigation |
|------|---------|--------|------------|
| 7 | **Onboard wizard appends without deduplication** | Running wizard twice with same agent ID appends duplicate service blocks unless user chooses "Replace". | Add pre-flight check in wizard to warn if ID already exists. |
| 8 | **No `restart` policy in live compose for infra** | Host reboot leaves PostgreSQL, Redis, NATS, and agent stopped. | Add `restart: unless-stopped` to all services in live compose. |
| 9 | **`personality_file` default mismatch risk** | `PERSONALITY_FILE=/config/puck.yaml` in `.env.example`, but wizard creates agents with arbitrary personality filenames. If the selected file does not exist under `./personalities/`, the container fails to start. | Add validation step in wizard that checks `PERSONALITIES_DIR` for the selected file before writing configs. |
| 10 | **Empty `registry.json` misleading** | `registry.json` is `{"skills": []}` despite `.py` files existing. Operators may think no skills are loaded. | Verify `SkillRegistry` behavior is documented; populate `registry.json` on first scan or remove its authority. |

### LOW (nice-to-have)

| Rank | Blocker | Impact | Mitigation |
|------|---------|--------|------------|
| 11 | **`uv.lock` absent** | Less reproducible builds; `uv` resolves dynamically. | Optionally generate and commit `uv.lock`. |
| 12 | **`extra_hosts` syntax compatibility** | `host.docker.internal:host-gateway` requires Docker Engine ≥ 20.10. | Document minimum Docker Engine version. |
| 13 | **SearXNG secret empty** | SearXNG may warn on empty `SEARXNG_SECRET`. | Provide generated default or document any non-empty string works. |

---

## 5. Testing Recommendations

When deploying, verify in this order:

### Smoke Tests (before exposing to users)

1. **Health endpoint** — `curl http://localhost:8080/healthz` should report Postgres, Redis, LLM, NATS all healthy.
2. **Telegram bot handshake** — Send `/start` or `!help`. Bot should reply with help text, typing indicator visible.
3. **Discord bot handshake** — Send `!help` in an authorized channel. Bot should reply.
4. **LLM generation** — Ask "What is 2+2?" Response should arrive within ~5–15 seconds (Ollama local).
5. **Memory persistence** — Restart agent container. Ask "What did I just ask you?" It should remember.
6. **Private memory isolation (if second agent running)** — Ask Agent A a secret. Ask Agent B "What did I tell Agent A?" Council memory may have an insight, but private memory should not leak.
7. **Skill execution** — Ask "Roll a d20". Bot should use `roll_dice` skill and return a number.
8. **Skill building flow** — Ask "Build a skill that reverses a string, tests "hello" → "olleh", and deploy it." Observe draft → test → review → approval → deploy → council broadcast. Then ask "Can you reverse 'pillywiggins'?" The new skill should be used.
9. **Scheduled task** — Add a task via `schedule_task` tool or personality YAML. Verify it fires at expected time and produces a message.
10. **Agent-to-agent direct message** — Use `send_message_to_agent` tool from one agent to another. Target should receive and process.
11. **Council broadcast** — Trigger `share_to_council` or observe skill deploy announcement. All agents' council memory searches should surface it.
12. **History compaction** — Use `!compact` command. Verify old messages summarized and new context preserved.
13. **Model switching** — Use `!models` then `!model qwen3.5:8b`. Verify new model used for subsequent messages.

### Regression Tests (after any change to adapters, brain, or compose)

- Run full `pytest` suite (~40 files).
- Verify `docker compose up -d --build` brings all services to healthy state without manual file copies.
- Verify onboarding wizard completes end-to-end and produces runnable configs.

### What NOT to test yet (stubbed / missing)

- Slack, Matrix, Email adapters.
- File-watching auto-reload of skills.
- Periodic automatic memory consolidation.
- Rate limiting under load (not implemented).

---

## 6. Next Steps

### Immediately (before inviting users)

| Priority | Action | Owner / Notes |
|----------|--------|---------------|
| P0 | **Fix CRITICAL deploy blockers** — ensure `.env` and `agents.yaml` are present before compose, or make compose resilient to their absence. | Onboard wizard already copies `.example` → real file. Ensure manual docs say the same. Consider adding a `setup.sh` script that does this automatically. |
| P0 | **Add Ollama prerequisite check to onboard wizard** — verify `OLLAMA_BASE_URL` is reachable and model is available before completing. Prevents silent post-onboard failure. | Wizard already polls models via `list_models()`; this can be reused as a health probe. |
| P1 | **Synchronize `docker-compose.yaml.example` with live generated file** — remove `puck-discord` from `.example`, or add it to wizard output. Decide: is `.example` a minimal infra template, or a full demo? | Recommendation: make `.example` minimal infra only; remove agent services. |
| P1 | **Add healthchecks and restart policies to all live compose services** — postgres already has healthcheck; add to redis, nats, searxng, and agent. Add `restart: unless-stopped` to all. | Straightforward compose YAML edit. |
| P1 | **Change `depends_on` conditions** from `service_started` to `service_healthy` for redis and nats. | Requires adding healthchecks first. |

### Short term (1–2 sprints)

| Priority | Action | Owner / Notes |
|----------|--------|---------------|
| P2 | **Implement Slack adapter** (`slack_adapter.py`) — `slack_bolt` Socket Mode, `UnifiedMessage` producer, same command set. | IMPLEMENTATION-PLAN §4.1. Enables multi-agent fleet. |
| P2 | **Implement Matrix adapter** (`matrix_adapter.py`) — `matrix-nio`, persistent sync. E2EE deferred. | IMPLEMENTATION-PLAN §5.1. |
| P2 | **Implement Email adapter** (`email_adapter.py`) — `aiosmtplib` + `imap-tools`, IMAP IDLE or 30s polling, 3-message context window. | IMPLEMENTATION-PLAN §5.1. |
| P2 | **Enable Discord in onboard wizard UI** — adapter already works via `--channel discord` CLI. Wizard disables it for no documented reason. | Simple UI removal of `disabled=True`. |
| P2 | **Add file-watching auto-reload to `SkillRegistry`** — `watchdog` or periodic polling loop; call `load_all()` on change. | Unblocks collaborative skill editing outside agent brain. |
| P3 | **Implement scheduler builtin handlers** — `memory_review` (prune/consolidate old private memories), `skill_reload` (call `SkillRegistry.load_all()`), `custom` (dispatch to skill or agent tool). | Phase 6 hardening. |
| P3 | **Add rate limiting** (10 LLM calls/min/agent) in `brain.py` or `base.py`. | Phase 6 hardening. |
| P3 | **Add PydanticAI retries + timeout** (`retries=2`, 120s overall). | Phase 6 hardening. |

### Medium term (backlog)

| Priority | Action | Owner / Notes |
|----------|--------|---------------|
| P4 | **Structured JSON logging** replace `logging.basicConfig` with structured format. | Observability / Phase 6. |
| P4 | **Periodic automatic memory consolidation** — schedule `compact_history()` or equivalent via scheduler. | Phase 6. |
| P4 | **Automated DB backup script** (`scripts/backup-db.sh`). | Phase 6. |
| P4 | **Add Ollama as optional compose service** — for single-machine deployments where GPU passthrough is already configured. Keep external as default. | Nice-to-have for single-node ease. |
| P5 | **Generate and commit `uv.lock`** — reproducible builds. | Developer experience. |
| P5 | **Populate `registry.json` on first scan** — align on-disk registry with in-memory state to avoid operator confusion. | Low effort, high clarity. |

---

## 7. Appendix: What to Ask the Agents

Below are sample prompts that exercise each major functional behavior. Use these after deployment to verify the system is alive end-to-end.

### Adapter / Basics
- `!help` — Should print command list.
- `!status` — Should show agent ID, channel, model, conversation length.
- `!models` — Should list available Ollama / OpenAI models.

### Memory
- "Remember that my favorite color is teal." (should save to private memory)
- "What is my favorite color?" (should recall from private memory)
- "Tell the council that the project deadline moved to Friday." (should write to council memory + NATS broadcast)

### Council Memory
- "Search the council memory for anything about deadlines." (should use `query_council_memory`)

### Skills
- "Roll a d20." (should invoke `roll_dice` skill)
- "Search the web for the weather in London." (should invoke `web_search` skill)
- "Count the words in this sentence: the quick brown fox jumps over the lazy dog." (should invoke `count_words` skill)

### Skill Building
- "Build a skill called `reverse_string` that takes a string and returns its reverse. Test it with 'hello' → 'olleh'. Show me the code and test results, then deploy it if tests pass."
- After deployment: "Can you reverse 'Pillywiggins' using the new skill?"

### Scheduling
- "Schedule a daily reminder at 9am to say 'Good morning!'" (should use `schedule_task` with cron)
- "List my scheduled tasks." (should use `list_scheduled_tasks`)
- "Remove the daily reminder." (should use `unschedule_task`)

### Agent-to-Agent
- "Send a message to the agent puck-discord saying 'Hello from Telegram!'" (should use `send_message_to_agent`)

### Utilities
- "What time is it?" (should use `get_current_time` with personality timezone)
- "How long is this conversation?" (should use `get_conversation_info`)

### Model Switching
- `!model qwen3.5:8b` — Should switch LLM model dynamically.

### History Management
- `!compact` — Should summarize old messages and truncate history.
- `!reset` — Should clear conversation history and confirm.

---

*End of Assessment Report.*
