# Pillywiggins: Detailed Design & Roadmap v2

**Version 2.1 — April 2026**

---

## 1. Architecture

The entire system is Docker containers wired together with Docker Compose. Each agent is a standalone Python process that directly connects to PostgreSQL, Redis, and NATS using standard async libraries. No sidecars, no service meshes, no control planes, no Kubernetes.

### docker-compose.yaml

```yaml
services:
  # --- Infrastructure ---
  postgres:
    image: pgvector/pgvector:pg16
    volumes: [pgdata:/var/lib/postgresql/data]
    environment:
      POSTGRES_DB: pillywiggins
      POSTGRES_PASSWORD: ${PG_PASSWORD}
    healthcheck:
      test: pg_isready -U postgres

  redis:
    image: redis:7-alpine
    volumes: [redisdata:/data]
    command: redis-server --appendonly yes

  nats:
    image: nats:2-alpine
    command: -js    # Enable JetStream for durable messaging

  ollama:
    image: ollama/ollama
    volumes: [ollama_models:/root/.ollama]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  # --- Agents (same image, different config) ---
  discord-agent:
    build: .
    command: python -m pillywiggins --channel discord
    env_file: .env
    environment:
      AGENT_ID: discord-agent
      PERSONALITY_FILE: /config/discord.yaml
    volumes:
      - ./personalities:/config:ro
      - skills:/app/skills              # shared skill volume
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_started }
      nats: { condition: service_started }
      ollama: { condition: service_started }

  slack-agent:
    build: .
    command: python -m pillywiggins --channel slack
    env_file: .env
    environment:
      AGENT_ID: slack-agent
      PERSONALITY_FILE: /config/slack.yaml
    volumes:
      - ./personalities:/config:ro
      - skills:/app/skills
    depends_on: [postgres, redis, nats, ollama]

  # telegram-agent, matrix-agent, email-agent follow the same pattern

volumes:
  pgdata:
  redisdata:
  ollama_models:
  skills:           # shared volume mounted into every agent container
```

Every agent uses the **same Docker image** with different arguments and config. The `skills` volume is mounted into every agent container so skills built by one agent are immediately visible to all others.

---

## 2. The Agent Runtime

### Core agent class (pseudocode)

```
class PillywigginAgent:

    initialise(agent_id, channel_type, personality_path):
        self.agent_id = agent_id
        self.channel_type = channel_type
        self.lock = AsyncLock()           # one message at a time

        self.personality = load_yaml(personality_path)

        # Direct connections — no middleware
        self.db = AsyncPGPool(
            dsn = env("DATABASE_URL"),
            on_connect = SET_RLS(agent_id)   # sets app.agent_id on every connection
        )
        self.redis = RedisClient(env("REDIS_URL"))
        self.nats = NATSClient(env("NATS_URL"))

        # Skill registry — discovers available skills from disk
        self.skill_registry = SkillRegistry("/app/skills")

        # PydanticAI agent brain
        self.brain = PydanticAI.Agent(
            model = "ollama:qwen3.5-8b",
            system_prompt = self.build_system_prompt(),
        )
        # Register built-in tools
        self.brain.register_tool(self.recall_private_memory)
        self.brain.register_tool(self.query_council_memory)
        self.brain.register_tool(self.share_to_council)
        self.brain.register_tool(self.build_skill)
        self.brain.register_tool(self.test_skill)
        self.brain.register_tool(self.deploy_skill)
        self.brain.register_tool(self.list_skills)
        # Dynamically register all deployed skills
        for skill in self.skill_registry.list_skills():
            self.brain.register_tool(skill.as_tool())

        # Per-agent scheduler
        self.scheduler = setup_scheduler(agent_id, self.personality, self.redis)


    async handle_message(unified_message):
        async with self.lock:
            # Assemble context
            history = await self.redis.get_conversation(self.agent_id)
            private_ctx = await self.search_private_memory(unified_message.content)
            council_ctx = await self.search_council_memory(unified_message.content)

            deps = AgentDeps(
                agent_id = self.agent_id,
                personality = self.personality,
                db = self.db,
                skill_registry = self.skill_registry,
                history = history,
                private_context = private_ctx,
                council_context = council_ctx,
            )

            result = await self.brain.run(
                user_prompt = unified_message.content,
                deps = deps,
                message_history = history,
            )

            # Persist
            await self.redis.save_conversation(self.agent_id, result.all_messages())
            await self.save_to_private_memory(unified_message, result)

            return result.output
```

