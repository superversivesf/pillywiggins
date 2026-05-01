# Deployment Troubleshooting Guide

Quick-reference for the most common failure modes when running Pillywiggins with Docker Compose.  Each section gives you a **symptom**, **root cause**, **one-line diagnostic**, and **fix**.

---

## 1. Agent starts but council memory / NATS never connects

### Symptom
Agent logs show messages like:

```
Failed to connect council memory for <agent_id>
NATS unavailable for <agent_id> — continuing without messaging
```

The agent still responds to channel messages, but it cannot share memory with the council or broadcast/receive NATS events.

### Root cause
`src/pillywiggins/__main__.py` omits `database_url` and/or `nats_url` when constructing `PillywigginAgent(...)`. Without these arguments the agent skips council-memory and NATS initialisation entirely.

### Diagnostic
```bash
grep "PillywigginAgent(" src/pillywiggins/__main__.py
```

Look for **both** of these inside the constructor call:

```python
database_url=settings.database_url,
nats_url=settings.nats_url,
```

### Fix
Add the two keyword arguments if they are missing:

```python
agent = PillywigginAgent(
    agent_id=agent_id,
    personality=personality,
    model_name=settings.model_name,
    provider=settings.llm_provider,
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
    cache=cache,
    store=store,
    private_memory=private_memory,
    skill_registry=skill_registry,
    compact_keep_messages=settings.compact_keep_messages,
    compact_truncate_message_chars=settings.compact_truncate_message_chars,
    database_url=settings.database_url,   # <-- ensure present
    nats_url=settings.nats_url,           # <-- ensure present
)
```

Restart the agent container:

```bash
docker compose restart <agent-service>
```

---

## 2. Skills not visible to other agents

### Symptom
Agent A drops a new Python file into `./skills/`, but agent B never picks it up. Tools added by the new skill do not appear in agent B's brain.

### Root cause
Two common causes:

1. `docker-compose.yaml` uses a **named Docker volume** for `/app/skills` instead of a **bind mount**, so the host `./skills/` directory is never reflected inside the container.
2. `skill_published` NATS events are received, but `_refresh_brain_tools()` is not invoked (or `create_brain` is not re-registering the updated `SkillRegistry`).

### Diagnostic

**Check the mount type:**

```bash
# Inside the container — should list the same files you see on the host
docker compose exec puck ls /app/skills/

# On the host — compare the two listings
ls skills/
```

If the container listing is stale or missing host files, the volume is wrong.

**Check whether `_refresh_brain_tools()` runs on `skill_published`:**

```bash
grep -n "skill_published" src/pillywiggins/agents/base.py
```

You should see a call to `_refresh_brain_tools()` inside the `skill_published` branch.

### Fix

1. Ensure the service definition uses a **bind mount** (`.` prefix), not a named volume:

   ```yaml
   volumes:
     - ./skills:/app/skills          # correct (bind mount)
     # skills_data:/app/skills       # wrong (named volume)
   ```

2. Verify `agents/base.py` reloads the skill registry and refreshes tools when a `skill_published` event arrives:

   ```python
   elif msg_type == "skill_published":
       if self._skill_registry is not None:
           self._skill_registry.load_all()
           self._refresh_brain_tools()
   ```

   If `_refresh_brain_tools()` is missing, add it.  It should reconstruct the brain so the new tools are registered.

Restart affected agents after editing code:

```bash
docker compose up -d --build <agent-service>
```

---

## 3. NATS messages silently lost

### Symptom
- Skill publishes succeed (no exception raised), but other agents do not receive broadcast events.
- Direct messages between agents have no reply, even though both agents are running.
- Logs contain `Failed to publish broadcast` or handler errors, but the publish call did not propagate the exception to the caller.

### Root cause
1. `is_connected` returns a stale `True` because it checks an internal `self._connected` flag instead of querying the actual `nats-py` connection state.
2. Exceptions inside `publish_broadcast()` or `publish_direct()` are caught and only logged, so callers never know the message failed.
3. The background `_monitor()` task has crashed or was never started, so the agent never auto-reconnects after a transient NATS outage.

### Diagnostic

**Check `is_connected` implementation:**

```bash
grep -A3 "def is_connected" src/pillywiggins/messaging/nats_bus.py
```

It should read:

```python
@property
def is_connected(self) -> bool:
    if self._nc is None:
        return False
    return self._nc.is_connected
```

**Check for swallowed exceptions:**

```bash
grep -n "Failed to publish" src/pillywiggins/messaging/nats_bus.py
```

Look for `except Exception:` blocks that only call `logger.exception(...)` without re-raising.

**Check that `_monitor()` is running:**

