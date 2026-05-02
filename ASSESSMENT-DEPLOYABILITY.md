# Deployability Assessment — Pillywiggins

**Date:** 2026-04-26  
**Auditor:** swarm-worker-deploy-audit  
**Scope:** `docker-compose.yaml.example`, `docker-compose.yaml`, `Dockerfile`, `pyproject.toml`, `env.example`, `agents.yaml.example`, `agents.yaml`, `src/pillywiggins/__main__.py`, `src/pillywiggins/onboard.py`

---

## 1. Services Inventory

### Infrastructure Services (defined in both `.example` and live `docker-compose.yaml`)

| Service | Image | Status | Notes |
|----------|--------|--------|--------|
| **postgres** | `pgvector/pgvector:pg16` | Ready | Includes `pgvector` pre-installed. `scripts/init-db.sql` mounted to `/docker-entrypoint-initdb.d/` for first-run schema creation. Healthcheck defined in `.example`, missing in live `.yaml`. |
| **redis** | `redis:7-alpine` | Ready | Append-only enabled. No healthcheck in live `.yaml`; `.example` has one. |
| **nats** | `nats:2-alpine` | Ready | JetStream enabled (`-js`). Monitoring on `:8222`. No healthcheck in live `.yaml`; `.example` has one. |
| **searxng** | `searxng/searxng:latest` | Ready | SearXNG search instance. `searxng_settings.yml` mounted read-only. Healthcheck present in both. |

### Application Services

| Service | Image/Build | Status | Notes |
|----------|-------------|--------|--------|
| **puck** | `build: .` | Present in live `.yaml` | Single Telegram agent. Overrides Dockerfile CMD with `--agent-id puck`. |
| **puck-discord** | `build: .` | **Only in `.example`** | Hardcoded Discord agent service exists in the template but is removed from the live file. Creates confusion for users referencing `.example`. |

### Omissions

- **Ollama is entirely absent** from `docker-compose.yaml` and `.example`. The default `LLM_BASE_URL=http://host.docker.internal:11434/v1` assumes Ollama is running on the Docker host. There is no service definition, no healthcheck for it, and no fallback if it is unreachable.
- No reverse-proxy or ingress service (e.g., Traefik, Nginx) is defined for multi-agent deployments.

---

## 2. Configuration Gap

### Environment Variables (`env.example`)

The `.env.example` file is comprehensive. It provides defaults for all major subsystems.

| Variable | Provided Default | Risk Level |
|----------|----------------- |------------|
| `DATABASE_URL` | `postgresql://pillywiggins:changeme@postgres:5432/pillywiggins` | Low — matches compose service name. |
| `PG_PASSWORD` | `changeme` | Low — acceptable for local dev. |
| `REDIS_URL` | `redis://redis:6379/0` | Low — matches compose service name. |
| `NATS_URL` | `nats://nats:4222` | Low — matches compose service name. |
| `LLM_PROVIDER` / `LLM_BASE_URL` / `MODEL_NAME` | `ollama` / `http://host.docker.internal:11434/v1` / `qwen3.5:8b` | **High** — depends on external Ollama on host. |
| `TELEGRAM_BOT_TOKEN` / `DISCORD_BOT_TOKEN` | Placeholders | **High** — must be filled for any agent to start. |
| `AGENT_ID` / `CHANNEL` / `PERSONALITY_FILE` | `puck` / `telegram` / `/config/puck.yaml` | Medium — overridden by `agents.yaml` when using `--agent-id`. |
| `ALLOWED_USER_IDS` | Empty (deny all) | Medium — user must set to `all` or specific IDs. |
| `SEARXNG_SECRET` | Empty | Low — SearXNG will use its internal default if empty. |
| `SEARXNG_URL` | `http://searxng:8080` | Low — matches compose service name. |

**Finding:** If `.env` is missing, `docker compose up` will fail to read the `env_file: .env` reference. The `onboard` wizard copies `env.example` → `.env`, but a user skipping onboarding will hit a hard error.

### `agents.yaml.example` Validity

- **Valid YAML:** Yes. It is a straightforward list of agents.
- **Variable expansion:** Uses `${PUCK_TELEGRAM_TOKEN}` which relies on `.env` interpolation. This matches the `env_file` mechanism in Docker Compose.
- **Live `agents.yaml`:** Identical to `.example`. It defines a single Telegram agent (`puck`).

