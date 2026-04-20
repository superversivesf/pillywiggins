# Getting Started with Pillywiggins

## Prerequisites

- **Docker** — for running agents and infrastructure
- **pipx** — for installing the CLI (`apt install pipx` or `brew install pipx`)
- **Telegram bot token** — create a bot via [@BotFather](https://t.me/BotFather)

## Setup

```bash
# 1. Clone
git clone https://github.com/superversivesf/pillywiggins.git
cd pillywiggins

# 2. Install CLI
pipx install -e .

# 3. Run the onboard wizard
pillywiggins onboard

# 4. Deploy
docker compose up -d --build
```

## The Onboard Wizard

Running `pillywiggins onboard` gives you an interactive menu:

- **Add agent** — walks you through creating a new agent
- **Reconfigure agent** — change settings for an existing agent
- **Remove agent** — remove an agent from all config files
- **Start/restart agents** — rebuild and restart Docker services

### Adding a new agent

The wizard walks you through these steps in order:

1. **Personality** — choose from 31 personality YAMLs (Puck, Bramblethorn, Ember, etc.)
2. **Channel** — Telegram (Discord/Slack coming soon)
3. **Agent ID** — defaults to the personality name, you can override
4. **Telegram bot token** — paste from @BotFather (validates via getMe)
5. **Allowed user IDs** — your Telegram user ID, comma-separated, or `all`
6. **Bot chat limit** — max consecutive bot-to-bot replies (0=never, -1=unlimited, default=3)
7. **LLM provider** — Ollama, Ollama Cloud, or OpenAI-compatible
8. **Model** — polled from your provider, browse with arrow keys
9. **Review** — confirm everything looks right

After confirming, the wizard writes to:
- `.env` — bot token, LLM API key
- `agents.yaml` — agent definition (personality, channel, allowed users, LLM config)
- `docker-compose.yaml` — agent Docker service

Then it asks if you want to build and start services now.

### Configuring your first agent (puck)

The repo ships with a `puck` agent as an example. To set it up:

1. Run `pillywiggins onboard`
2. Choose **Reconfigure agent** → select **puck**
3. Enter your Telegram bot token and allowed user IDs
4. Rebuild: `docker compose up -d --build`

### Per-agent LLM providers

Each agent can have its own LLM provider and model. When adding a second agent, the wizard defaults to the first agent's LLM config. You can override to use a different provider (e.g., puck uses local Ollama, wormwood uses Ollama Cloud).

## Configuration Files

These files are **gitignored** — your local config is never committed:

| File | Purpose | Created from |
|------|---------|-------------|
| `.env` | Secrets (tokens, API keys) | `env.example` |
| `agents.yaml` | Agent definitions | `agents.yaml.example` |
| `docker-compose.yaml` | Docker services | `docker-compose.yaml.example` |

All three are created automatically from `.example` templates on first run of `pillywiggins onboard`.

## LLM Configuration

### Local Ollama (default)

The default `LLM_BASE_URL` is `http://host.docker.internal:11434` — this lets Docker containers reach Ollama running on the host machine. If you're running Ollama locally:

1. Install [Ollama](https://ollama.ai)
2. Pull a model: `ollama pull qwen3.5:8b`
3. Ollama runs on port 11434 by default

### Ollama Cloud

Set in the wizard or edit `.env`:

```
LLM_PROVIDER=openai
LLM_BASE_URL=https://ollama.com/v1
LLM_API_KEY=your_ollama_api_key
MODEL_NAME=qwen3.5:9b
```

Get an API key from [ollama.com/settings/keys](https://ollama.com/settings/keys).

### Other OpenAI-compatible providers

Groq, Together, OpenAI, etc:

```
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=your_api_key
MODEL_NAME=llama-3.3-70b-versatile
```

## Telegram Setup

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` — choose a name and username
3. Copy the bot token (format: `123456789:ABCdefGHI...`)
4. Paste it into the onboard wizard or `.env`

### Finding your Telegram user ID

1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. It replies with your user ID
3. Use this as `allowed_user_ids` to restrict access to yourself

### Multi-agent groups

To let agents talk to each other in a Telegram group:

1. Add all agent bots to a Telegram group
2. Each agent uses per-user conversation context in groups
3. Set `bot_chat_limit` per agent to control bot-to-bot conversation depth

## Docker Commands

```bash
# Build and start everything
docker compose up -d --build

# View logs for a specific agent
docker compose logs -f wormwood

# Stop everything
docker compose down

# Stop and wipe data (resets Postgres, Redis, NATS)
docker compose down -v
```

## Troubleshooting

### "You are not authorized to use this bot"

Check `agents.yaml` — the `allowed_user_ids` field must be set to `all` or your Telegram user ID. Then rebuild: `docker compose up -d --build`.

### "Connection error" when agent tries to respond

The Docker container can't reach the LLM provider. Check:
- If using local Ollama: `LLM_BASE_URL` must be `http://host.docker.internal:11434` (not `localhost`)
- If using Ollama Cloud: check your API key and network access
- Verify with: `docker compose exec <agent_id> curl -s http://host.docker.internal:11434/api/tags`

### "externally-managed-environment" when installing

Use `pipx install -e .` instead of `pip install -e .`. pipx handles venv isolation automatically. Install pipx with `apt install pipx` (Debian/Ubuntu) or `brew install pipx` (macOS).

### Changes to agents.yaml or docker-compose.yaml not taking effect

Rebuild the containers: `docker compose up -d --build`. Config files are mounted read-only at container start.

### Reset everything

```bash
# Remove all containers, volumes, and local config
docker compose down -v
rm .env agents.yaml docker-compose.yaml
pillywiggins onboard   # start fresh
```