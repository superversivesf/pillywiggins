# Pillywiggins Operations Runbook

Day-to-day operations guide for the pillywiggins Docker Compose deployment. Grep-friendly: every problem section follows **Symptom → Diagnosis → Fix**.

---

## 1. Quick Health Check

Run these in order when something seems wrong. All services should show `Up` and `healthy`.

```bash
# 1. Overall service status
docker compose ps

# 2. Database
docker compose exec postgres pg_isready -U postgres

# 3. Redis
docker compose exec redis redis-cli PING

# 4. NATS
docker compose exec nats nats server check

# 5. Ollama (runs on host, not in compose)
curl -s http://localhost:11434/api/tags

# 6. GPU / VRAM (on host)
nvidia-smi

# 7. Latest agent output
docker compose logs puck --tail 5

# 8. Disk usage
df -h
du -sh backups/ pgdata/
```

**Expected output:** `docker compose ps` shows `healthy` for postgres, redis, nats, searxng, and all agent services. `pg_isready` returns `accepting connections`. `redis-cli PING` returns `PONG`. `nats server check` exits 0. `curl /api/tags` returns JSON with model list.

---

## 2. Viewing Logs

```bash
# Follow a specific agent live
docker compose logs -f puck

# Follow all services (interleaved)
docker compose logs -f

# Last N lines
docker compose logs --tail 50 bramblethorn
docker compose logs --tail 100 postgres

# Time-filtered logs
docker compose logs --since 10m nats
docker compose logs --since 1h puck

# Error hunting
docker compose logs nats 2>&1 | grep -i error
docker compose logs puck 2>&1 | grep -iE "error|exception|traceback"

# SearXNG (web search)
docker compose logs --tail 20 searxng

# Timestamps on (ISO 8601)
docker compose logs -t puck --tail 20
```

Logs persist across container restarts. If disk space is tight, run `docker compose logs --tail` with a limit rather than dumping everything.

---

## 3. Common Problems & Recovery

### 3.1 Agent Won't Start

**Symptom:** `docker compose ps` shows `exited` or `unhealthy` for an agent service.

**Diagnosis:**
```bash
docker compose logs <agent> --tail 30
```

**Root causes and fixes:**