```bash
grep -n "_monitor_task" src/pillywiggins/messaging/nats_bus.py
```

Ensure `connect()` creates the task and `close()` cancels it.  If `_monitor_task` is `None` or `.done()`, the monitor is not active.

### Fix

1. Make `is_connected` query the live NATS client:

   ```python
   return self._nc.is_connected
   ```

   (Remove any cached `self._connected` boolean if present.)

2. In `publish_broadcast` / `publish_direct`, either **re-raise** after logging or return a status the caller can check:

   ```python
   try:
       ack = await self._js.publish(...)
   except Exception:
       logger.exception("Failed to publish broadcast ...")
       raise   # or return {"success": False}
   ```

3. Verify `connect()` spawns the monitor task and that it survives reconnect attempts:

   ```python
   if self._monitor_task is None or self._monitor_task.done():
       self._monitor_task = asyncio.create_task(self._monitor())
   ```

Restart the agent after the fix.

---

## 4. Council memory rejects embeddings

### Symptom
Calls to `CouncilMemory.write_entry()` or `CouncilMemory.search()` raise PostgreSQL errors about **vector dimensions**, or return:

```
Embedding dimension 384 does not match council_memory column dimension 768
```

### Root cause
- `CouncilMemory` was constructed without an explicit `embedding_dimension`, so it falls back to the default `768`.
- The runtime embedding model (e.g. a 384-dim sentence transformer) produces vectors whose length does **not** match the column dimension in `council_memory.embedding vector(768)`.
- `PrivateMemory` and `CouncilMemory` are initialised with different dimensions.

### Diagnostic

**Check the configured dimension:**

```bash
grep "embedding_dimension" src/pillywiggins/config.py
```

**Check what `CouncilMemory` receives:**

```bash
grep -n "CouncilMemory(" src/pillywiggins/agents/base.py
```

It should show:

```python
CouncilMemory(self._database_url, self.agent_id, embedding_dimension=settings.embedding_dimension)
```

**Check the database column dimension:**

```bash
docker compose exec postgres psql -U pillywiggins -d pillywiggins -c "\d council_memory"
```

Look for the `embedding` line — e.g. `vector(768)`.

### Fix

Pass the same `embedding_dimension` used by `PrivateMemory` into `CouncilMemory`:

```python
council = CouncilMemory(
    self._database_url,
    self.agent_id,
    embedding_dimension=settings.embedding_dimension,
)
```

If you change the model to one that produces a different dimension, you must also recreate the pgvector column or create a new table with the matching dimension:

```sql
ALTER TABLE council_memory ALTER COLUMN embedding TYPE vector(384);
ALTER TABLE private_memory ALTER COLUMN embedding TYPE vector(384);
```

(Changing the dimension drops and recreates the HNSW index; re-run `init-db.sql` or rebuild indexes afterwards.)

---

## 5. SearXNG failure causes all agents to restart-loop

### Symptom
All agent containers show `Restarting` in `docker compose ps`. The only recent change is that the `searxng` container is down or its healthcheck is failing.

### Root cause
`docker-compose.yaml` declares:

```yaml
depends_on:
  searxng:
    condition: service_healthy
```

When SearXNG's healthcheck fails (e.g. after a network blip or settings error), Docker Compose marks it unhealthy.  Because agents depend on `service_healthy`, Compose restarts them continuously even though the agents can operate without SearXNG (skills that need search will simply fail gracefully).

### Diagnostic

```bash
# See which services are restarting
docker compose ps

# Check SearXNG health
docker logs --tail 50 searxng
```

### Fix

Change the dependency from `service_healthy` to `service_started` (or remove the `searxng` dependency entirely if the agent does not strictly require it at boot):

```yaml
depends_on:
  postgres:
    condition: service_healthy
  redis:
    condition: service_healthy
  nats:
    condition: service_healthy
  # searxng:
  #   condition: service_healthy   # <-- remove or relax
```

If you still want agents to wait for SearXNG to exist but not be fully healthy, use:

```yaml
  searxng:
    condition: service_started
```

Then restart:

```bash
docker compose up -d
```

---

## 6. Health check fails during startup

### Symptom
`docker compose ps` shows an agent stuck in `(health: starting)` for a few seconds, then flipping to `(unhealthy)` before the agent finishes initialising.  The container may be killed and restarted by Compose or by an orchestrator.

### Root cause
The healthcheck `start_period` is too short for the agent to connect PostgreSQL, Redis, NATS, and the LLM backend.  The default in the example compose is `5s`; in practice agents need 10–30s before they respond on the HTTP health port.

### Diagnostic

