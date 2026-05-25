# Release Notes — v0.4.0
*(May 2026)*

38 commits since v0.3.0. This release delivers multi-provider LLM support, three-layer prompt injection hardening, MCP server integration, a Claude skill importer, display name overrides, memory consolidation, and a raft of deployment and security fixes.

---

## New Features

### Multi-provider LLM support

The onboard wizard (`pillywiggins onboard`) now offers **9 providers** when configuring an agent. Every provider uses the OpenAI-compatible API path through PydanticAI, which means tool calling, streaming, and structured output work identically across all providers.

| Provider | Key | Default Base URL |
|---|---|---|
| Ollama (local) | `ollama` | `http://host.docker.internal:11434/v1` |
| Ollama Cloud | `ollama_cloud` | `https://ollama.com/v1` |
| OpenAI | `openai` | `https://api.openai.com/v1` |
| Groq | `groq` | `https://api.groq.com/openai/v1` |
| Together AI | `together` | `https://api.together.xyz/v1` |
| OpenRouter | `openrouter` | `https://openrouter.ai/api/v1` |
| vLLM (self-hosted) | `vllm` | `http://host.docker.internal:8000/v1` |
| LiteLLM Proxy | `litellm` | `http://host.docker.internal:4000/v1` |
| Custom | `custom` | *(user-provided)* |

Each provider pre-fills suggested models and API key requirements. The `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY`, and `MODEL_NAME` environment variables are written to `.env` and respected at startup. Switching providers is a single `pillywiggins onboard` re-run.

> **Related changes:** `agents.yaml` entries now include a `provider` key. The `AgentDeps` dataclass carries `llm_provider` through to all tool calls. Old `ollama` configs continue to work — `ollama` is the fallback default.

### Prompt injection defense

Three independent layers harden the agent against prompt injection attacks:

1. **XML input wrapping** — User messages are wrapped in `<user_message>` tags and a randomly generated canary token is injected into the system prompt. Any LLM output reproducing the canary token is blocked, detecting prompt leaks before they reach the user.

2. **Sandwich defense** — The system prompt is structured with guardrails at the top and bottom of the message, bracketing user content between explicit boundaries that the model cannot easily override.

3. **Structural injection detection** — `PromptSanitizer` (in `src/pillywiggins/security/prompt_sanitizer.py`) scores every message against three structural heuristics:
   - **API token leaks** — 13 token format patterns (OpenAI, GitHub, AWS, Slack, Anthropic, Google, Stripe, JWT)
   - **Context boundary injection** — Chat template delimiters that attackers use to escape conversation context (`<|im_start|>`, `[INST]`, `<<SYS>>`, etc.)
   - **Unicode obfuscation detection** — Zero-width character stripping + NFKC normalization to defeat homoglyph attacks

   Input messages are scored at threshold **40** (lenient, to avoid blocking legitimate conversation). Output messages are scored at threshold **30** (stricter — outputs should never contain leaked keys or template delimiters).

> **Removed:** Keyword-based substring matching (`JAILBREAK_PATTERNS`, `ROLEPLAY_PATTERNS`) was removed after it caused excessive false positives on common words in normal conversation. The new system is purely structural — it only blocks format-specific patterns, never content.

### MCP server integration

Agents can now connect to external MCP (Model Context Protocol) servers for extended tool access. Configured globally via `pillywiggins onboard`, stored in `skills/mcp_servers.json` and shared across all agents.

Supports two transport modes:
- **stdio** — Subprocess-based MCP servers (e.g., `npx @modelcontextprotocol/server-filesystem`)
- **Streamable HTTP** — Remote MCP servers over HTTP/SSE

Configuration is done once in the onboard wizard. At startup, `__main__.py` reads `mcp_servers.json`, builds `MCPServerStdio` / `MCPServerStreamableHTTP` instances, and appends them as toolsets to the agent's PydanticAI brain. Existing agents pick up new MCP servers on the next `docker compose restart`.

### Claude skill importer

New CLI command: `pillywiggins import-skills`.

Converts Claude-style `.skill.md` files (YAML frontmatter + markdown instructions) into Pillywiggins `.py` skill files. Handles:

- YAML frontmatter parsing (`name`, `description`)
- `## Instructions` → docstring conversion
- `## Tools` → `register_tools()` function body
- `## Parameters` → tool signature generation

```bash
# Import a single file
pillywiggins import-skills --source ~/claude-skills/weather.skill.md --output skills/

# Import a directory
pillywiggins import-skills --source ~/claude-skills/ --output skills/
```

The importer lives in `src/pillywiggins/skills/claude_importer.py` with full test coverage in `tests/test_claude_importer.py`.

### Display name override

Agents can now have a custom **display name** that differs from their personality name. When set, the display name is used in user-facing output (channel messages, status reports) while the personality name remains for internal routing and scheduling.

Set during onboarding:
```
Display name (optional, e.g. "Assistant Bot"): My Custom Name
```

Stored in `agents.yaml` as `display_name`. If omitted, the personality name is used as before. Existing configs without this field behave identically.

### Memory consolidation

Agents now automatically prune and compact long-running conversation histories to stay within model context windows. When a conversation exceeds 12 messages, `compact_history()` summarizes the oldest exchanges into a single system message, preserving the 6 most recent messages intact.