### The message lock

`asyncio.Lock()` ensures one message is processed at a time per agent. If a second message arrives while the first is processing, it queues and waits. This is correct for conversational agents — you don't want two messages interleaving their state reads and writes.

Each agent is a separate process, so Discord's lock has zero effect on Slack's processing. They're independent.

### RLS connection setup

Every time the connection pool hands out a database connection, it runs:

```sql
SET app.agent_id = 'discord-agent';
```

Combined with the RLS policy, this means every query is automatically scoped. The agent code never needs `WHERE agent_id = ...` — the database enforces it regardless of what SQL runs.

```
async on_connect(connection):
    await connection.execute("SET app.agent_id = $1", self.agent_id)

pool = asyncpg.create_pool(dsn=DATABASE_URL, init=on_connect)
```

---

## 3. The Skills System

### What is a skill?

A skill is a Python file with a standard shape:

```python
# skills/check_website.py
"""Check if a website is reachable and measure response time."""

SKILL_META = {
    "name": "check_website",
    "description": "Check if a URL is reachable and return its status code and response time",
    "author": "discord-agent",
    "version": "1.0",
    "created": "2026-04-13T10:30:00Z",
    "parameters": {
        "url": {"type": "string", "description": "The URL to check"},
        "timeout": {"type": "number", "description": "Timeout in seconds", "default": 10},
    },
    "returns": "dict with status_code, response_time_ms, and reachable boolean",
    "network_access": True,      # explicitly declares network need
}

import aiohttp

async def run(url: str, timeout: float = 10) -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            start = time.monotonic()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                elapsed = (time.monotonic() - start) * 1000
                return {
                    "reachable": True,
                    "status_code": resp.status,
                    "response_time_ms": round(elapsed, 1),
                }
    except Exception as e:
        return {
            "reachable": False,
            "status_code": None,
            "response_time_ms": None,
            "error": str(e),
        }
```

Every skill has:
- A `SKILL_META` dict describing what it does, who made it, and what it needs
- A `run()` function that does the work
- Declared permissions (`network_access`, `file_access`, etc.)

### The collaborative build flow

Building a skill is a conversation between the user and an agent. The flow has four states: **draft → test → review → deployed**.

```
                    User feedback
                   ┌────────────┐
                   ▼            │
  User request → DRAFT ──► TEST ──► REVIEW ──► DEPLOYED
                   ▲            │       │
                   └────────────┘       │
                    Test failures       │
                                   User rejects
                                   (back to DRAFT)
```

**Step 1 — DRAFT**: User asks for a skill. The agent writes the code and shows it.

```
User:   "Can you build a tool that rolls dice? Like 2d6 or 3d20?"

Agent:  "Here's what I've got:"

        Name: roll_dice
        Description: Roll dice in NdS format (e.g. 2d6, 3d20)
        Input: notation (string like "2d6")
        Output: { rolls: [3, 5], total: 8 }

        [shows the Python code]

        Want me to test it, or would you like changes first?
```

**Step 2 — TEST**: The agent generates test cases and runs them in a sandbox.

```
Agent:  "Running tests..."

        ✅ roll_dice("1d6")  → rolls=[4], total=4  (valid: 1-6 range)
        ✅ roll_dice("2d20") → rolls=[13,7], total=20  (valid: 1-20 range)
        ✅ roll_dice("0d6")  → error: "Must roll at least 1 die"
        ✅ roll_dice("abc")  → error: "Invalid notation"
        ❌ roll_dice("1d0")  → got {rolls: [0], total: 0}, expected error

        4/5 tests passed. The d0 edge case isn't handled.
        Want me to fix it?
```

**Step 3 — REVIEW**: User looks at the code and test results, provides feedback.

