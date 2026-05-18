# Pillywiggins Gap Analysis Report

**Date:** 2026-04-23
**Scope:** Full codebase inventory against `pillywiggins-overview-v2.md` and `IMPLEMENTATION-PLAN.md`
**Method:** 7 parallel assessment workers covering Core Runtime, Memory, Skills, Messaging, Adapters, Scheduling, and Infrastructure

> **Note:** This document was written in April 2026. Several gaps identified have since been resolved as of May 2026:
> - **Puck defaults removed** — config, Dockerfile, and `__main__.py` no longer hard-code Puck/Telegram; `agents.yaml` is the single source of truth
> - **`agents.yaml` added to `.gitignore`** — prevents accidental commits of local agent config
> - **Scheduler fixed** — switched to MemoryJobStore, eliminated `_thread.lock` pickle crash
> - **Skill building fixed** — `build_and_publish_skill` single-call pipeline replaces 4-step multi-turn pattern
> - **Dockerfile hardened** — non-root `USER appuser` and `HEALTHCHECK` added
> - **Security hardened** — prompt sanitizer NFKC normalization, CRLF injection fixes in email adapter, token masking in Slack adapter, output sanitization in tools, DB credential validators

---

## Executive Summary

Pillywiggins is approximately **55-60% implemented** against the Phase 1-5 target architecture. The core runtime exists (agent base class, brain, Telegram adapter, health endpoint, conversation cache, scheduler skeleton, skill registry skeleton), but several critical blockers prevent the system from reaching even a single working Discord agent. The biggest gaps are:

1. **Only Telegram is wired** — Discord, Slack, Matrix, and Email adapters are entirely missing from `__main__.py` and `docker-compose.yaml`
2. **Database schema is underspecified** — `init-db.sql` lacks 9 columns required by the spec (memory_type, importance, access_count, etc.)
3. **Private memory has RLS and type-safety gaps** — SQL injection risk in `SET app.agent_id`, missing `::vector` cast, no connection-checkout context manager
4. **Personality YAML diverges from spec** — code uses `description`/`system_prompt`/`traits`; spec calls for `archetype`/`tone`/`style`/`response_length`
5. **Skills system integration layer missing** — `registry.json` is empty despite 4 skills on disk, `builder.py` has no NATS council announcement, no `watch_for_changes()`, no `templates.py`
6. **NATS transport is write-only** — agents create `NatsBus` but never subscribe to broadcast or direct messages; `_parse_payload` discards sender/timestamp metadata
7. **Scheduler field mismatch** — personality YAML uses `cron_expr` but scheduler checks for `cron`; `scheduling:` nested dict vs `schedules:` flat list; no synthetic `UnifiedMessage` for cron actions
8. **Infrastructure gaps in docker-compose** — no Ollama service, no GPU passthrough, no healthchecks on agent services, no restart policies, missing channel SDKs in `pyproject.toml`

Notably, the *low-level machinery* in most modules is solid. The gaps are primarily in **integration wiring** (connecting A to B), **spec compliance** (schema alignment), and **missing adapters** (Discord/Slack/Matrix/Email).

---

## File-by-File Status Table

