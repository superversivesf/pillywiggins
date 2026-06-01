# Pillywiggins

**A council of AI agents, not a chatbot with multiple faces.**

Each agent has its own personality, private memory, and communication channel. They share a common noticeboard but keep their own notebooks. One crashes? The others keep working.

## Why Pillywiggins?

### The problem with single-agent AI assistants

A single chatbot — whether it's ChatGPT, Claude, or a local model — is one personality talking everywhere. Slack DMs, Discord servers, email threads: same voice, same memory, same biases. If you want different tones for different contexts, you're switching accounts or writing custom system prompts for every conversation.

Multi-agent frameworks like CrewAI and LangGraph promise agent teams, but they're designed for task orchestration — decomposing a goal into subtasks and farming them out. They're batch processors, not always-on companions. And they don't solve memory isolation: your Slack conversations bleed into your Discord agent's context.

### What Pillywiggins does differently

**True council, not a committee.** Each agent runs as its own process with its own personality YAML, private memory sandboxed at the database level, and its own cron schedule. A bug in Puck's Telegram handler can't take down Ariel on Slack. What you told Puck in private DM stays in Puck's private memory — Ariel literally can't read it.

**Every agent has a voice.** Choose from 90+ personality templates across 10 themes: a fairy court, a starship bridge crew, a tavern, a workshop, a medical clinic — or write your own. Each personality defines tone, traits, and behavior, not just a name.

**Agents build their own tools — with you.** Tell an agent "build me a tool that checks if a website is up." It drafts the Python, writes tests, runs them in a sandbox, and shows you the results. You iterate, approve, and the skill is shared with every agent automatically. No IDE, no deployment pipeline, no MCP server to configure. This is a first-class feature, not a future roadmap item.

**No provider lock-in.** 9 LLM providers supported — Ollama (local), OpenAI, Groq, Together, OpenRouter, vLLM, LiteLLM, and custom OpenAI-compatible endpoints. Swap per agent during onboarding. Puck can run on your RTX GPU while Wormwood uses OpenRouter's free tier.

**Runs at home. Full stop.** No cloud accounts, no API quotas, no data leaving your machine. One `docker compose up` starts everything: agents, PostgreSQL, Redis, NATS. Connects to your local Ollama. Your Discord token. Your Slack bot. Your data, your hardware.

### Comparison

|  | Single Chatbot | CrewAI / LangGraph | Pillywiggins |
|--|:---:|:---:|:---:|
| Multiple personalities | One per account | Task-roles | 90+ YAML templates |
| Memory isolation | None | Thread-based | Database-enforced (RLS) |
| Always-on agents | One session | Batch-only | Persistent processes |
| Agent-built skills | No | No | Yes — collaborative |
| Per-agent schedules | No | No | Yes — cron in personality YAML |
| Runs locally | Varies | Cloud-biased | `docker compose up` |
| Multi-channel | One | N/A | Discord, Slack, Telegram, Matrix, Email |
| Prompt injection defense | Varies | None | 3-layer (input, output, memory) |

### Who is this for?

**Homelabbers and self-hosters** who want AI companions running on their own hardware — no cloud subscription, no data leaving the house.

**Families and shared houses** where multiple people each have their own agent. Mom talks to Sunflower on Telegram; Dad talks to Barkeep on Discord. The agents share skills and council memory behind the scenes but keep private conversations private. Each agent learns its own user's preferences without cross-contamination.

**Tinkerers** who want agents that grow over time. The skill library expands as you and your agents build tools together. What starts as "check if a website is up" becomes a personal toolbox of 20 utilities your agents built for you.

### Channels

| Channel | Status |
|---------|--------|
| Telegram | Stable, well-tested |
| Discord | Adapter implemented |
| Slack | Adapter implemented |
| Matrix | Adapter implemented |
| Email | Adapter implemented |

All five adapters produce the same internal `UnifiedMessage` format — the agent brain doesn't know or care which channel a message came from. Telegram is the most battle-tested; other channels need real-world mileage.

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

## More Features

**MCP server support.** Connect external tools via the Model Context Protocol — filesystem access, GitHub management, Brave Search, or any MCP-compatible server. Configured globally via `pillywiggins onboard`, shared across all agents. See [docs/MCP.md](docs/MCP.md).

**Claude skill import.** Already have Claude skills? Import them directly:

```bash
pillywiggins import-skills --source path/to/skill.md --output skills/
```

**Display name override.** Give agents a different display name than their personality YAML — set during onboarding.

### Personality themes

90+ personalities across 10 themes, all YAML-driven:

| Theme | Directory | Flavor |
|-------|-----------|--------|
| Fey Court | `fey_court/` | Mischievous fairies, gatekeepers, healers |
| Starship Bridge | `bridge/` | Chief engineer, science officer, counselor |
| Tavern | `tavern/` | Barkeep, bard, alchemist, rumormonger |
| Workshop | `workshop/` | Foreman, inspector, fixer, scout |
| Clinic | `clinic/` | Therapist, coach, nutritionist, pharmacist |
| Study | `study/` | Historian, editor, skeptic, synthesist |
| Kitchen | `kitchen/` | Chef, forager, taster, host |
| Studio | `studio/` | Critic, curator, muse, director |
| Ship | `ship/` | Captain, navigator, lookout, boatswain |
| Defaults | `_defaults/` | Per-channel sensible defaults |

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