```
User:   "Fix the d0 case, and also add a max of 100 dice so
         nobody can ask for 999999d6"

Agent:  [revises code, re-runs tests]

        ✅ All 7 tests passed (including d0 and 101d6 rejection).
        Here's the final code: [shows it]
        Ready to deploy?
```

**Step 4 — DEPLOY**: User approves, agent saves the skill and announces it.

```
User:   "Looks good, deploy it."

Agent:  ✅ Skill "roll_dice" saved to skills/roll_dice.py
        ✅ Registry updated
        ✅ Announced to council — all agents can now use roll_dice

        Try it: "roll 3d8"
```

### The skill registry

The registry is a JSON file on the shared volume:

```json
// skills/registry.json
{
  "skills": [
    {
      "name": "check_website",
      "file": "check_website.py",
      "description": "Check if a URL is reachable and return status code and response time",
      "author": "discord-agent",
      "version": "1.0",
      "created": "2026-04-13T10:30:00Z",
      "permissions": ["network_access"]
    },
    {
      "name": "roll_dice",
      "file": "roll_dice.py",
      "description": "Roll dice in NdS format (e.g. 2d6, 3d20)",
      "author": "discord-agent",
      "version": "1.1",
      "created": "2026-04-13T11:45:00Z",
      "permissions": []
    }
  ]
}
```

### The SkillRegistry class (pseudocode)

```
class SkillRegistry:

    initialise(skills_dir):
        self.skills_dir = skills_dir      # /app/skills
        self.skills = {}                  # name → loaded module
        self.load_all()
        self.watch_for_changes()          # inotify / polling

    load_all():
        registry = read_json(self.skills_dir / "registry.json")
        for entry in registry["skills"]:
            module = import_file(self.skills_dir / entry["file"])
            self.skills[entry["name"]] = Skill(
                name = entry["name"],
                meta = module.SKILL_META,
                run_fn = module.run,
                permissions = entry["permissions"],
            )

    list_skills() -> list[Skill]:
        return list(self.skills.values())

    get_skill(name) -> Skill:
        return self.skills[name]

    register_skill(name, code, meta):
        """Save a new skill to disk and update the registry."""
        filepath = self.skills_dir / f"{name}.py"
        write_file(filepath, code)
        registry = read_json(self.skills_dir / "registry.json")
        registry["skills"].append({
            "name": name,
            "file": f"{name}.py",
            "description": meta["description"],
            "author": meta["author"],
            "version": meta["version"],
            "created": now_iso(),
            "permissions": meta.get("permissions", []),
        })
        write_json(self.skills_dir / "registry.json", registry)
        # Reload
        self.load_all()

    watch_for_changes():
        """Watch the skills directory for new/changed files.
           When another agent deploys a skill, this agent picks it up."""
        # Use watchdog or simple polling every 10 seconds
        on_change -> self.load_all()


class Skill:
    """Wraps a loaded skill module for use as a PydanticAI tool."""

    as_tool():
        """Return a callable that PydanticAI can register as a tool."""
        # Returns a function with the right signature and docstring
        # that calls self.run_fn inside the sandbox
        return sandboxed_wrapper(self.run_fn, self.permissions)
```

### Sandboxing skill execution

Skills are user-approved but still LLM-generated code. They run in a restricted subprocess:

```
async run_skill_sandboxed(skill, arguments):
    """Execute a skill in a restricted subprocess."""
    
    # Build the execution script
    script = f"""
import json, sys
sys.path.insert(0, '/app/skills')
from {skill.name} import run
import asyncio
result = asyncio.run(run(**json.loads(sys.argv[1])))
print(json.dumps(result))
"""
    
    process = await create_subprocess(
        ["python", "-c", script, json.dumps(arguments)],
        timeout = 30,                    # hard kill after 30 seconds
        cwd = "/tmp",                    # no access to app code
        env = restricted_env(skill.permissions),
    )
    
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        return {"error": stderr}
    return json.loads(stdout)


def restricted_env(permissions):
    """Build environment variables for the sandbox."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if "network_access" not in permissions:
        # Could use network namespace isolation in future
        pass
    return env
```