| File | Phase | Status | Key Gap |
|------|-------|--------|---------|
| `src/pillywiggins/__main__.py` | 1 | Partial | Accepts `--channel discord/slack/matrix/email` but raises `ValueError` at runtime for all non-telegram |
| `src/pillywiggins/config.py` | 1 | Partial | Loads from env/Pydantic Settings; missing some spec fields (model name, embedding model defaults) |
| `src/pillywiggins/agents/base.py` | 1 | Partial | Creates `NatsBus` but never subscribes to broadcast/direct; `_builtin_send_message_handler` hard-codes `channel="telegram"` |
| `src/pillywiggins/agents/brain.py` | 1-2 | Partial | PydanticAI brain works; missing `deploy_skill_code()` council broadcast; skill tools wired but builder tools not in registry yet |
| `src/pillywiggins/agents/deps.py` | 1-2 | Divergent | Uses `Any` fields instead of typed `asyncpg.Pool` and `Redis`; spec calls for `db`, `redis`, `history`, `private_context`, `council_context` |
| `src/pillywiggins/agents/personality.py` | 2 | Divergent | Expects `description`, `system_prompt`, `traits`; spec expects `archetype`, `tone`, `style`, `response_length` |
| `src/pillywiggins/health.py` | 1 | Partial | LLM URL bug (`/api/tags` appended to `/v1` base URL); missing NATS connectivity check |
| `src/pillywiggins/adapters/base.py` | 1 | Divergent | `send()` signature mismatches spec (`conversation_key`/`text` vs `channel_id`/`content`/`metadata`); `normalize` (US) vs spec `normalise` (UK) |
| `src/pillywiggins/adapters/telegram_adapter.py` | 1 | Partial | Polling only; webhook TODO; no channel-specific personality (`personalities/telegram.yaml`) |
| `src/pillywiggins/adapters/discord_adapter.py` | 1 | **MISSING** | Blocks Phase 1 — spec requires this as the first adapter |
| `src/pillywiggins/adapters/slack_adapter.py` | 4 | **MISSING** | Blocks Phase 4 |
| `src/pillywiggins/adapters/matrix_adapter.py` | 5 | **MISSING** | Blocks Phase 5 |
| `src/pillywiggins/adapters/email_adapter.py` | 5 | **MISSING** | Blocks Phase 5 |
| `src/pillywiggins/memory/private.py` | 2 | Partial | `save()` missing `::vector` cast (`str(embedding)`); RLS `SET` uses f-string (SQL injection); `SET` on pool init not checkout; missing spec columns |
| `src/pillywiggins/memory/council.py` | 2 | Near-complete | Exceeds spec with extra CRUD; no major gaps |
| `src/pillywiggins/memory/cache.py` | 2 | Partial | Redis cache works; conversation store integration exists |
| `src/pillywiggins/memory/embeddings.py` | 2 | Partial | Calls Ollama `/api/embed`; no retry logic or embedding cache for Ollama unavailability |
| `src/pillywiggins/memory/store.py` | 2 | Near-complete | Conversation persistence to PostgreSQL works |
| `src/pillywiggins/skills/registry.py` | 3 | Partial | Reads filesystem, not `registry.json` as source of truth; missing `watch_for_changes()`; missing `Skill.as_tool()` for PydanticAI |
| `src/pillywiggins/skills/builder.py` | 3 | Near-complete | Core builder flow exists; missing NATS council announcement on deploy; not wired as brain tools yet |
| `src/pillywiggins/skills/sandbox.py` | 3 | Near-complete | Subprocess sandbox with timeout works; missing comprehensive tests |
| `src/pillywiggins/skills/templates.py` | 3 | **MISSING** | LLM skill-generation template |
| `src/pillywiggins/messaging/nats_bus.py` | 4 | Partial | Stream named `COUNCIL` not `pillywiggins` per spec; `_parse_payload` discards `from` and `timestamp`; no subscription handling in base.py |
| `src/pillywiggins/messaging/unified.py` | 1-4 | Partial | `UnifiedMessage` model exists; limited fields |
| `src/pillywiggins/messaging/__init__.py` | 4 | **EMPTY** | No exports; should expose `UnifiedMessage`, `NatsBus`, etc. |
| `src/pillywiggins/scheduling/scheduler.py` | 4 | Partial | RedisJobStore lacks per-agent `jobs_key`; personality YAML uses `cron_expr` but code checks `cron`; `target_channel` ignored; no synthetic `UnifiedMessage` |
| `docker-compose.yaml` | 1-5 | Partial | Ollama service missing; only `puck` (Telegram) agent; no GPU passthrough; no restart policies; no healthchecks on agents; `searxng` present but not in spec |
| `pyproject.toml` | 1 | Partial | Missing `discord.py`, `slack_bolt`, `matrix-nio`, `aiosmtplib`, `imap-tools` |
| `.env` | 1 | Bad value | `PUCK_TELEGRAM_TOKEN=Europe/Helsinki` — timezone string in token field |
| `scripts/init-db.sql` | 1-2 | Partial | Missing spec columns (`memory_type`, `importance`, `access_count`, `last_accessed_at`, `message_type`, `confidence`, `source_context`, `expires_at`, `superseded_by`); no per-agent DB roles |
| `skills/registry.json` | 3 | Empty | Contains `{"skills": []}` despite 4 skills on disk |
| `personalities/discord.yaml` | 1 | **MISSING** | Only generic 31 YAMLs exist; no channel-specific personalities |