**Finding:** If `agents.yaml` is missing, Docker Compose will create a **directory** at `./agents.yaml` because it is referenced as a bind-mount source. The application inside the container will then fail with a read error (`IsADirectoryError`).

### `docker-compose.yaml.example` vs Live File

| Aspect | `.example` | Live `.yaml` | Issue |
|--------|-----------|-------------|--------|
| Agent services | `puck`, `puck-discord` | `puck` only | `.example` advertises Discord support that the live tool chain does not yet enable. |
| `restart` policy | `unless-stopped` on all services | Only `searxng` has it | Host reboot leaves infrastructure down unexpectedly. |
| Healthchecks | All services have healthchecks | Only `postgres`, `searxng` have healthchecks | Redis/NATS failures will not be detected; `depends_on` conditions are weaker. |
| `depends_on` | `condition: service_healthy` for all deps | `condition: service_started` for redis/nats | Agents may start before redis/nats are actually accepting connections. |
| `HEALTH_PORT` | `8080` on agents | Absent | No healthcheck endpoint is exposed for the agent container in the live file. |

**Finding:** The divergence between `.example` and `docker-compose.yaml` is a configuration gap. A user manually copying `.example` to `.yaml` will get a different runtime behavior than what the onboard wizard produces.

---

## 3. CLI & Onboarding

### Package Installability (`pyproject.toml`)

- **Build backend:** `hatchling` — standard, works.
- **Entrypoint:** `pillywiggins = "pillywiggins.__main__:main"` — correct.
- **Editable install:** Verified working (`pip3 show pillywiggins` reports editable install at `/Users/jason/Repos/pillywiggins`).
- **CLI test:** `python3 -m pillywiggins --help` succeeds and shows `--channel`, `--agent-id`, and `onboard` subcommand.

### `pillywiggins onboard` Wizard

The wizard (`src/pillywiggins/onboard.py`) is functional code-wise but has UI/UX limitations:

- **Channel support:** Only **Telegram** is selectable. Discord and Slack choices are `disabled=True`.
- **Token validation:** It calls Telegram Bot API (`getMe`) to validate tokens — good UX.
- **LLM polling:** It calls `list_models()` (from `adapters/models.py`) to let the user pick from available models. Good UX, but will fail silently if Ollama is not running.
- **Config generation:** It writes three files:
  1. `.env` (appends token + per-agent LLM API keys)
  2. `agents.yaml` (appends agent entry)
  3. `docker-compose.yaml` (appends service block)
- **Post-config:** It optionally runs `docker compose up -d --build`.

**Findings:**
1. The wizard assumes the **host** has `docker compose` CLI available. In a headless/CI environment, this subprocess call will fail with `FileNotFoundError` and print a fallback message.
2. The wizard does **not** validate that Ollama is reachable or that the selected model is pulled. A first-time user can complete onboarding and then immediately face a non-working bot because the LLM backend is missing.
3. If `agents.yaml` or `docker-compose.yaml` exist, the wizard appends to them. There is no cleanup logic, so repeated runs can leave stale/duplicate entries if the user changes their mind.

---

## 4. First-Time Deploy Blockers

### CRITICAL

| # | Blocker | Impact | Mitigation |
|---|----------|--------|-----------|
| 1 | **Missing `.env` causes Docker Compose failure** | `env_file: .env` is referenced in compose for the agent service. If `.env` does not exist, `docker compose up` errors out. | Ensure `env.example` is copied to `.env` before any compose command. The onboard wizard does this, but users skipping it will fail. |
| 2 | **Missing `agents.yaml` causes directory mount** | Bind mount `./agents.yaml:/app/agents.yaml:ro` creates a directory if the file is absent. The app then crashes trying to read a directory as YAML. | Ensure `agents.yaml.example` is copied to `agents.yaml` before compose. |
| 3 | **Ollama is external and unverified** | No Ollama service in compose. Default `LLM_BASE_URL` points to `host.docker.internal:11434`. If Ollama is not installed, running, or reachable, the agent will fail on first message. | Document prerequisite: `ollama serve` must be running on the host, and the selected model must be pulled (`ollama pull qwen3.5:8b`). Optionally add an `ollama` service to `docker-compose.yaml`. |