For Phase 1, subprocess isolation with timeouts is sufficient. Later, this can be upgraded to Docker-in-Docker or a dedicated sandbox container for stronger isolation.

### How skills become tools

When the agent starts (or when the skills directory changes), every skill is wrapped and registered with PydanticAI:

```
for skill in self.skill_registry.list_skills():
    
    async def tool_wrapper(**kwargs):
        return await run_skill_sandboxed(skill, kwargs)
    
    # Set the function name and docstring so PydanticAI
    # can describe it to the LLM
    tool_wrapper.__name__ = skill.name
    tool_wrapper.__doc__ = skill.meta["description"]
    
    self.brain.register_tool(tool_wrapper)
```

The LLM sees these exactly like built-in tools — it gets the name, description, and parameter schema, and can decide to call them during any conversation.

### Council announcement on deploy

When a skill is deployed, the agent publishes a council message:

```
async announce_skill(nats, agent_id, skill_name, description):
    await nats.publish("council.broadcast", {
        "type": "skill_deployed",
        "from": agent_id,
        "skill": skill_name,
        "description": description,
        "timestamp": now(),
    })
```

Other agents pick this up via their NATS subscription and reload their skill registry.

---

## 4. Per-Agent Cron System

Each agent runs its own instance of APScheduler with a Redis-backed job store. This means:

- **Isolation**: Discord's cron jobs don't interfere with Email's
- **Persistence**: Jobs survive container restarts (stored in Redis, not memory)
- **No duplication**: `replace_existing=True` prevents duplicate jobs on restart
- **Standard cron syntax**: Same format you'd use in crontab

### Setup (pseudocode)

```
setup_scheduler(agent_id, personality, redis_client):
    scheduler = AsyncIOScheduler()
    
    # Redis job store — prefixed by agent ID so agents don't clash
    scheduler.add_jobstore(
        RedisJobStore(redis_client, jobs_key=f"apscheduler:{agent_id}:jobs")
    )
    
    # Load personality-defined schedules
    for task_name, config in personality.get("scheduling", {}).items():
        scheduler.add_job(
            func = run_scheduled_task,
            trigger = CronTrigger.from_crontab(config["cron"]),
            id = f"{agent_id}:{task_name}",
            args = [agent_id, task_name, config],
            replace_existing = True,
            timezone = config.get("timezone", "UTC"),
            misfire_grace_time = 300,     # 5 min grace if container was down
        )
    
    # Built-in heartbeat for health monitoring
    scheduler.add_job(
        func = heartbeat,
        trigger = IntervalTrigger(minutes=30),
        id = f"{agent_id}:heartbeat",
        replace_existing = True,
    )
    
    scheduler.start()
    return scheduler
```

### How scheduled tasks execute

A cron job triggers the same `handle_message` flow as a user message, but with a synthetic message:

```
async run_scheduled_task(agent_id, task_name, config):
    synthetic_message = UnifiedMessage(
        message_id = generate_id(),
        channel_type = "scheduled",
        sender_id = "system",
        sender_name = "Scheduler",
        content = config["action"],        # e.g. "Send a cheerful morning greeting"
        is_scheduled = True,
        metadata = {"task_name": task_name},
    )
    
    response = await agent.handle_message(synthetic_message)
    
    # Send the response to the appropriate channel
    if config.get("target_channel"):
        await agent.adapter.send(config["target_channel"], response)
```

This means the agent uses its full brain for scheduled tasks — it can use tools, search memory, consult the council. A "morning greeting" isn't a canned message, it's the agent thinking about what to say based on context.

### Dynamic cron management

Agents can also create cron jobs during conversation:

```
User:   "Puck, remind me to take a break every 2 hours during work days"

Puck:   "Done! I've set up a reminder:"
        Schedule: Every 2 hours, Mon-Fri, 9am-5pm
        Cron: "0 9,11,13,15,17 * * 1-5"
        
        I'll ping you in this channel. Want me to adjust anything?
```

This adds a job to the scheduler at runtime, and since it's backed by Redis, it persists.

---

## 5. Channel Adapters

### Universal message format