---

## Phase-by-Phase Gap Analysis

### Phase 1: One Agent Talks (~65% complete)

**Blockers preventing Phase 1 completion:**

1. **Discord adapter missing** — The spec lists Discord as the Phase 1 adapter. Only Telegram exists. `__main__.py` accepts `--channel discord` but hard-codes `TelegramAdapter` and raises `ValueError` for anything else.
2. **Personality schema mismatch** — The spec YAML schema (`archetype`, `tone`, `style`, `response_length`) is not what `personality.py` parses. The current `personalities/` directory has 31 generic YAMLs but no `discord.yaml` with Puck's personality.
3. **Health endpoint bug** — `health.py` does `f"{settings.llm_base_url}/api/tags"`. When `LLM_BASE_URL` is `http://ollama:11434/v1`, this produces `.../v1/api/tags` which is a 404. The correct Ollama tags endpoint is `/api/tags` on the base URL (without `/v1`). Also missing NATS connectivity check.
4. **docker-compose missing Ollama** — The current `docker-compose.yaml` assumes `host.docker.internal` for Ollama. The spec requires an `ollama` service with GPU passthrough.
5. **Dockerfile default CMD** — `Dockerfile` (not yet examined in detail) likely defaults to `--channel telegram` instead of `--channel discord` per spec.
6. **pyproject.toml missing channel SDKs** — `discord.py` is required for Phase 1 but not present in dependencies.
7. **BaseAdapter signature mismatch** — `send()` takes `conversation_key`, `text`, `**kwargs`. Spec expects `channel_id`, `content`, `metadata`. `normalize` vs `normalise` spelling mismatch.

### Phase 2: Memory Works (~70% complete)

**Gaps:**