```bash
docker compose ps
# Watch the STATUS column transition from (health: starting) → (unhealthy)
```

Check agent logs to see how far it got before the health probe failed:

```bash
docker logs --tail 30 <agent-service>
```

### Fix

Increase `start_period` to at least `30s` in the agent service definition:

```yaml
healthcheck:
  test: ["CMD-SHELL", "wget --spider -q http://localhost:8080/healthz || exit 1"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 30s   # <-- was 5s, increase to 30s
```

If the agent is on a slow host or cold-starting Ollama models, you can raise it further (e.g. `60s`).  The key is that `start_period` must cover the longest serial dependency connection (usually NATS + PostgreSQL + LLM warmup).

Apply with:

```bash
docker compose up -d
```

---

## 7. PostgreSQL RLS not isolating agents

### Symptom
Agent A can query or update rows in `private_memory` or `conversation_cache` that belong to agent B.  Memory leaks between agents, or one agent overwrites another's conversation history.

### Root cause
Two failure modes:

1. **Connection pool `init` callback does not set `app.agent_id`.**  RLS policies rely on `current_setting('app.agent_id')`.  If the asyncpg pool is created without an `init` callback that runs `SET app.agent_id = '<agent_id>'` on every new connection, the policy evaluates against an empty string and blocks (or, if `app.agent_id` is not set at all, `current_setting` may raise an error).

2. **RLS policy is missing `WITH CHECK`.**  A `FOR ALL` policy without `WITH CHECK` only filters rows on `SELECT`/`UPDATE`/`DELETE` but does not validate `INSERT`s, allowing cross-agent inserts.

### Diagnostic

**Test from inside the agent container:**

```bash
docker compose exec <agent-service> python -c "
import asyncio, asyncpg, os
async def test():
    pool = await asyncpg.create_pool(os.environ['DATABASE_URL'])
    async with pool.acquire() as conn:
        val = await conn.fetchval(\"SELECT current_setting('app.agent_id')\")
        print('app.agent_id =', val)
    await pool.close()
asyncio.run(test())
"
```

If this raises `configuration parameter "app.agent_id" is not set` or returns an empty string, the pool `init` callback is missing.

**Inspect the policy definition:**

```bash
docker compose exec postgres psql -U pillywiggins -d pillywiggins -c "\d+ private_memory"
docker compose exec postgres psql -U pillywiggins -d pillywiggins -c "\dp private_memory"
```

Look for:

```sql
CREATE POLICY private_memory_isolation ON private_memory
    FOR ALL
    USING (agent_id = current_setting('app.agent_id')::text)
    WITH CHECK (agent_id = current_setting('app.agent_id')::text);   -- <-- WITH CHECK must be present
```

### Fix

1. **Ensure the pool `init` callback sets the variable.**  In any file that creates an `asyncpg.create_pool` for agent data (e.g. `memory/private.py`, `memory/store.py`), add:

   ```python
   async def _init_connection(conn):
       await conn.execute(f"SET app.agent_id = '{agent_id}'")
       # ... other setup (register_vector, JSONB codec, etc.)

   pool = await asyncpg.create_pool(
       database_url,
       init=_init_connection,
       ...
   )
   ```

2. **Ensure `init-db.sql` has explicit `WITH CHECK` on every RLS policy.**  The current schema should already contain it, but verify:

   ```sql
   CREATE POLICY private_memory_isolation ON private_memory
       FOR ALL
       USING (agent_id = current_setting('app.agent_id')::text)
       WITH CHECK (agent_id = current_setting('app.agent_id')::text);

   CREATE POLICY conversation_cache_isolation ON conversation_cache
       FOR ALL
       USING (agent_id = current_setting('app.agent_id')::text)
       WITH CHECK (agent_id = current_setting('app.agent_id')::text);
   ```

   If `WITH CHECK` is missing, alter the policy:

   ```sql
   ALTER POLICY private_memory_isolation ON private_memory
       WITH CHECK (agent_id = current_setting('app.agent_id')::text);
   ```

3. Recreate the database volume if you are unsure about drift:

   ```bash
   docker compose down
   docker volume rm pillywiggins_pgdata
   docker compose up -d postgres
   docker compose exec postgres psql -U pillywiggins -d pillywiggins -f /docker-entrypoint-initdb.d/01-schema.sql
   ```

---

## General tips

- **Always check logs first:** `docker compose logs --tail 50 <service>`
- **Rebuild after code changes:** `docker compose up -d --build <service>`
- **Run a single agent locally for debugging:**
  ```bash
  pipx install -e .
  pillywiggins --channel telegram
  ```
- **Verify `.env` is not committed:** `git status` should show `.env` as untracked.