```
UnifiedMessage:
    message_id: string           # platform-native ID
    channel_type: enum           # discord | slack | telegram | matrix | email | scheduled
    channel_id: string           # server/channel/room/thread
    sender_id: string            # platform user ID
    sender_name: string          # display name
    content: string              # the actual text
    attachments: list            # files, images
    reply_to: string or null     # if replying to another message
    thread_id: string or null    # thread context
    is_dm: boolean               # private message?
    is_scheduled: boolean        # triggered by cron?
    timestamp: datetime
    raw_metadata: dict           # anything platform-specific
```

### Adapter pattern

```
class BaseAdapter:
    abstract async connect()
    abstract async listen()
    abstract async send(channel_id, content, metadata)
    abstract normalise(platform_event) -> UnifiedMessage

    async on_message(platform_event):
        unified = self.normalise(platform_event)
        response = await self.agent.handle_message(unified)
        await self.send(unified.channel_id, response, unified.raw_metadata)
```

### Platform libraries

| Platform | Library | Connection Mode |
|----------|---------|----------------|
| Discord | `discord.py` v2 | Gateway WebSocket (stays connected) |
| Slack | `slack_bolt` | Socket Mode (no public URL needed) |
| Telegram | `python-telegram-bot` v21 | Polling for dev, webhook for production |
| Matrix | `matrix-nio` | Persistent sync, E2EE optional |
| Email | `imap-tools` + `aiosmtplib` | IMAP IDLE or polling every 30s |

---

## 6. Memory Architecture

### Private memory (PostgreSQL + pgvector + RLS)

```sql
CREATE TABLE private_memory (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        VARCHAR(64) NOT NULL,
    content         TEXT NOT NULL,
    memory_type     VARCHAR(32) DEFAULT 'episodic',
    embedding       vector(768) NOT NULL,
    importance      FLOAT DEFAULT 0.5,
    created_at      TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE private_memory ENABLE ROW LEVEL SECURITY;
CREATE POLICY agent_isolation ON private_memory
    USING (agent_id = current_setting('app.agent_id'))
    WITH CHECK (agent_id = current_setting('app.agent_id'));

CREATE INDEX ON private_memory
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
```

### Council memory (shared, attributed)

```sql
CREATE TABLE council_memory (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contributing_agent  VARCHAR(64) NOT NULL,
    content             TEXT NOT NULL CHECK (length(content) <= 2000),
    tags                TEXT[] NOT NULL DEFAULT '{}',
    embedding           vector(768) NOT NULL,
    message_type        VARCHAR(32) DEFAULT 'insight',   -- insight, skill_announcement, etc.
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON council_memory
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX ON council_memory USING gin (tags);
```

### Conversation cache (Redis, TTL-based)

```
Key:    conversation:{agent_id}
Value:  JSON array of message objects
TTL:    1800 seconds (30 min inactivity)
```

### Embeddings

Generated via Ollama's embedding endpoint using a small model on CPU:

```
async embed(text):
    response = await http_post("http://ollama:11434/api/embed", {
        model: "nomic-embed-text",
        input: text
    })
    return response.embeddings[0]
```

---

## 7. Inter-Agent Communication (NATS)

Direct use of `nats-py` — about 15 lines of setup code:

```
async setup_nats(agent_id):
    nc = await nats.connect("nats://nats:4222")
    js = nc.jetstream()

    await js.add_stream(name="pillywiggins", subjects=["council.>"])

    await js.subscribe("council.broadcast", cb=on_broadcast, durable=agent_id)
    await js.subscribe(f"council.direct.{agent_id}", cb=on_direct, durable=f"{agent_id}-dm")

    return nc, js
```

### Topic structure

```
council.broadcast              — insights and skill announcements
council.direct.{agent_id}     — agent-to-agent private messages
council.memory.updated         — council memory change notifications
council.health                 — heartbeat pings
```

### Handling a council broadcast

```
async on_broadcast(msg):
    data = json.loads(msg.data)
    
    if data["type"] == "skill_deployed":
        # Another agent deployed a skill — reload our registry
        self.skill_registry.load_all()
        log.info(f"Picked up new skill: {data['skill']} from {data['from']}")
    
    elif data["type"] == "insight":
        # Another agent shared knowledge — it's already in council memory,
        # this notification just lets us know it's there
        pass
    
    await msg.ack()
```