### HIGH

| # | Blocker | Impact | Mitigation |
|---|----------|--------|-----------|
| 4 | **`.example` vs live compose drift** | `.example` has `puck-discord`, extra healthchecks, and `restart` policies that the live file lacks. A user referencing `.example` for manual setup gets a different topology than the onboard wizard generates. | Regenerate `docker-compose.yaml.example` to match the minimal live structure, or remove agent services from `.example` so it only shows infrastructure. |
| 5 | **Discord/Slack advertised but disabled** | `.env.example` defines `PUCK_DISCORD_TOKEN`. `docker-compose.yaml.example` includes a `puck-discord` service. The onboard UI disables these channels. Users will expect Discord support and not get it. | Update `.env.example` to remove Discord placeholders until the adapter is fully wired in the wizard. Remove `puck-discord` from `.example` or enable it in the wizard. |
| 6 | **Weak `depends_on` in live compose** | `redis` and `nats` use `condition: service_started` instead of `service_healthy`. Agents may start and crash-loop before redis/nats accept connections. | Add healthchecks to redis/nats in `docker-compose.yaml` and use `condition: service_healthy`. |

### MEDIUM

| # | Blocker | Impact | Mitigation |
|---|----------|--------|-----------|
| 7 | **Onboard wizard appends without deduplication** | Running the wizard twice with the same agent ID appends duplicate service blocks unless the user chooses "Replace". | Add pre-flight check in wizard to warn if ID already exists before asking questions. |
| 8 | **No `restart` policy in live compose for infra** | A host reboot leaves PostgreSQL, Redis, NATS, and the agent stopped. | Add `restart: unless-stopped` to all infrastructure and agent services in `docker-compose.yaml`. |
| 9 | **`personality_file` default mismatch risk** | `PERSONALITY_FILE=/config/puck.yaml` in `.env.example`, but the wizard creates agents with arbitrary personality filenames. If the selected personality file does not exist under `./personalities/`, the container will fail to start. | Add a validation step in the wizard that checks `PERSONALITIES_DIR` for the selected file before writing configs. |
| 10 | **`skills/registry.json` is empty** | The skills directory contains `.py` files, but `registry.json` is `{"skills": []}`. If `SkillRegistry` relies on `registry.json` for the manifest, no skills will be loaded. | Verify `SkillRegistry.load_all()` scans the filesystem in addition to (or instead of) `registry.json`. Document expected behavior. |

### LOW

| # | Blocker | Impact | Mitigation |
|---|----------|--------|-----------|
| 11 | **`uv.lock` absent** | Dockerfile does `COPY pyproject.toml uv.lock* ./`. `uv` will resolve dependencies dynamically. Slightly less reproducible, but not a deploy blocker. | Optionally generate and commit `uv.lock`. |
| 12 | **`extra_hosts` syntax** | `extra_hosts: ["host.docker.internal:host-gateway"]` is valid in Docker Compose v2+, but older versions may not resolve `host-gateway`. | Document minimum Docker Engine version (≥ 20.10). |
| 13 | **SearXNG secret** | `SEARXNG_SECRET` defaults to empty in `.env.example`. SearXNG will start but may warn. | Provide a generated default or document that any non-empty string is acceptable. |

---

## Summary

- **Total services defined:** 5 infrastructure + up to 2 application agents (`puck`, `puck-discord`).
- **CLI entrypoint:** Works (`python3 -m pillywiggins --help` OK).
- **Onboard wizard:** Generates valid configs but only supports Telegram and does not verify Ollama reachability.
- **Critical blockers for first `docker compose up`:**
  1. `.env` must exist (copy from `env.example`).
  2. `agents.yaml` must exist (copy from `agents.yaml.example`).
  3. Ollama must be running externally with the chosen model pulled.
- **Recommended immediate actions:**
  1. Synchronize `docker-compose.yaml.example` with the live `docker-compose.yaml` (or remove agent services from `.example`).
  2. Add `restart: unless-stopped` and healthchecks to all infrastructure services in the live compose file.
  3. Document Ollama prerequisite prominently in onboarding output.
  4. Verify `SkillRegistry` behavior with an empty `registry.json`.