1. **Private memory type safety** — `save()` uses `str(embedding)` instead of `$3::vector`, which may fail pgvector type checking depending on server config.
2. **RLS SQL injection risk** — `_init_connection` does `await conn.execute(f"SET app.agent_id = '{self._agent_id}'")`. This should be parameterized: `await conn.execute("SET app.agent_id = $1", self._agent_id)`.
3. **RLS context manager missing** — `SET app.agent_id` runs on pool `init`, not on every connection checkout. Per the spec, this should wrap pool checkout to guarantee the session variable is always set, even on connection reuse.
4. **Missing spec columns** — `init-db.sql` lacks: `memory_type`, `importance`, `access_count`, `last_accessed_at` on `private_memory`; and `message_type`, `confidence`, `source_context`, `expires_at`, `superseded_by` on `council_memory`.
5. **No per-agent DB roles** — The spec requires `CREATE ROLE agent_discord LOGIN ...` etc. Current schema uses a single shared role.
6. **All memory tests are mocked** — No real DB integration tests verify RLS isolation (agent A cannot read agent B's memories).
7. **Embedding resilience** — `embeddings.py` has no retry logic or local cache for when Ollama is unavailable.

### Phase 3: Skills System (~70% complete)

**Gaps:**

1. **registry.py reads filesystem, not `registry.json`** — `load_all()` iterates `skills_dir.glob("*.py")`. The spec says `registry.json` is the source of truth. `registry.json` is empty despite 4 skills on disk.
2. **Missing `watch_for_changes()`** — No polling or watchdog to detect skill deployments from other agents.
3. **Missing `Skill.as_tool()`** — No method to wrap a `Skill` as a PydanticAI tool for brain registration.
4. **Builder missing NATS council announcement** — `builder.py` does not publish `skill_deployed` broadcast on deploy.
5. **Builder tools not wired in brain.py** — `build_skill`, `test_skill`, `deploy_skill` are not registered as PydanticAI tools.
6. **Missing `templates.py`** — No LLM skill-generation template exists.
7. **Missing `tests/test_skill_sandbox.py`** — Sandbox has no dedicated test file.

### Phase 4: Second Agent + Communication (~60% complete)

**Gaps:**

1. **Slack adapter missing** — Blocks Phase 4 entirely.
2. **NATS stream name wrong** — `nats_bus.py` uses `COUNCIL`; spec calls for `pillywiggins`.
3. **`_parse_payload` discards metadata** — Returns only `(type, data)` tuple; drops `from` and `timestamp` which council memory needs.
4. **Agent never subscribes to messages** — `base.py` creates `NatsBus` but never calls `subscribe_broadcast()` or `subscribe_direct()`.
5. **No message routing** — No handling for `insight` or `skill_deployed` message types; no council memory integration on receive.
6. **messaging/__init__.py empty** — Should export `UnifiedMessage`, `NatsBus`, message type constants.

### Phase 5: Full Fleet (~40% complete)

**Gaps:**

1. **Matrix and Email adapters missing** — Both block Phase 5.
2. **Remaining channel personalities missing** — No `slack.yaml`, `telegram.yaml`, `matrix.yaml`, `email.yaml` with distinct archetypes.
3. **docker-compose missing all agent services** — Only `puck` (Telegram) exists. Missing Discord, Slack, Matrix, Email agent services entirely.
4. **pyproject.toml missing channel SDKs** — `slack_bolt`, `matrix-nio`, `aiosmtplib`, `imap-tools` all missing.

### Phase 6: Hardening (~30% complete)

**Gaps:**

1. **No rate limiting** — Spec calls for 10 LLM calls/minute per agent.
2. **No structured JSON logging** — Current logging is plain text, not JSON.
3. **No Docker healthchecks on agents** — Only postgres/searxng have healthchecks.
4. **No restart policies** — Spec requires `restart: unless-stopped` on agent services.
5. **No backup script** — `scripts/backup-db.sh` missing.
6. **No conversation summarization / memory consolidation** — Spec calls for periodic summarization and pruning.
7. **Searxng not in spec** — Present in docker-compose but not mentioned in overview-v2.

---

## Prioritized Recommendations

### Priority 1: Phase 1 Blockers (Do these first — without them, nothing else works)

1. **Implement `discord_adapter.py`** and wire it into `__main__.py`
2. **Fix `health.py` LLM URL bug** — strip `/v1` before appending `/api/tags`; add NATS check
3. **Fix `__main__.py` channel switch** — remove hard-coded `TelegramAdapter`, route to correct adapter
4. **Create `personalities/discord.yaml`** with Puck personality matching spec schema
5. **Add Ollama service to `docker-compose.yaml`** with GPU passthrough
6. **Add `discord.py` to `pyproject.toml`** dependencies
7. **Fix `.env` bad token value** — `PUCK_TELEGRAM_TOKEN` contains a timezone string
8. **Update `init-db.sql`** with all spec columns and per-agent DB roles
9. **Fix `BaseAdapter.send()` signature** to match spec (`channel_id`, `content`, `metadata`)

### Priority 2: Phase 2-3 Gaps (Fix memory correctness and skill integration)

10. **Fix `private.py` `save()`** — use `$3::vector` instead of `str(embedding)`
11. **Fix RLS SQL injection** — parameterize `SET app.agent_id`
12. **Add RLS connection-checkout context manager** — guarantee `app.agent_id` on every checkout
13. **Update `personality.py`** to parse spec schema (`archetype`, `tone`, `style`, `response_length`)
14. **Add embedding retry/cache logic** in `embeddings.py`
15. **Write real DB integration tests** for RLS isolation
16. **Rewrite `registry.py` `load_all()`** to read `registry.json` as source of truth
17. **Implement `watch_for_changes()`** (polling every 10s or watchdog)
18. **Implement `Skill.as_tool()`** for PydanticAI registration
19. **Add NATS council announcement** to `builder.py` deploy flow
20. **Register builder tools** (`build_skill`, `test_skill`, `deploy_skill`) in `brain.py`
21. **Create `skills/templates.py`** with skill generation template

### Priority 3: Phase 4-5 New Features (Expand to multi-agent fleet)

22. **Implement `slack_adapter.py`** and add `slack-agent` to docker-compose
23. **Implement `matrix_adapter.py`** and `email_adapter.py`
24. **Create remaining channel personalities** (`slack.yaml`, `telegram.yaml`, `matrix.yaml`, `email.yaml`)
25. **Fix NATS stream name** to `pillywiggins`
26. **Fix `_parse_payload`** to include `from` and `timestamp`
27. **Wire NATS subscriptions** in `base.py` (broadcast + direct)
28. **Implement message routing** for `insight` and `skill_deployed`
29. **Fill `messaging/__init__.py`** with exports
30. **Add `jobs_key` per agent** in `RedisJobStore`
31. **Fix scheduler personality YAML field name** (`cron_expr` -> `cron` or vice versa)
32. **Add synthetic `UnifiedMessage`** for non-send_message cron tasks
33. **Add remaining channel SDKs** to `pyproject.toml`
34. **Add all agent services** to `docker-compose.yaml`

### Priority 4: Phase 6 Hardening (Reliability and ops)

35. **Add GPU passthrough** and restart policies to `docker-compose.yaml`
36. **Add Docker healthchecks** to all agent services
37. **Add rate limiting** (10 LLM calls/min per agent)
38. **Implement structured JSON logging**
39. **Create `scripts/backup-db.sh`**
40. **Implement conversation summarization and memory consolidation**
41. **Remove or justify `searxng`** service (not in spec)
42. **Write end-to-end integration tests** for full fleet

---

## Risk Amplification

The gaps above are not merely "missing features." Several represent **active correctness risks**:

| Risk | Why It Matters |
|------|---------------|
| RLS f-string injection | A malicious `agent_id` could escape the quote and modify session variables |
| `str(embedding)` instead of `::vector` | May cause silent pgvector failures or performance degradation |
| `health.py` 404 on LLM check | Health endpoint reports degraded even when Ollama is healthy, masking real failures |
| Empty `registry.json` with skills on disk | Inconsistent state; future registry-driven features will break |
| No NATS subscriptions | Agents are deaf to council announcements and skill deployments |
| Scheduler silently dropping cron jobs | `cron_expr` in YAML vs `cron` in code means no cron schedules ever fire |
| `.env` bad token | Will cause Telegram auth failures in production |

---

## Dependency Graph of Critical Path

```
Phase 1 Blockers (all parallel):
  discord_adapter.py  __main__.py routing  health.py fix  personalities/discord.yaml
        |                    |                  |                  |
        +--------------------+------------------+                  |
                           |                                       |
                           v                                       v
                   Phase 1 complete (Discord agent talks)  docker-compose + pyproject fix
                           |
                           v
                Phase 2 Blockers (parallel):
                  private.py fixes  personality.py schema  init-db.sql update
                           |
                           v
                Phase 2 complete (Memory + Personality work)
                           |
                           v
                Phase 3 Blockers (parallel):
                  registry.py rewrite  Skill.as_tool()  builder.py NATS  templates.py
                           |
                           v
                Phase 3 complete (Skills system end-to-end)
                           |
                           v
                Phase 4 Blockers (parallel):
                  slack_adapter.py  NATS subscribe wiring  scheduler fixes
                           |
                           v
                Phase 4 complete (Two agents + council)
                           |
                           v
                Phase 5 (parallel): Matrix + Email adapters + personalities
                           |
                           v
                Phase 6 (sequential after Phase 5): Rate limiting, logging, backups
```

The longest critical path is approximately: Discord adapter -> private memory fixes -> registry rewrite -> NATS wiring -> Slack adapter -> Matrix/Email adapters -> hardening. Many of these can be parallelized once their prerequisites are met.

---

*Report generated by synthesizer agent (cell-2r4g0k-moan8bb1vsx) as part of epic cell-2r4g0k-moan8baftmh.*