---

## 8. Personality System

Each agent's personality is a YAML file mounted into the container:

```yaml
# personalities/discord.yaml
name: "Puck"
archetype: "Mischievous fairy trickster"
tone: "playful, witty, slightly chaotic"
style: "uses emojis freely, loves puns, references internet culture"
response_length: "concise, 1-3 sentences unless asked for more"

additional_instructions: |
  You adore wordplay. You occasionally speak in rhyming couplets
  when excited. You call users 'mortal' affectionately.

scheduling:
  morning_greeting:
    cron: "0 9 * * *"
    action: "Send a cheerful morning greeting to the general channel"
    target_channel: "general"
  fun_fact_friday:
    cron: "0 15 * * 5"
    action: "Share a random interesting fun fact"
    target_channel: "general"
  memory_review:
    cron: "0 3 * * 0"
    action: "Review and consolidate old memories, discard trivial ones"
```

To change personality: edit the YAML, then `docker compose restart discord-agent`. No rebuild needed.

---

## 9. Security

### Memory isolation (PostgreSQL RLS)

The most important security boundary. Every agent connects with `SET app.agent_id = '...'`. The RLS policy means `SELECT * FROM private_memory` only returns that agent's rows. A compromised agent cannot read another agent's data.

### Council memory write validation

```
validate_council_write(agent_id, content, tags):
    REJECT if length(content) > 2000
    REJECT if any tag not in ALLOWED_TAGS
    REJECT if agent has written > 10 entries in the last hour
    REJECT if cosine_similarity(content, existing_entries) > 0.95
    ACCEPT
```

### Skill execution sandboxing

Skills run in restricted subprocesses with:
- 30-second timeout (hard kill)
- Working directory set to `/tmp`
- Restricted environment variables
- No access to the main application code
- Permissions declared in SKILL_META (network_access, file_access)

User approval is required before any skill is deployed. The agent cannot autonomously add code to the system.

### Secrets

All secrets in `.env` (not committed to Git). Docker Compose loads them automatically:

```env
PG_PASSWORD=strong_random_password
DISCORD_TOKEN=your_discord_bot_token
SLACK_BOT_TOKEN=xoxb-your-slack-token
TELEGRAM_TOKEN=your_telegram_bot_token
# ... etc
```

### Rate limiting

Token bucket per agent — max 10 LLM calls per minute by default. Prevents runaway tool loops.

---

## 10. Observability

### Phase 1: Structured logging only

```
log.info("message_processed", {
    agent_id: "discord-agent",
    sender: "Jason",
    processing_time_ms: 1247,
    tools_called: ["roll_dice"],
    tokens_used: 342,
})
```

Follow logs with `docker compose logs -f discord-agent`.

### Health endpoint

Each agent exposes `/healthz` that checks PostgreSQL, Redis, NATS, and Ollama connectivity. Docker Compose uses this for healthcheck/restart logic.

### Later: Prometheus + Grafana

Add monitoring containers when the system is stable. Not a launch requirement.

---

## 11. Project Structure

