# Pillywiggins: The Big Picture

**A council of AI agents, not a chatbot with multiple faces.**

---

## What Is This Thing?

Pillywiggins is a system that runs multiple AI agents — one per communication channel — that work together as a team while keeping their own identities. Think of it like a group of helpful assistants who share a common noticeboard but have their own desks, their own notebooks, and their own personalities.

```
  Discord ──► Puck (playful trickster)      ─┐
     Slack ──► Ariel (efficient professional) ─┤
 Telegram ──► Robin (warm companion)         ─┼── Shared Noticeboard + Shared Toolbox
   Matrix ──► Cobweb (quiet thinker)         ─┤
    Email ──► Moth (formal correspondent)    ─┘
```

Each agent:

- Has its **own personality** (Puck is playful on Discord; Moth is formal over email)
- Keeps its **own private memory** (what you said on Slack stays on Slack)
- Runs as its **own process** (if Telegram crashes, Discord keeps working)
- Has its **own cron schedule** (Puck greets you at 9am, Moth checks email every 2 minutes)
- Can **share insights** with the team through a shared "council memory"
- Can **build new skills** collaboratively with you, then share them with all agents
- Can **use any skill** that any agent has built

This is different from most AI frameworks where one brain wears different masks. In those systems, your private Slack DM context might leak into a Discord server reply. Here, each agent genuinely has its own head.

---

## The Three Memory Spaces

```
┌──────────────────────────────────────────────────────┐
│                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │   Puck's    │  │   Ariel's   │  │   Robin's   │  │
│  │   Private   │  │   Private   │  │   Private   │  │
│  │   Memory    │  │   Memory    │  │   Memory    │  │
│  │  (LOCKED)   │  │  (LOCKED)   │  │  (LOCKED)   │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │           Council Memory (Shared)              │  │
│  │                                                │  │
│  │  "User prefers dark mode" — from Puck          │  │
│  │  "Meeting moved to Friday" — from Ariel        │  │
│  │  "New skill deployed: weather_check" — from    │  │
│  │    Robin, tagged: [skills, announcement]       │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │           Conversation Cache (Fast)            │  │
│  │  Recent messages per agent — kept in Redis     │  │
│  │  for quick access, auto-expires after 30 min   │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
└──────────────────────────────────────────────────────┘
```

**Private memory** is stored in PostgreSQL with enforced isolation. Even if there's a bug in the code, Puck literally cannot read Ariel's memories — the database itself blocks it.

**Council memory** is a shared noticeboard. Any agent can pin something there, tagged with who said it and what it's about. Other agents can search it. This is how agents share knowledge without sharing everything. When a new skill is deployed, it gets announced here so all agents know about it.

**Conversation cache** is fast, short-term memory in Redis. It keeps the last few minutes of conversation so the agent doesn't have to hit the database for every message.

---

## The Skills System

This is the part that makes Pillywiggins genuinely useful. Agents can **build new skills** — and they do it collaboratively with you.

### How building a skill works

```
You:    "Hey Puck, can you build me a tool that checks if a website is up?"

Puck:   "Sure! Here's what I'm thinking:"

        ┌─────────────────────────────────────────────┐
        │  Skill: check_website                       │
        │  Description: Check if a URL is reachable   │
        │  Input: url (string)                        │
        │  Output: { status, response_time_ms }       │
        │                                             │
        │  [Python code shown to you]                 │
        │                                             │
        │  Test cases:                                │
        │  ✅ check_website("https://google.com")     │
        │     → { status: 200, response_time: 142 }   │
        │  ✅ check_website("https://fakexyz.invalid") │
        │     → { status: "unreachable", error: ... } │
        │                                             │
        │  All tests passed! Deploy this skill?       │
        └─────────────────────────────────────────────┘

You:    "Looks good, but can you add a timeout parameter?"

Puck:   [revises the skill, re-runs tests]
        "Updated! Tests still pass. Deploy?"

You:    "Yes, deploy it."

Puck:   ✅ Skill "check_website" deployed!
        📢 Announced to council: all agents now have access.
```