The `consolidate_memory` tool is also registered as an agent tool, so agents can trigger consolidation on demand. Scheduled task handlers invoke `compact_history()` after each task run to prevent unbounded growth in cron-driven conversations.

---

## Bug Fixes

### Deployment fixes

- **PostgreSQL / Redis crash from `cap_drop:ALL` + `read_only:true`** — These Compose security options are incompatible with database stateful services. Removed from `postgres` and `redis` services. Databases run with default Docker capabilities and writable filesystems.
- **Docker Compose v5 parse error** — `no_new_privileges` is not a valid Compose key under `deploy`. Moved to `security_opt: ["no-new-privileges:true"]`.
- **Dockerfile healthcheck using missing `/healthz` endpoint** — Replaced with `pg_isready`-style process checks. `procps` added to the Docker image as a dependency.
- **AgentLogger crash on read-only filesystem** — `AgentLogger` now gracefully falls back to in-memory logging when the filesystem is read-only. A `/app/logs` tmpfs mount with explicit UID/GID ensures log directories exist even under restrictive security profiles.

### Agent runtime fixes

- **Scheduled messages not saved to conversation history** — Scheduled task results were being generated but discarded. Fixed by appending results to the conversation cache after each scheduled run.
- **Web search tool crash** — `Settings()` was unavailable in the sandbox environment. Fixed by injecting required environment variables into the sandbox process.
- **Missing `settings` parameter causing startup crash loop** — A `PillywigginAgent` initialization path omitted the `settings` parameter, causing agents to crash at startup. Fixed the constructor call chain.
- **`display_name` `NameError` during onboard** — The variable wasn't properly propagated through the config function chain. Fixed by threading it through all intermediate functions.
- **Skill parameter schema mismatch** — Skill tools with empty parameter schemas caused validation errors during tool registration. Fixed by handling empty schemas gracefully.
- **Memory recall prompt regression** — The tool prompt for `recall_private_memory` didn't include a strong enough instruction to search memory before claiming ignorance. Prompt strengthened with `MUST first search` wording.

---

## Security

- **Keyword-based prompt injection blocking removed** — `JAILBREAK_PATTERNS` and `ROLEPLAY_PATTERNS` caused too many false positives on normal conversation (e.g., "hack", "sudo", "Dan", "leak"). Replaced with structural heuristics in `PromptSanitizer`.
- **13 API token format patterns** detected at input and output boundaries — OpenAI (`sk-`), GitHub (`ghp_`, `gho_`, `ghu_`), AWS (`AKIA`, `ASIA`), Slack (`xox[baprs]-`), Anthropic (`sk-ant-api`), Google (`AIza`), Stripe (`pk_live_`, `sk_live_`), JWT (`eyJ...`)
- **Context boundary injection detection** — Chat template delimiters (`<|im_start|>`, `[INST]`, `<<SYS>>`, `<|system|>`, `<|user|>`, `<|assistant|>`) are detected and scored.
- **Canary token defense** — A per-agent random 12-byte hex token is injected into the system prompt as a leak detector. If the LLM output ever contains the token (indicating a prompt leak), the response is replaced with `[Response filtered for security]`.
- **Output sanitization** — Stricter threshold (30) than input (40) since model outputs should never contain API keys or template delimiters.
- **`.env` enforcement in CI** — Tests now verify that `.env` is gitignored and not committed, and that required environment variables fail gracefully when missing.

---

## Breaking Changes

| Change | Details | Migration |
|---|---|---|
| `sanitize_output` threshold | Changed 20 → 25 → 30 | No action. Existing deployments pick up the new default. |
| Input sanitization threshold | Changed from keyword-based to structural, threshold 30 → 40 | No action. Fewer false positives, same detection for structural attacks. |
| `JAILBREAK_PATTERNS` removed | Keyword-based blocking removed entirely | No action. The entire keyword system is gone; nothing to migrate. |
| `ROLEPLAY_PATTERNS` removed | Keyword-based blocking removed entirely | No action. |
| `agents.yaml` schema | New optional `display_name` field, new optional `provider` field | Add fields if desired. Configs without them continue to work. |

---

## Upgrade Instructions

**From v0.3.0:**

```bash
# 1. Pull the latest code
git pull origin main

# 2. Reinstall with updated dependencies
pipx install -e .

# 3. (Recommended) Re-run onboard to pick up new provider / MCP options
pillywiggins onboard

# 4. Rebuild and restart
docker compose down
docker compose up -d --build
```

**Health check after upgrade:**

```bash
docker compose ps          # All services should show Up / healthy
docker compose logs puck --tail 5   # Confirm no startup errors
```

**If you use Claude skills:**

```bash
pillywiggins import-skills --source ~/claude-skills/ --output skills/
```

**If you had custom prompt injection patterns** in any local config — those patterns no longer exist. The new `PromptSanitizer` uses structural heuristics only. No migration needed unless you were relying on keyword blocking for custom use cases.

**Database schema:** No migration required. v0.4.0 uses the same schema as v0.3.0.

---

For detailed operations guidance, see [`docs/OPS-RUNBOOK.md`](OPS-RUNBOOK.md).  
For troubleshooting, see [`docs/TROUBLESHOOTING.md`](TROUBLESHOOTING.md).