```
pillywiggins/
├── README.md
├── docker-compose.yaml
├── Dockerfile
├── .env.example
├── .gitignore                          # includes .env
├── pyproject.toml
│
├── personalities/                      # mounted into containers
│   ├── discord.yaml
│   ├── slack.yaml
│   ├── telegram.yaml
│   ├── matrix.yaml
│   └── email.yaml
│
├── skills/                             # shared Docker volume
│   └── registry.json                   # starts as { "skills": [] }
│
├── src/
│   └── pillywiggins/
│       ├── __init__.py
│       ├── __main__.py                 # entry point: --channel arg → start agent
│       ├── config.py                   # Pydantic Settings for env vars
│       │
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py                 # PillywigginAgent class
│       │   ├── brain.py                # PydanticAI agent + built-in tools
│       │   ├── deps.py                 # AgentDeps dataclass
│       │   └── personality.py          # YAML loader
│       │
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base.py                 # BaseAdapter ABC
│       │   ├── discord_adapter.py
│       │   ├── slack_adapter.py
│       │   ├── telegram_adapter.py
│       │   ├── matrix_adapter.py
│       │   └── email_adapter.py
│       │
│       ├── memory/
│       │   ├── __init__.py
│       │   ├── private.py              # pgvector + RLS
│       │   ├── council.py              # shared pgvector
│       │   ├── cache.py                # Redis conversation cache
│       │   └── embeddings.py           # Ollama embedding helper
│       │
│       ├── messaging/
│       │   ├── __init__.py
│       │   ├── unified.py              # UnifiedMessage model
│       │   └── nats_bus.py             # NATS pub/sub wrapper
│       │
│       ├── skills/
│       │   ├── __init__.py
│       │   ├── registry.py             # SkillRegistry class
│       │   ├── builder.py              # Skill building/testing flow
│       │   ├── sandbox.py              # Sandboxed execution
│       │   └── templates.py            # Skill file template for LLM
│       │
│       ├── scheduling/
│       │   ├── __init__.py
│       │   └── scheduler.py            # APScheduler setup
│       │
│       └── health.py                   # /healthz endpoint
│
├── scripts/
│   ├── setup-db.sh                     # schemas, RLS, indexes
│   ├── pull-models.sh                  # ollama pull commands
│   └── backup-db.sh                    # pg_dump wrapper
│
├── tests/
│   ├── conftest.py
│   ├── test_brain.py
│   ├── test_memory_isolation.py
│   ├── test_skill_sandbox.py
│   ├── test_skill_registry.py
│   ├── test_adapters.py
│   └── test_council.py
│
└── docs/
    ├── OVERVIEW.md
    ├── DESIGN.md                       # this document
    ├── PERSONALITIES.md                # how to write personality files
    ├── SKILLS.md                       # how the skill system works
    └── ADDING-CHANNELS.md              # how to add a new adapter
```

---

## 12. Implementation Roadmap

### Phase 1: One Agent Talks (Week 1–2)

**Goal**: Discord agent running, talking to Ollama, persisting conversations.

- Set up project structure, Dockerfile, docker-compose.yaml
- Deploy PostgreSQL, Redis, NATS, Ollama via Compose
- Run setup-db.sh for schemas and RLS
- Pull Qwen 3.5 8B and nomic-embed-text
- Write PillywigginAgent base class with asyncio.Lock
- Write PydanticAI brain with basic system prompt
- Write Discord adapter
- Wire together in `__main__.py`
- Test: send a message on Discord, get a response

**Done when**: You can DM the bot and have a multi-turn conversation. History persists across restarts.

### Phase 2: Memory Works (Week 3–4)

**Goal**: Private memory with RLS, personality from YAML, council memory schema ready.

- Implement Ollama embedding generation
- Implement private memory save and semantic search
- Write and verify RLS isolation tests (cross-agent reads must fail)
- Implement personality loading from YAML
- Build council memory table and search/write functions
- Add council write validation
- Add `recall_private_memory`, `query_council_memory`, `share_to_council` as PydanticAI tools

**Done when**: The agent remembers previous conversations. Personality changes take effect on restart. Council memory is searchable.

### Phase 3: Skills System (Week 5–7)

**Goal**: Agents can build, test, and deploy skills collaboratively with the user.

- Design the skill file template (SKILL_META + run function)
- Write the SkillRegistry class (load, register, watch for changes)
- Write the sandbox executor (subprocess with timeouts)
- Write the skill builder flow (draft → test → review → deploy)
- Add `build_skill`, `test_skill`, `deploy_skill`, `list_skills` as tools
- Wire council announcements for new skills
- Test: ask an agent to build a simple tool, approve it, verify all agents can use it
- Write 2-3 example skills manually to seed the system

**Done when**: You can ask an agent to build a tool, iterate on it, approve deployment, and then use it from any channel.

### Phase 4: Second Agent + Communication (Week 8–9)

**Goal**: Two agents running with isolated state, sharing skills and council memory.

