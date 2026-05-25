# Pillywiggins

**A council of AI agents, not a chatbot with multiple faces.**

Each agent has its own personality, private memory, and communication channel. They share a common noticeboard (council memory) but keep their own notebooks. One crashes? The others keep working.

## Quick Start

```bash
# 1. Clone
git clone https://github.com/superversivesf/pillywiggins.git
cd pillywiggins

# 2. Install (requires pipx — apt install pipx or brew install pipx)
pipx install -e .

# 3. Configure agents (interactive wizard)
pillywiggins onboard

# 4. Deploy
docker compose up -d --build
```

See [ONBOARD.md](ONBOARD.md) for detailed setup instructions, LLM configuration, and troubleshooting.

## View Logs

Docker Compose v2 provides unified log viewing — similar to how Kubernetes aggregates pod container logs. All services' output is interleaved, color-coded by service, and followable in real time.

### Basic unified log viewing

```bash
# Follow all services (like kubectl logs -f for a pod)
docker compose logs -f
```

This streams output from **every** service (agents, Postgres, Redis, NATS) interleaved in one terminal. Docker Compose v2 color-codes each service automatically, so you can tell which agent said what at a glance.

### Specific services

```bash
# Follow only certain services
docker compose logs -f puck puck-discord nats

# One agent's logs
docker compose logs -f wormwood
```

### Tail recent output

```bash
# Last 100 lines across all services, then follow
docker compose logs -f --tail=100

# Last 50 lines from a specific agent, no follow
docker compose logs --tail=50 wormwood
```

### Timestamps

```bash
# Show Docker timestamps on every line
docker compose logs -f -t
```

This adds a UTC timestamp prefix to each line. Useful when correlating events across services.

### Filtering and searching

```bash
# Grep for errors across all services
docker compose logs --tail=500 | grep -i error

# Grep for a specific agent's LLM calls
docker compose logs --tail=1000 wormwood | grep -i "llm\|model\|completion"

# Search council memory broadcasts
docker compose logs --tail=500 | grep -i "council\|broadcast"

# Find agent startup messages
docker compose logs --tail=200 | grep -i "started\|ready\|connected"

# Filter errors from infrastructure (not agents)
docker compose logs --tail=500 postgres redis nats | grep -i error
```

### Dumping to a file

```bash
# Export all logs for analysis or sharing
docker compose logs --tail=5000 > pillywiggins-logs.txt
```

> **Note:** Docker Compose v2 automatically color-codes output by service name. If you pipe to `grep` or redirect to a file, the color codes are stripped — you'll see plain text with the service name as a prefix on each line.

## Documentation

- [ONBOARD.md](ONBOARD.md) — Setup, configuration, and troubleshooting
- [docs/pillywiggins-overview-v2.md](docs/pillywiggins-overview-v2.md) — Architecture, design decisions, and how everything fits together

## Features

### Multi-provider LLM support

Pillywiggins works with 9 LLM providers out of the box, selectable per-agent during onboarding:

| Provider | Type | Needs API Key |
|----------|------|:---:|
| Ollama | Local, self-hosted | No |
| Ollama Cloud | ollama.com | Yes |
| OpenAI | Cloud | Yes |
| Groq | Fast inference | Yes |
| Together AI | Cloud | Yes |
| OpenRouter | Multi-model gateway | Yes |
| vLLM | Self-hosted inference server | No |
| LiteLLM Proxy | Multi-provider gateway | No |
| Custom | Any OpenAI-compatible API | Optional |

Each agent gets its own LLM config — Puck can use local Ollama while Wormwood uses OpenRouter. The onboard wizard polls your provider for available models so you can browse with arrow keys.

### MCP servers (global tools)

Pillywiggins connects to MCP (Model Context Protocol) servers for shared tools available to all agents. During onboarding (`pillywiggins onboard` → "Configure MCP servers"), you can add stdio or HTTP-based MCP servers — connect a filesystem server for file access, a GitHub server for repo management, or any other MCP-compatible tool. The config is written to `skills/mcp_servers.json` and shared across agents.

### Claude skill import

Bring your existing Claude-style skills into Pillywiggins:

```bash
pillywiggins import-skills --source path/to/skill.md --output skills/
```

This parses `.skill.md` files and converts them to Pillywiggins' Python-native skill format. Point `--source` at a single file or a directory to batch-import.

### Display names

During onboarding, you can give each agent a custom display name that overrides the personality name in conversations — your agents don't have to be called what their personality YAML says.

## Architecture

Every agent runs as its own Docker container with its own Python process, personality YAML, and cron schedule. They share a Docker network and talk through NATS, store memories in PostgreSQL (with row-level security isolation), and cache conversations in Redis. See the [overview doc](docs/pillywiggins-overview-v2.md) for the full picture.

## Security

### Prompt injection defense (3-layer)

Pillywiggins applies a defense-in-depth strategy against prompt injection, recognizing that no single layer is sufficient:

1. **Input sanitization** — Every user message entering the system is scored against structural heuristics (API token format leaks, chat template delimiter injection, Unicode obfuscation). Messages scoring above threshold 40 are replaced with a safe default before reaching the LLM. Normal conversation is never blocked — only structural attack patterns.

2. **Output sanitization** — LLM responses are also sanitized before delivery using the same structural heuristics at a stricter threshold (30). This catches cases where the model is tricked into echoing injected content or leaking sensitive patterns.

3. **Memory sanitization** — All content written to private and council memory passes through the sanitizer. An agent that becomes compromised cannot poison other agents' memories via the shared council.

See `src/pillywiggins/security/prompt_sanitizer.py` for implementation details.

## License

See [LICENSE](LICENSE) for details.