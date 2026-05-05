# Pillywiggins Multi-Agent Test Checklist

Work through each section with both agents running. Many bugs only surface during multi-agent interaction. Tick boxes as you verify each item.

---

## Phase 1 — Core Memory (DB / Dimension Bugs)

### Private Memory (per-agent)
- [ ] **Save memory**: Tell Agent A "Remember my favorite color is red"
- [ ] **Recall memory**: Ask Agent A "What is my favorite color?" → should return "red"
- [ ] **Memory search**: Ask "What do you know about me?" → should find the color memory via similarity
- [ ] **Memory persistence**: Restart Agent A, ask the same question → should still recall
- [ ] **Memory with metadata**: Ask agent to remember something with a tag or category
- [ ] **Memory delete**: "Forget my favorite color" (if a delete skill is available)

### Council Memory (shared)
- [ ] **Share to council**: Ask Agent A to "share an insight with the council"
- [ ] **Query council**: Ask Agent B "What insights has the council shared?" → should see Agent A's contribution
- [ ] **Cross-agent council write**: Agent A shares to council, Agent B reads it back
- [ ] **Council persistence**: Restart both agents, query council again → should still be there

---

## Phase 2 — Inter-Agent Communication (NATS / Config Bugs)

- [ ] **Broadcast message**: Use a custom message to `council.broadcast` from Agent A; verify Agent B receives it in logs
- [ ] **Direct message**: Send a direct message to `council.direct.{agent_id}` → verify only the target agent receives it
- [ ] **Agent ping**: Use any built-in skill that sends a NATS message to the other agent by name
- [ ] **NATS reconnect**: Restart the NATS container (`docker compose restart nats`) → verify both agents reconnect automatically in logs

---

## Phase 3 — Built-in Skills & Diagnostics

### Standard Skills
- [ ] **Web search**: "Search the web for quantum computing news" (uses `brave_search` or `searxng`)
- [ ] **Website check**: "Check if example.com is up"
- [ ] **Dice roll**: "Roll a d20"
- [ ] **Word count**: "Count the words in this message"

### Skill Registry
- [ ] **Skill loading**: Check startup logs that all skills loaded without errors
- [ ] **Dynamic skill add**: Add a new `.py` file to the `skills/` volume and verify the agent picks it up (wait for auto-reload or restart the agent)

---

## Phase 4 — Scheduling (APScheduler)

- [ ] **Heartbeat job**: Check logs for periodic `_builtin_heartbeat` entries
- [ ] **Memory review job**: Verify `_builtin_memory_review` runs on schedule
- [ ] **Skill reload job**: Verify `_builtin_skill_reload` runs
- [ ] **Redis persistence**: Restart the Redis container → verify scheduled jobs survive and resume
- [ ] **Misfire tolerance**: Stop an agent for 5 minutes, restart it → verify jobs catch up (check `misfire_grace_time=300` behavior)

---

## Phase 5 — Channel Adapters

### Telegram (Puck)
- [ ] **Text message**: Send plain text → verify response
- [ ] **Long message**: Send a message >2000 characters → verify truncation or split handling
- [ ] **Command handler**: Send `/start` or any configured command
- [ ] **Unauthorized user**: Have an unauthorized Telegram user message the bot → verify rejection
- [ ] **Timeout handling**: Observe logs during slow network conditions → verify graceful `WARNING` instead of full traceback

### Other Channels (if configured)
- [ ] **Discord**: Message formatting, embeds, slash commands
- [ ] **Slack**: DM vs channel, thread handling
- [ ] **Matrix**: Room vs DM, HTML formatting

---

## Phase 6 — Database & Storage

- [ ] **RLS enforcement**: Verify Agent A cannot read Agent B's `private_memory` rows (inspect DB directly: `docker compose exec postgres psql -U pillywiggins -d pillywiggins -c "SELECT * FROM private_memory WHERE agent_id = '{other_agent_id}';"`)
- [ ] **Vector search quality**: Query with an embedding and verify results are ordered by similarity correctly
- [ ] **Conversation cache**: Have a long back-and-forth conversation → verify history loads correctly on next message
- [ ] **DB reconnect**: Restart the PostgreSQL container (`docker compose restart postgres`) → verify agents reconnect and resume
- [ ] **Embedding dimension change**: Edit `.env` to change `EMBEDDING_MODEL` to a model with a different dimension → verify `ALTER TABLE` runs automatically on restart (check logs)

---

## Phase 7 — Configuration & Personality

- [ ] **Personality loading**: Verify the agent responds with its configured personality tone (e.g., Puck is whimsical, Ember is formal)
- [ ] **Personality reload**: Edit `personalities/puck.yaml`, restart the agent container → verify new behavior
- [ ] **Agent-specific config**: If running multiple agents, verify each loads its own personality and config
- [ ] **Env override**: Change a setting in `.env`, restart the agent → verify the new value takes effect
- [ ] **Timezone handling**: Verify scheduled jobs respect the agent's configured timezone

---

## Phase 8 — Health & Monitoring

- [ ] **Healthz endpoint**: `curl http://localhost:8080/healthz` → should return HTTP 200
- [ ] **Ollama health**: `curl http://localhost:11434/api/tags` → should list available models
- [ ] **Model list**: Run `curl http://localhost:11434/api/tags` and verify Ollama reports available models
- [ ] **Resource usage**: Run `docker stats` and monitor for memory/CPU bloat over a 30-minute window

---

## Phase 9 — Resilience & Edge Cases

- [ ] **Agent restart**: Restart one agent mid-conversation → verify it resumes correctly and context is preserved
- [ ] **Message flood**: Send 5 messages rapidly to one agent → verify no crashes or dropped messages
- [ ] **Empty message**: Send a blank or whitespace-only message → verify graceful handling
- [ ] **Special characters**: Send emoji, markdown (`**bold**`), and code blocks → verify formatting is preserved or handled gracefully
- [ ] **Concurrent requests**: Have two different users message simultaneously → verify no deadlocks or cross-talk
- [ ] **LLM failure / fallback**: Stop the Ollama container temporarily → verify the agent falls back to HuggingFace embeddings or logs a graceful error

---

## How to Report an Issue

When you find a bug, capture:

1. **The exact message you sent**
2. **The agent's response (if any)**
3. **Relevant log output** (`docker logs pillywiggins-{agent}-1 --since 5m`)
4. **The expected vs actual behavior**

Paste these into a new issue or message and the swarm will investigate.

---

## Quick Debug Commands

```bash
# Check agent logs
docker logs pillywiggins-puck-1 --since 5m
docker logs pillywiggins-ember-1 --since 5m

# Check all service logs
docker compose logs --tail 50

# Restart a single agent
docker compose restart puck

# Check health
curl http://localhost:8080/healthz

# Check Ollama models
curl http://localhost:11434/api/tags

# Inspect DB directly
docker compose exec postgres psql -U pillywiggins -d pillywiggins -c "SELECT * FROM private_memory LIMIT 5;"
```

---

*Checklist version: 2026-05-05*
*Last updated after fixes: embedding dimension migration, config env poisoning, Telegram timeout handling.*