- Write second adapter (Slack or Telegram)
- Set up NATS pub/sub wiring
- Test council broadcasts and skill discovery across agents
- Verify private memory isolation between agents
- Implement per-agent cron with APScheduler + Redis
- Add personality-driven scheduled tasks

**Done when**: Two agents running, separate personalities, shared skills, isolated memories. Cron jobs fire on time and survive restarts.

### Phase 5: Full Fleet (Week 10–13)

**Goal**: All five channels live with the complete feature set.

- Write remaining adapters: Telegram, Matrix, Email
- Write all five personality files
- Configure per-agent cron schedules
- End-to-end: message on each channel, skill available everywhere, council sharing works
- Stress test: simultaneous messages across channels
- Add dynamic cron creation from conversation

**Done when**: `docker compose up` starts everything. All five agents respond on their platforms. Skills, memory, cron, and council all work across the fleet.

### Phase 6: Hardening (Week 14–16)

**Goal**: Reliable enough to leave running 24/7.

- Rate limiting per agent
- Structured JSON logging
- Docker healthchecks with restart policies
- Conversation summarisation (compress old history to save context window)
- Memory consolidation (periodic summarisation of old private memories)
- Basic prompt injection detection
- Automated PostgreSQL backups
- Write a runbook: restart procedures, log checking, backup restoration

**Done when**: Runs unattended for a week. Auto-restarts on failure. Logs are useful. Database backed up daily.

### Phase 7: Polish (ongoing)

- Agent self-reflection during scheduled quiet time
- Rich responses (Discord embeds, Slack blocks)
- Skill versioning and rollback
- Admin web UI for monitoring
- Optional MCP support for external tool servers (n8n, third-party)
- Multi-model routing (small model for simple queries)
- Prometheus + Grafana dashboards

---

## 13. Open Questions

**Model quality at 8B**: Will Qwen 3.5 8B generate good skill code? Test in Phase 1. Fallback: try Gemma 4, Llama 3.3, or budget for a GPU upgrade.

**Skill complexity ceiling**: Some skills need dependencies (aiohttp, beautifulsoup, etc.). How are these installed? Options: pre-install common packages in the Docker image, or have the build process flag required packages for manual installation.

**Sandbox escape risk**: Subprocess isolation is okay for user-approved code but not bulletproof. Upgrade path: run skills in a dedicated sandbox container with Docker-in-Docker.

**Ollama concurrency**: Five agents sharing one Ollama instance with `NUM_PARALLEL=2` means three could be waiting. Monitor and tune.

**Email threading**: How much thread context for multi-day email conversations? Start with last 3 messages + summary.

**Council memory conflicts**: Two agents contribute contradictory info. For now, newer wins. Add conflict resolution later if needed.

---

## 14. Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|------------|
| GPU OOM under load | High | Medium | OLLAMA_NUM_PARALLEL=2, request queuing, VRAM monitoring |
| 8B model can't write good skills | High | Medium | Test early, have fallback models, allow manual skill writing |
| RLS misconfiguration | High | Low | Explicit isolation tests, separate DB roles per agent |
| Runaway skill execution | Medium | Medium | 30s timeout, user approval required, rate limiting |
| Skill dependency not installed | Low | Medium | Pre-install common packages, flag missing deps at test time |
| Single machine failure | High | Low | Daily PG backups, documented recovery |
| Agent infinite tool loop | Medium | Medium | PydanticAI retries=2, 120s overall timeout |

---

## Summary

Pillywiggins is a council of AI agents — one per channel — that:

- Run as **Docker containers** orchestrated by Docker Compose
- Think using **PydanticAI + Ollama** with open-weight models
- Keep **isolated private memories** enforced by PostgreSQL RLS
- Share knowledge through **council memory** (attributed, tagged, searchable)
- **Build their own tools** collaboratively with the user (draft → test → approve → deploy)
- Share deployed skills across all agents via a **shared volume + NATS notifications**
- Run **per-agent cron jobs** backed by Redis (survive restarts, don't interfere with each other)
- Communicate through **NATS JetStream** for council broadcasts and direct messages
- Start with **one command**: `docker compose up`