| Root Cause | Fix |
|---|---|
| `agents.yaml` missing | `cp agents.yaml.example agents.yaml` |
| `.env` missing or invalid credentials | `cp env.example .env`, fill in `DATABASE_URL`, `PG_PASSWORD`, channel tokens |
| `agents.yaml` is a directory (bind mount creates directory when host file doesn't exist) | `rm -rf agents.yaml && cp agents.yaml.example agents.yaml` |
| Personality YAML missing or invalid path | Check `PERSONALITY_FILE` in env/agents.yaml points to a real file in `personalities/` |
| Channel token not set (Telegram, Discord, etc.) | Set `PUCK_TELEGRAM_TOKEN` (or relevant agent token) in `.env` |
| Dependencies not healthy | Run `docker compose ps` — postgres, redis, nats must all be `healthy` first |
| Ollama not reachable from container | Verify `LLM_BASE_URL` in `.env`; on Linux, see §7 Gotcha on `host.docker.internal` |
| Healthcheck start period too short | Increase `start_period` to `30s` or `60s` in docker-compose.yaml (agent needs time to connect PG, Redis, NATS, and warm the LLM) |

### 3.2 Agent Stops Responding

**Symptom:** `docker compose ps` shows `healthy`, but agent ignores channel messages. Users see "typing..." then nothing, or no response at all.

**Diagnosis:**
```bash
# Check agent logs for errors
docker compose logs puck --tail 20

# Verify Ollama is up and responding
curl -s http://localhost:11434/api/tags

# Check GPU / VRAM
nvidia-smi

# Check Redis (conversation cache)
docker compose exec redis redis-cli PING

# Verify agent process is running
docker compose exec puck pgrep -f pillywiggins
```

**Fixes:**

- **Ollama crashed or overloaded:** Restart Ollama on the host (`ollama serve`). On RTX 5060 Ti (16GB), qwen3.5:8b uses ~5GB VRAM. `OLLAMA_NUM_PARALLEL=2` means two concurrent requests are possible. If VRAM is exhausted, reduce parallelism or stop unused models.
- **Conversation cache corrupted:** `docker compose restart redis`. Cache is ephemeral — no data loss, just short-term memory reset.
- **NATS disconnected:** `docker compose restart nats`. Inter-agent messages may have been lost; agents recover automatically.
- **Agent stuck in LLM call:** Check `docker compose logs puck --tail 10` for a hanging request. Restart agent: `docker compose restart puck`.
- **Scheduler crash (historical):** Previously APScheduler crashed with `TypeError: cannot pickle '_thread.lock'` when using RedisJobStore. Now resolved — scheduler uses MemoryJobStore with JSON file persistence. If you see pickling errors on an older install, update your agent code.

### 3.3 Redis Down

**Symptom:** Agent still runs (scheduler uses MemoryJobStore), but conversation cache is unavailable. Short-term memory between conversation turns resets.

**Diagnosis:**
```bash
docker compose ps redis              # check status
docker compose exec redis redis-cli PING  # should return PONG
docker compose logs redis --tail 20
```

**Fix:**
```bash
docker compose restart redis
# Wait for healthy, then agents reconnect automatically.
docker compose exec redis redis-cli PING   # confirm
```

**Impact:** Agent continues processing messages. Conversation context (recent chat history) resets on restart. Private memory, council memory, and scheduling are unaffected.

### 3.4 PostgreSQL Down

**Symptom:** Agent loses private memory and council memory access. RLS enforcement stops working. Conversation cache in Redis is unaffected (temporary buffer).

**Diagnosis:**
```bash
docker compose ps postgres
docker compose exec postgres pg_isready -U postgres
docker compose logs postgres --tail 30
```

**Fix:**
```bash
docker compose restart postgres
# Wait for "healthy" — then agents reconnect automatically.
docker compose exec postgres pg_isready -U postgres  # confirm
```

**Impact:** Private memory (long-term knowledge) is unreachable while PostgreSQL is down. Agents continue processing messages but cannot recall past learnings. No data loss — pgvector data is on persistent volume.

**If PostgreSQL won't start (corruption):**
```bash
docker compose logs postgres --tail 50  # check for corruption messages
# Check disk space:
df -h
du -sh pgdata/
```

### 3.5 NATS Down

**Symptom:** Council broadcasts and inter-agent direct messages stop. Each agent continues processing its own channel messages fine, but they can't coordinate. `Failed to connect council memory` in agent logs.

**Diagnosis:**
```bash
docker compose ps nats
docker compose exec nats nats server check
docker compose logs nats --tail 30
```

**Fix:**
```bash
docker compose restart nats
docker compose exec nats nats server check   # confirm
```

**Impact:** Agents cannot publish skill updates via `skill_published` events, cannot send/receive council broadcasts, and cannot exchange direct messages. Each agent works in isolation. Agents reconnect automatically once NATS is healthy again.

### 3.6 Ollama Down or Overloaded

**Symptom:** Agent acknowledges a message (e.g., "Let me think about that…") then goes silent. Or returns error about model not being available.

**Diagnosis:**
```bash
# Test Ollama directly
curl -s http://localhost:11434/api/tags      # should return JSON with models
curl -s http://localhost:11434/api/chat -d '{
  "model": "qwen3.5:8b",
  "messages": [{"role": "user", "content": "ping"}],
  "stream": false
}'  | jq .message.content

# Check GPU status
nvidia-smi
```

**Fixes:**

- **Ollama not running on host:** `ollama serve` (run in a tmux/screen or as a systemd service)
- **Model not pulled:** `ollama pull qwen3.5:8b` (or whichever model is configured in `MODEL_NAME`)
- **VRAM exhausted:** On RTX 5060 Ti (16GB), `qwen3.5:8b` uses ~5GB. If multiple containers are configured with `OLLAMA_NUM_PARALLEL=2`, ensure total concurrent requests don't exceed VRAM. Check `nvidia-smi` for available memory.
- **`host.docker.internal` not resolving (Linux):** See §7 Gotchas. The agent container can't reach Ollama on the host. Use the host's actual IP in `LLM_BASE_URL` or add `extra_hosts` to docker-compose.
- **Ollama crashed GPU driver:** `dmesg | tail -30` for GPU driver errors. Restart Ollama and check `nvidia-smi` for GPU health.

### 3.7 Skill Sandbox Hangs or Web Search Fails

**Symptom:** Agent mentions it's searching or executing a skill, then times out. Or search results are empty/incomplete.

**Diagnosis:**

**For skill sandbox hangs:**
```bash
docker compose logs <agent> --tail 30     # look for "sandbox" or "timeout"
```
The sandbox has a 30-second timeout — hung processes are auto-killed.

**For web search failures:**
```bash
# Test SearXNG directly
curl -s "http://localhost:8888/search?q=test&format=json" | jq .
docker compose logs searxng --tail 20
```

**Fixes:**

- **SearXNG not initialized:** `docker compose restart searxng` and wait for `healthy`. Note: there's a startup race — the agent may try searching before SearXNG is ready. Restarting usually resolves it.
- **SearXNG healthcheck failing agents:** See §7 Gotchas — if agents `depends_on` SearXNG with `condition: service_healthy`, a failed SearXNG healthcheck causes agent restarts. Change to `service_started` or remove the dependency.
- **Brave Search API alternative:** If SearXNG is unreliable, configure `BRAVE_API_KEY` in `.env` (free tier: ~1,000 searches/month). The agent will use Brave instead.
- **Sandbox skill timeout:** If a specific skill consistently hangs, check the skill's code for infinite loops or external API calls without timeouts. Increase `SANDBOX_SKILLS` timeout or fix the skill.

---

## 4. Restart Procedures

### Full stack restart (preserves all data)
```bash
docker compose down
docker compose up -d
```

### Restart a single agent
```bash
docker compose restart puck
```

### Rebuild agent after code changes
```bash
# Single agent
docker compose up -d --build puck

# Multiple agents
docker compose up -d --build puck bramblethorn
```

### Infrastructure only
```bash
docker compose up -d postgres redis nats searxng
```

### Restart Ollama (on host, not in compose)
```bash
# Stop
pkill ollama

# Start in background (tmux/screen or systemd)
ollama serve > /tmp/ollama.log 2>&1 &

# Verify
curl -s http://localhost:11434/api/tags
nvidia-smi
```

### Order of operations for a full recovery
```bash
# 1. Infrastructure first
docker compose up -d postgres redis nats searxng
docker compose ps  # wait for all healthy

# 2. Verify Ollama on host
curl -s http://localhost:11434/api/tags

# 3. Bring up agents
docker compose up -d puck bramblethorn
docker compose ps  # wait for all healthy
```

---

## 5. Backup & Restore

### Automated backup (recommended)
```bash
# Saves to backups/ with timestamp, 14-day rotation
scripts/backup-db.sh

# Custom destination
scripts/backup-db.sh /mnt/backups/

# Cron example (daily at 3 AM):
# 0 3 * * * cd /path/to/pillywiggins && ./scripts/backup-db.sh >> /var/log/pillywiggins-backup.log 2>&1
```

Output: `backups/pillywiggins_YYYY-MM-DD_HH-MM-SS.sql.gz` plus `backups/pillywiggins_latest.sql.gz` symlink.

### Manual database backup
```bash
docker compose exec -T postgres pg_dump -U pillywiggins pillywiggins \
    --clean --if-exists --no-owner --no-privileges \
    | gzip > backup_$(date +%Y%m%d).sql.gz
```

### Restore database
```bash
# From compressed backup
gunzip -c backup_20260101.sql.gz | \
    docker compose exec -T postgres psql -U pillywiggins pillywiggins

# From uncompressed SQL
docker compose exec -T postgres psql -U pillywiggins pillywiggins < backup_20260101.sql
```

### Config backup (gitignored files — back these up separately!)
```bash
# Archive all config
tar czf config_backup_$(date +%Y%m%d).tar.gz \
    agents.yaml \
    .env \
    personalities/ \
    skills/ \
    schedules.json \
    docker-compose.yaml

# Restore
tar xzf config_backup_20260101.tar.gz
```

### What to back up

| What | Why | Backup method |
|---|---|---|
| PostgreSQL data | Private memory, council memory, embeddings | `scripts/backup-db.sh` or `pg_dump` |
| `agents.yaml` | Agent configuration (gitignored) | `tar czf` with other config |
| `.env` | Secrets, tokens, credentials (gitignored) | `tar czf` with other config |
| `skills/` | Custom agent skills | `tar czf` with other config |
| `personalities/` | Personality YAML files (templates are in git; custom ones are not) | `tar czf` with other config |
| `schedules.json` | Agent scheduler persistence (MemoryJobStore) | `tar czf` with other config |
| `docker-compose.yaml` | Your deployment-specific compose file (gitignored) | `tar czf` with other config |

**Not necessary to back up:** Redis data (ephemeral conversation cache), Docker volumes `pgdata` and `redisdata` (covered by `pg_dump`), SearXNG data (rebuilds on restart).

---

## 6. Adding a New Agent

```bash
# 1. Interactive setup wizard
pillywiggins onboard

# 2. Build and deploy
docker compose up -d --build <agent-name>

# 3. Verify it's running
docker compose logs -f <agent-name>

# 4. Confirm healthy
docker compose ps <agent-name>
```

The wizard guides you through:
- Selecting a personality from `personalities/`
- Choosing a channel (Telegram, Discord, etc.)
- Setting up channel tokens in `.env`
- Adding the service definition to `docker-compose.yaml` (or manually: uncomment and copy the agent template block)
- Adding the agent config to `agents.yaml`

After onboarding, the agent appears in `docker compose ps` alongside existing agents.

---

## 7. Known Gotchas

### 7.1 `host.docker.internal` on Linux

**Problem:** Docker Desktop (Mac/Windows) provides `host.docker.internal` automatically. On Linux (Docker Engine), it does not exist. The default `LLM_BASE_URL=http://host.docker.internal:11434/v1` in `.env` will fail.

**Fix — Option A (extra_hosts):** In `docker-compose.yaml`, add to each agent service:
```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

**Fix — Option B (host IP):** Change `LLM_BASE_URL` in `.env` to the host's actual IP:
```
LLM_BASE_URL=http://192.168.1.100:11434/v1
```
Find your IP with `ip addr show` or `hostname -I`.

**Fix — Option C (ollama in compose):** Move Ollama into Docker Compose with GPU access (requires nvidia-container-toolkit). See [Ollama Docker docs](https://hub.docker.com/r/ollama/ollama).

### 7.2 `agents.yaml` Bind Mount Creates a Directory

**Problem:** If `agents.yaml` doesn't exist on the host when Docker starts, the bind mount (`./agents.yaml:/app/agents.yaml:ro`) creates a directory instead of a file. Agent logs show `"IsADirectoryError"` or `"agents.yaml is a directory"`.

**Fix:**
```bash
rm -rf agents.yaml
cp agents.yaml.example agents.yaml
docker compose restart <agent>
```

### 7.3 Personality YAML Schema Inconsistency

**Problem:** Two personality formats coexist. The `personalities/` directory has YAML files organized by realm (bridge, clinic, fey_court, etc.), and some use `archetype`/`tone`/`style`/`response_length` while others use `description`/`system_prompt`/`traits`. Both formats work — the agent loader handles both.

**Fix:** No action required. The agent code detects and handles both formats. When creating custom personalities, either format is acceptable.

### 7.4 Schema Drift: `init-db.sql` vs `setup-db.sh`

**Problem:** `scripts/init-db.sql` is the canonical schema definition with HNSW indexes and full RLS policies (including `WITH CHECK`). `scripts/setup-db.sh` is stale with ivfflat indexes and partial RLS. Using the wrong one leads to missing indexes and broken RLS isolation.

**Fix:** Always use `init-db.sql`. It's mounted as `/docker-entrypoint-initdb.d/01-schema.sql` and runs automatically on first PostgreSQL startup. For manual use:
```bash
docker compose exec -T postgres psql -U pillywiggins pillywiggins < scripts/init-db.sql
```

### 7.5 APScheduler Pickle Issue (Resolved)

**Problem (historical):** When the scheduler used `RedisJobStore`, APScheduler crashed with `TypeError: cannot pickle '_thread.lock'` because Python thread locks cannot be serialized into Redis.

**Status:** Resolved. The scheduler now uses `MemoryJobStore` with JSON file persistence (`schedules.json`). No Redis dependency for scheduling.

**If you encounter this on an old deployment:** Update your agent code to use the MemoryJobStore implementation.

### 7.6 No Ollama Service in Docker Compose

**Problem:** `docker compose ps` does not include an Ollama service. New users may expect Ollama to be containerized.

**Status:** By design. Ollama runs directly on the host for direct GPU access without nvidia-container-toolkit. You must run `ollama serve` separately (manually, via systemd, or in tmux/screen).

**Verify it's running:**
```bash
curl -s http://localhost:11434/api/tags
```

### 7.7 SearXNG Startup Race

**Problem:** Agent containers may start and attempt web searches before SearXNG finishes initializing. This produces search errors in the agent logs even though SearXNG is working. Additionally, if `depends_on: searxng: condition: service_healthy` is set, a failed SearXNG healthcheck causes all agent containers to restart-loop.

**Fix for startup race:** Restart SearXNG and wait for `healthy`, or restart the agent after SearXNG is ready:
```bash
docker compose restart searxng
docker compose restart puck
```

**Fix for restart-loop:** In `docker-compose.yaml`, change the agent's dependency on SearXNG from `service_healthy` to `service_started` (or remove it entirely — agents handle missing SearXNG gracefully):
```yaml
depends_on:
  searxng:
    condition: service_started  # instead of service_healthy
```

---

## 8. Quick Reference

```bash
# Service status
docker compose ps

# Follow agent logs
docker compose logs -f puck

# Restart agent
docker compose restart puck

# Rebuild and restart agent
docker compose up -d --build puck

# Health checks
docker compose exec postgres pg_isready -U postgres
docker compose exec redis redis-cli PING
docker compose exec nats nats server check

# Ollama on host
curl -s http://localhost:11434/api/tags

# GPU status
nvidia-smi

# Disk usage
du -sh backups/ pgdata/
df -h

# Run database backup
scripts/backup-db.sh

# Add a new agent
pillywiggins onboard
docker compose up -d --build <agent-name>

# Full restart
docker compose down && docker compose up -d

# Infrastructure restart only
docker compose up -d postgres redis nats searxng

# Inspect PostgreSQL schema
docker compose exec postgres psql -U pillywiggins -d pillywiggins -c "\dt"
docker compose exec postgres psql -U pillywiggins -d pillywiggins -c "\d+ private_memory"

# List active NATS streams
docker compose exec nats nats stream ls

# Debug a single agent locally (no Docker)
pipx install -e .
pillywiggins --channel telegram --agent-id debug
```

---

## 9. Schema Note

**`scripts/init-db.sql` is the canonical schema definition.** It is mounted as `/docker-entrypoint-initdb.d/01-schema.sql` and runs automatically on first PostgreSQL startup. It contains:

- pgvector extension and HNSW indexes (vector similarity search)
- Full RLS policies with `USING` and `WITH CHECK` clauses on `private_memory`, `conversation_cache`, and `council_memory`
- Correct `vector(768)` column dimension

**`scripts/setup-db.sh` is a manual alternative that has drifted.** It uses ivfflat indexes (slower than HNSW) and has incomplete RLS policies. Always prefer `init-db.sql`.

**To recreate the database from scratch:**
```bash
docker compose down
docker volume rm pillywiggins_pgdata
docker compose up -d postgres
# init-db.sql runs automatically on first startup
```

**To apply schema changes manually:**
```bash
docker compose exec -T postgres psql -U pillywiggins pillywiggins < scripts/init-db.sql
```