### What happens behind the scenes

1. The agent writes a Python function following a standard template
2. It writes test cases for the function
3. It runs the tests in a **sandboxed subprocess** (restricted, no access to your filesystem or network unless explicitly allowed)
4. You review the code and tests, give feedback, iterate
5. When you approve, the skill file is saved to a shared `skills/` directory
6. The skill registry is updated
7. A council announcement is published so all agents discover the new skill
8. From now on, any agent can use `check_website` as a tool

### Skills are permanent and shared

Once deployed, a skill persists across restarts. It's just a Python file on disk. All five agents can use it. The skills directory grows over time into your personal toolbox — built exactly for your needs, by your agents, with your approval.

```
skills/
├── registry.json              # what's available
├── check_website.py           # built by Puck
├── summarise_article.py       # built by Ariel
├── dice_roller.py             # built by Robin
├── convert_timezone.py        # built by Moth
└── count_words.py             # built by Cobweb
```

### Why not just MCP?

MCP (Model Context Protocol) is a standard for connecting AI agents to external tools. Pillywiggins can optionally connect to MCP servers (like n8n) for external integrations. But the primary skill system is simpler — it's just Python files in a folder. No HTTP servers to run, no protocol to implement, no spec to comply with. When an agent builds a skill, it writes a .py file, not a microservice.

MCP is available as an optional add-on for connecting to external tool ecosystems if you want it later.

---

## Per-Agent Cron Jobs

Every agent has its own scheduler. This is a first-class feature, not an afterthought.

```yaml
# personalities/discord.yaml
scheduling:
  morning_greeting:
    cron: "0 9 * * *"              # Every day at 9am
    action: "Send a cheerful morning greeting to the general channel"
  
  fun_fact_friday:
    cron: "0 15 * * 5"             # Every Friday at 3pm
    action: "Share a random fun fact"
  
  memory_cleanup:
    cron: "0 3 * * 0"             # Every Sunday at 3am
    action: "Review and consolidate old memories"


# personalities/email.yaml
scheduling:
  check_inbox:
    cron: "*/2 * * * *"            # Every 2 minutes
    action: "Check for new emails and process them"
  
  daily_digest:
    cron: "0 8 * * 1-5"           # Weekdays at 8am
    action: "Summarise unread emails from overnight"
```

Each agent's cron runs **inside its own process**. If Discord's cron fires while Telegram's is sleeping, they don't interfere. Jobs survive container restarts because they're backed by Redis — if the container crashes at 8:59am, it picks up the 9:00am job when it comes back.

This is different from most frameworks where cron is either global (one scheduler for everything) or bolted on as an afterthought. Here, each agent's personality file defines its own schedule, and that schedule is as much a part of the agent's identity as its tone of voice.

---

## How a Message Gets Processed

Here's what happens when someone sends "Hey Puck, what's the weather?" on Discord:

```
1. Discord sends the message to the Discord adapter
2. The adapter normalises it into a standard format
3. The adapter hands this to Puck's agent process
4. Puck's agent:
   a. Grabs recent conversation from Redis cache
   b. Searches private memory for relevant context
   c. Searches council memory for anything useful
   d. Checks the skill registry for available tools
   e. Assembles a prompt with personality + context + tools + message
   f. Sends it to Ollama (the local LLM)
   g. The LLM might call a skill (e.g., check_weather)
   h. Gets a response back
   i. Saves the exchange to conversation cache + private memory
5. The adapter translates the response back to Discord format
6. Discord shows the reply
```

The same flow works for every channel — only step 1 (receive) and step 6 (send) are platform-specific. Cron-triggered actions follow the same path, just with a synthetic "scheduled task" message instead of a user message.

---

## What Runs Where

Everything runs as Docker containers, orchestrated by Docker Compose. One command starts the whole system:

```
docker compose up
```

Here's what's inside:

```
┌─────────────────────────────────────────────────┐
│  Docker Compose                                 │
│                                                 │
│  Infrastructure:                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ Postgres │ │  Redis   │ │   NATS   │        │
│  │ +pgvector│ │          │ │ JetStream│        │
│  └──────────┘ └──────────┘ └──────────┘        │
│                                                 │
│  Inference:                                     │
│  ┌─────────────────────────┐                    │
│  │  Ollama (GPU-attached)  │                    │
│  └─────────────────────────┘                    │
│                                                 │
│  Agents (one container each):                   │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐          │
│  │ Discord │ │  Slack  │ │Telegram │          │
│  │  Agent  │ │  Agent  │ │  Agent  │          │
│  └─────────┘ └─────────┘ └─────────┘          │
│  ┌─────────┐ ┌─────────┐                       │
│  │ Matrix  │ │  Email  │                       │
│  │  Agent  │ │  Agent  │                       │
│  └─────────┘ └─────────┘                       │
│                                                 │
│  Shared:                                        │
│  ┌────────────────────┐                         │
│  │ skills/ volume     │ ← mounted into all      │
│  │ (persistent tools) │   agent containers       │
│  └────────────────────┘                         │
│                                                 │
└─────────────────────────────────────────────────┘
```

Each agent is a Python process in its own container. They talk to each other through NATS (a lightweight message bus). They store memories in PostgreSQL. They cache conversations in Redis. They think using Ollama. They share skills through a mounted Docker volume.

No Kubernetes. No sidecars. No control planes. Just containers talking to each other over a Docker network.

---

## The Technology Stack (and Why Each Piece)

| What | Technology | Why This One |
|------|-----------|-------------|
| Language | Python | Best AI library ecosystem, period |
| Agent brain | PydanticAI | Type-safe, works with Ollama natively, clean tool support |
| LLM inference | Ollama | One command to run local models, GPU support |
| Models | Qwen 3.5 8B | Best tool-calling in its size class, fits a 16GB GPU |
| Database | PostgreSQL + pgvector | Rock solid, row-level security, vector search built in |
| Cache | Redis | Fast, simple, also backs the cron job store |
| Message bus | NATS JetStream | Tiny footprint, agents talk to each other through it |
| Skills | Python files + sandbox | Simple, no protocol overhead, agents can write them |
| Channel libs | discord.py, slack_bolt, etc. | Official or best-in-class per platform |
| Scheduling | APScheduler + Redis | Per-agent cron, persistent across restarts |
| External tools | MCP (optional) | For connecting to n8n or third-party tool servers |

---

## What You Need to Run It

**Hardware:**

- A machine with an NVIDIA GPU (16GB+ VRAM for the 8B model)
- 16GB+ system RAM
- Docker and Docker Compose installed
- NVIDIA Container Toolkit (for GPU passthrough to Ollama)

**Accounts/Tokens:**

- Discord bot token
- Slack bot token (Socket Mode — no public URL needed)
- Telegram bot token
- Matrix homeserver account
- Email account with IMAP/SMTP access

**That's it.** No cloud services, no API keys for LLM providers, no Kubernetes cluster. Everything runs on your machine.

---

## How It's Different

| Feature | OpenClaw | LangGraph | Pillywiggins |
|---------|----------|-----------|-------------|
| Agent-per-channel | No (one brain, many mouths) | No (single agent) | Yes (council model) |
| Memory isolation | No (shared flat files) | Partial (thread-based) | Yes (database-enforced) |
| Open models only | No (Claude-first) | No (model-agnostic but cloud-biased) | Yes (Ollama-first) |
| Agent-built skills | No | No | Yes (collaborative with user) |
| Per-agent cron | Partial (heartbeats only) | No | Yes (first-class feature) |
| Setup complexity | Medium | High | Low (docker compose up) |
| Personality per channel | No | Manual | First-class feature |
