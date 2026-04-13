# Pillywiggins: Software Design Document & Implementation Roadmap

**Version 1.0 — April 12, 2026**
**Author: Jason (with AI-assisted research)**

---

Pillywiggins is a 24/7 autonomous council of AI agents — one per communication channel — sharing knowledge while maintaining distinct identities, memories, and personalities. This document serves as both a technical specification and implementation guide. **The recommended architecture pairs PydanticAI v1 as the agent brain inside custom Dapr virtual actors**, giving type-safe dependency injection, native Ollama and MCP support, and full control over per-agent state isolation via PostgreSQL Row-Level Security. Every architectural decision below has been validated against the current state of each technology as of April 2026.

---

## 1. The council of agents, not a chatbot with multiple faces

Pillywiggins rejects the common pattern of a single AI agent multiplexed across channels. Instead, each communication channel — Discord, Slack, Telegram, Matrix, Email — gets its own **autonomous agent** with a private personality, private memory, and scoped session context. These agents form a *council*: they share knowledge through a tagged, attributed council memory and access shared tools through an MCP registry, but they cannot read each other's private thoughts or conversation histories.

This matters for three reasons. First, personality authenticity: a Discord agent can be casual and emoji-heavy while the Email agent maintains professional formality, without schizophrenic context-switching. Second, memory isolation prevents information leakage — a private Slack DM's content never surfaces in a Discord server response. Third, the council pattern enables emergent collaboration: agents can share insights (attributed and validated) without centralizing all knowledge in one monolithic context window.

The metaphor is deliberate. Each agent is a distinct member of a council who convenes with peers to share findings, but maintains their own notes, their own style, and their own relationships with the people they serve.

---

## 2. System architecture at a glance

### High-level data flow

Every inbound message follows the same path regardless of channel:

1. **Channel Adapter** receives a platform-native event (Discord message, Slack event, Telegram update, etc.)
2. Adapter normalizes the event into a **UnifiedMessage** and routes it to the appropriate Dapr virtual actor
3. The **PillywigginActor** activates (if idle), loads its private state, constructs PydanticAI dependencies, and invokes the PydanticAI agent brain
4. The agent brain processes the message — consulting private memory, council memory, and MCP tools as needed
5. The response flows back through the channel adapter to the originating platform
6. State changes (conversation history, memory updates) are persisted via Dapr state stores and direct PostgreSQL writes

### Inter-agent communication

Agents communicate through **NATS JetStream** (via Dapr pub/sub). Three topic patterns:

- **`council.broadcast`** — Any agent can publish insights for all agents to consume
- **`council.direct.{agent_id}`** — Point-to-point messages between specific agents
- **`council.memory.updates`** — Notifications when council memory is modified, triggering cache invalidation

### Namespace layout

```
pillywiggins-system/     # Dapr control plane, NATS, Redis
pillywiggins-agents/     # All agent pods (one Deployment per channel agent)
pillywiggins-data/       # PostgreSQL (private + council memory)
pillywiggins-inference/  # Ollama inference server with GPU access
pillywiggins-tools/      # MCP server pods, gVisor-sandboxed tool execution
pillywiggins-obs/        # Prometheus, Grafana, OpenTelemetry collector
```

### Pod structure per agent

Each channel agent runs as a Kubernetes Deployment with:

```
┌─────────────────────────────────────┐
│  Pod: discord-agent                 │
│  ┌──────────────┐ ┌──────────────┐  │
│  │ agent        │ │ daprd        │  │
│  │ container    │ │ sidecar      │  │
│  │ (Python)     │ │ (injected)   │  │
│  │              │◄─►             │  │
│  │ - PydanticAI │ │ - State API  │  │
│  │ - Actor Host │ │ - PubSub API │  │
│  │ - Channel    │ │ - Secrets    │  │
│  │   Adapter    │ │ - mTLS       │  │
│  └──────────────┘ └──────────────┘  │
│  ConfigMap: discord-personality     │
│  Secret: discord-bot-token          │
└─────────────────────────────────────┘
```

---

## 3. Core components specification

### 3.1 Agent runtime: PydanticAI inside Dapr actors

**Architectural decision**: Use PydanticAI v1 as the agent brain inside custom Dapr virtual actors, rather than Dapr Agents' built-in DurableAgent.

**Rationale**: DurableAgent abstracts away actor-level control, making it difficult to implement PostgreSQL RLS-scoped memory isolation. PydanticAI's dependency injection (`RunContext[AgentDeps]`) maps perfectly to the actor activation pattern — the actor constructs deps with its scoped database connection, private state, and personality config, then passes them to the stateless PydanticAI agent. DurableAgent's built-in tool system also conflicts with PydanticAI's more mature tool/MCP integration.

**Base class: `PillywigginActor`**

```python
# src/pillywiggins/agents/base.py
from dataclasses import dataclass
from dapr.actor import Actor, ActorId
from dapr.actor.runtime.context import ActorRuntimeContext
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPServerStreamableHTTP
import asyncpg

@dataclass
class AgentDeps:
    """Injected into every PydanticAI tool and instruction call."""
    agent_id: str
    channel: str
    personality: dict
    db_pool: asyncpg.Pool          # RLS-scoped connection pool
    council_db: asyncpg.Pool       # Council memory (shared read)
    state_manager: "DaprStateManager"
    conversation_history: list
    user_context: dict

class PillywigginActor(Actor):
    """Base Dapr virtual actor for all channel agents."""

    def __init__(self, ctx: ActorRuntimeContext, actor_id: ActorId):
        super().__init__(ctx, actor_id)
        self._agent_id = actor_id.id
        self._message_history = []
        self._personality = {}

    async def _on_activate(self) -> None:
        """Load state on actor activation."""
        stored_history = await self._state_manager.try_get_state("history")
        self._message_history = stored_history or []
        self._personality = await self._load_personality()

    async def handle_message(self, unified_msg: dict) -> dict:
        """Process an incoming message through the PydanticAI brain."""
        deps = AgentDeps(
            agent_id=self._agent_id,
            channel=self._channel_type,
            personality=self._personality,
            db_pool=await self._get_scoped_pool(),
            council_db=await self._get_council_pool(),
            state_manager=self._state_manager,
            conversation_history=self._message_history,
            user_context=unified_msg.get("user_context", {}),
        )
        result = await self._brain.run(
            unified_msg["content"],
            deps=deps,
            message_history=self._message_history,
        )
        self._message_history = result.all_messages()
        # Persist to Redis cache (fast) and PostgreSQL (durable)
        await self._persist_state()
        return {"content": result.output, "channel": self._channel_type}

    async def _on_deactivate(self) -> None:
        """Save state when actor is garbage-collected."""
        await self._persist_state()
```

**PydanticAI agent definition (stateless, global singleton)**:

```python
# src/pillywiggins/agents/brain.py
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPServerStreamableHTTP

# MCP tool servers — shared across all agents
skill_registry = MCPServerStreamableHTTP("http://mcp-registry.pillywiggins-tools:8000/mcp")
n8n_tools = MCPServerStreamableHTTP("http://n8n.pillywiggins-system:5678/mcp")

pillywiggin_brain = Agent(
    "ollama:qwen3.5-32b",
    deps_type=AgentDeps,
    toolsets=[skill_registry, n8n_tools],
    output_type=str,
    retries=2,
)

@pillywiggin_brain.instructions
async def dynamic_personality(ctx: RunContext[AgentDeps]) -> str:
    p = ctx.deps.personality
    return (
        f"You are {p['name']}, a {p['archetype']}. "
        f"Tone: {p['tone']}. Style: {p['style']}. "
        f"Channel: {ctx.deps.channel}. "
        f"{p.get('additional_instructions', '')}"
    )

@pillywiggin_brain.tool
async def recall_private_memory(
    ctx: RunContext[AgentDeps], query: str, limit: int = 5
) -> list[dict]:
    """Search your private memory for relevant past context."""
    rows = await ctx.deps.db_pool.fetch(
        """
        SELECT content, metadata, created_at,
               1 - (embedding <=> $1::vector) as similarity
        FROM private_memory
        WHERE agent_id = current_setting('app.agent_id')
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """,
        await _embed(query), limit,
    )
    return [dict(r) for r in rows]

@pillywiggin_brain.tool
async def query_council_memory(
    ctx: RunContext[AgentDeps], query: str, tags: list[str] | None = None
) -> list[dict]:
    """Search the shared council memory for knowledge from all agents."""
    tag_filter = "AND tags && $3::text[]" if tags else ""
    params = [await _embed(query), 10]
    if tags:
        params.append(tags)
    rows = await ctx.deps.council_db.fetch(
        f"""
        SELECT content, contributing_agent, tags, created_at,
               1 - (embedding <=> $1::vector) as similarity
        FROM council_memory
        {tag_filter}
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """,
        *params,
    )
    return [dict(r) for r in rows]

@pillywiggin_brain.tool
async def share_to_council(
    ctx: RunContext[AgentDeps], content: str, tags: list[str]
) -> str:
    """Share an insight or piece of knowledge with all council members."""
    embedding = await _embed(content)
    await ctx.deps.council_db.execute(
        """
        INSERT INTO council_memory (contributing_agent, content, tags, embedding)
        VALUES ($1, $2, $3, $4)
        """,
        ctx.deps.agent_id, content, tags, embedding,
    )
    # Notify other agents via pub/sub
    await _publish_council_update(ctx.deps.agent_id, tags)
    return f"Shared to council with tags: {tags}"
```

### 3.2 Channel adapter layer

Each adapter translates platform-specific events into a `UnifiedMessage` and dispatches them to the corresponding Dapr actor. Adapters run inside the same pod as their agent.

**Unified message format:**

```python
# src/pillywiggins/messages/unified.py
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class ChannelType(str, Enum):
    DISCORD = "discord"
    SLACK = "slack"
    TELEGRAM = "telegram"
    MATRIX = "matrix"
    EMAIL = "email"

class UnifiedMessage(BaseModel):
    message_id: str = Field(description="Platform-native message ID")
    channel_type: ChannelType
    channel_id: str = Field(description="Channel/room/thread ID")
    sender_id: str
    sender_display_name: str
    content: str
    attachments: list[dict] = Field(default_factory=list)
    reply_to: str | None = None
    thread_id: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)
    is_direct_message: bool = False
```

**Discord adapter example:**

```python
# src/pillywiggins/adapters/discord_adapter.py
import discord
from discord.ext import commands
from pillywiggins.messages.unified import UnifiedMessage, ChannelType
from dapr.clients import DaprClient

class DiscordAdapter(commands.Bot):
    def __init__(self, actor_id: str):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self._actor_id = actor_id
        self._dapr = DaprClient()

    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return
        unified = UnifiedMessage(
            message_id=str(message.id),
            channel_type=ChannelType.DISCORD,
            channel_id=str(message.channel.id),
            sender_id=str(message.author.id),
            sender_display_name=message.author.display_name,
            content=message.content,
            is_direct_message=isinstance(message.channel, discord.DMChannel),
            thread_id=str(message.thread.id) if message.thread else None,
            metadata={"guild_id": str(message.guild.id) if message.guild else None},
        )
        # Invoke the Dapr actor
        response = await self._dapr.invoke_actor(
            actor_type="PillywigginActor",
            actor_id=self._actor_id,
            method="handle_message",
            data=unified.model_dump_json(),
        )
        await message.reply(response["content"])
```

Each adapter follows the same pattern: receive platform event → normalize to `UnifiedMessage` → invoke actor → translate response back to platform format.

| Adapter | Library | Key Integration Notes |
|---------|---------|----------------------|
| Discord | `discord.py` v2 | Gateway websocket, slash commands, thread support |
| Slack | `slack_bolt` | Socket Mode (no public URL needed), blocks/rich formatting |
| Telegram | `python-telegram-bot` v21 | Webhook mode in k8s, inline keyboards, markdown |
| Matrix | `matrix-nio` + `NioBot` | E2EE support, room state tracking, federation |
| Email | `aiosmtplib` + `imap-tools` | IMAP IDLE for real-time, SMTP for sending, MIME parsing |

### 3.3 Memory architecture

**Three-tier memory system:**

**Tier 1 — Conversation cache (Redis via Dapr state store)**:
Hot conversation context for the current session. TTL of **30 minutes** of inactivity. Sub-millisecond reads. Used to maintain conversational flow without hitting PostgreSQL on every turn.

**Tier 2 — Private memory (PostgreSQL + pgvector with RLS)**:
Long-term episodic memory per agent. Each agent's queries are automatically scoped by PostgreSQL RLS policies — even a SQL injection in a tool cannot access another agent's memories. Supports semantic search via pgvector embeddings.

**Tier 3 — Council memory (PostgreSQL + pgvector, shared read)**:
Attributed, tagged knowledge base readable by all agents. Writes require the `contributing_agent` field and go through content validation. Agents are notified of new entries via NATS pub/sub.

### 3.4 Skill and tool registry via MCP

Tools are exposed through **MCP servers** using the Streamable HTTP transport. PydanticAI's built-in `MCPServerStreamableHTTP` client discovers and invokes tools dynamically.

**MCP server catalogue:**

| Server | Purpose | Transport |
|--------|---------|-----------|
| `mcp-core-tools` | File ops, web search, calculations | Streamable HTTP |
| `mcp-n8n-bridge` | n8n workflows as tools (via MCP Server Trigger) | Streamable HTTP |
| `mcp-memory-tools` | Advanced memory operations (summarize, forget) | Streamable HTTP |
| `mcp-admin-tools` | System health, agent management | Streamable HTTP |

**n8n integration**: n8n's native MCP Server Trigger node (available since n8n v2.13+) exposes any workflow as an MCP tool. Each workflow gets a tool name, description, and input schema derived from the workflow's trigger parameters. The `mcp-n8n-bridge` service is simply the n8n instance configured with MCP Server Trigger nodes.

**Custom MCP server template:**

```python
# src/pillywiggins/tools/servers/core_tools.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Pillywiggins Core Tools", json_response=True)

@mcp.tool()
async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web for current information."""
    # Implementation using a search API
    ...

@mcp.tool()
async def summarize_text(text: str, max_length: int = 200) -> str:
    """Summarize a long piece of text."""
    ...

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

### 3.5 Scheduling system

**Dapr Reminders** for durable, crash-surviving schedules (stored in Dapr's Scheduler service backed by embedded etcd since v1.15):

```python
# Register a daily check-in reminder
await actor_client.register_reminder(
    actor_type="PillywigginActor",
    actor_id="discord-agent",
    reminder_name="daily-checkin",
    due_time="0h0m0s",
    period="PT24H",
    data={"task": "morning_greeting"},
)
```

**APScheduler** for flexible in-process cron (personality-specific schedules like "post a fun fact every Friday at 3pm"):

```python
# Inside the agent container
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()
scheduler.add_job(
    post_fun_fact,
    CronTrigger(day_of_week="fri", hour=15),
    id="friday-fun-fact",
    kwargs={"agent_id": "discord-agent"},
)
scheduler.start()
```

**Design guideline**: Use Dapr Reminders for anything that must survive crashes (health checks, daily summaries, periodic memory consolidation). Use APScheduler for personality-driven schedules that can be rebuilt from config on restart.

### 3.6 LLM integration

**Primary**: Ollama on k3s with NVIDIA GPU, accessed through PydanticAI's native `OllamaProvider`.

```python
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider

# Simple shorthand
agent = Agent("ollama:qwen3.5-32b")

# Explicit configuration for production
model = OpenAIChatModel(
    model_name="qwen3.5-32b",
    provider=OllamaProvider(
        base_url="http://ollama.pillywiggins-inference:11434/v1"
    ),
)
agent = Agent(model, deps_type=AgentDeps)
```

**Model selection strategy:**

| Use Case | Model | VRAM Estimate |
|----------|-------|---------------|
| Primary agent brain | Qwen 3.5 32B (Q4_K_M) | ~20 GB |
| Fast tool-calling | Qwen 3.5 8B (Q8) | ~9 GB |
| Embeddings | nomic-embed-text v1.5 | ~300 MB |

The RTX 5060 Ti (**16 GB VRAM**) constrains model choice. **Qwen 3.5 8B quantized is the practical ceiling** for single-GPU inference with headroom for KV cache. For the 32B model, consider aggressive quantization (Q3_K_M at ~15 GB) or plan the vLLM upgrade path with model sharding if a second GPU becomes available.

**Fallback strategy**: If Ollama is unavailable (GPU OOM, crash), fall back to a smaller model or queue messages with a "thinking..." status. Implement via PydanticAI's model override:

```python
from pydantic_ai import Agent

primary = Agent("ollama:qwen3.5-8b")
fallback = Agent("ollama:qwen3.5-1.5b")  # Runs on CPU if needed

async def run_with_fallback(prompt, deps):
    try:
        return await primary.run(prompt, deps=deps)
    except Exception:
        return await fallback.run(prompt, deps=deps)
```

---

## 4. Security architecture

### Per-agent memory isolation via PostgreSQL RLS

Every agent connects to PostgreSQL with a dedicated database role. RLS policies ensure that even if an agent's code is compromised or a tool generates malicious SQL, it can only access its own rows.

```sql
-- Setup
CREATE ROLE agent_discord LOGIN PASSWORD 'xxx';
CREATE ROLE agent_slack LOGIN PASSWORD 'xxx';
-- ...repeat for each agent

ALTER TABLE private_memory ENABLE ROW LEVEL SECURITY;

CREATE POLICY agent_isolation ON private_memory
    USING (agent_id = current_setting('app.agent_id'))
    WITH CHECK (agent_id = current_setting('app.agent_id'));

-- Connection initialization (in the connection pool setup)
-- SET app.agent_id = 'discord-agent';
```

Each agent's `asyncpg` pool is initialized with `SET app.agent_id` on every connection checkout, ensuring RLS scoping without per-query filtering.

### Prompt injection defense

Council memory writes are validated before insertion:

- **Content length limits**: Max **2,000 characters** per council memory entry
- **Tag whitelist**: Only predefined tags are accepted
- **Attribution enforcement**: `contributing_agent` must match the authenticated caller
- **Rate limiting**: Max **10 council writes per agent per hour**
- **Semantic deduplication**: Reject entries with cosine similarity > 0.95 to existing entries

Input sanitization strips known injection patterns from user messages before they reach the LLM. A lightweight classifier (or regex-based filter) flags suspicious inputs for review.

### Tool execution sandboxing

All MCP tool servers that execute user-influenced code run in **gVisor-sandboxed pods**:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-core-tools
  namespace: pillywiggins-tools
spec:
  template:
    spec:
      runtimeClassName: gvisor
      securityContext:
        runAsNonRoot: true
        fsGroup: 65534
      containers:
        - name: tools
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            readOnlyRootFilesystem: true
```

### Secrets management flow

```
Developer → SOPS + age encrypt → Git repo (encrypted secrets.yaml)
                                      ↓
CI/CD or Flux → sops --decrypt → kubectl apply → K8s Secrets
                                                      ↓
Dapr sidecar → K8s Secrets Store → secretKeyRef in component YAML
```

`.sops.yaml` configuration:

```yaml
creation_rules:
  - path_regex: .*secret.*\.yaml$
    encrypted_regex: ^(data|stringData)$
    age: age1your_public_key_here
```

### Inter-agent security

Dapr Sentry provides **automatic mTLS** for all sidecar-to-sidecar communication. This is enabled by default on Kubernetes and requires zero configuration. Every agent pod gets a **SPIFFE-based cryptographic identity**. Access control lists can restrict which agents can invoke which other agents' methods.

### Rate limiting and circuit breakers

Dapr's built-in resiliency policies handle transient failures:

```yaml
apiVersion: dapr.io/v1alpha1
kind: Resiliency
metadata:
  name: agent-resiliency
spec:
  policies:
    retries:
      llmRetry:
        policy: constant
        duration: 2s
        maxRetries: 3
    circuitBreakers:
      ollamaCB:
        maxRequests: 1
        interval: 30s
        timeout: 60s
        trip: consecutiveFailures > 3
    timeouts:
      llmTimeout: 120s
  targets:
    components:
      ollama:
        outbound:
          retry: llmRetry
          circuitBreaker: ollamaCB
          timeout: llmTimeout
```

---

## 5. Data models and schemas

### Council memory schema

```sql
CREATE TABLE council_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contributing_agent VARCHAR(64) NOT NULL,
    content TEXT NOT NULL CHECK (char_length(content) <= 2000),
    tags TEXT[] NOT NULL DEFAULT '{}',
    embedding vector(768) NOT NULL,
    confidence FLOAT DEFAULT 1.0,
    source_context JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    superseded_by UUID REFERENCES council_memory(id)
);

CREATE INDEX idx_council_embedding ON council_memory
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_council_tags ON council_memory USING gin (tags);
CREATE INDEX idx_council_agent ON council_memory (contributing_agent);
```

### Private memory schema

```sql
CREATE TABLE private_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(64) NOT NULL,
    content TEXT NOT NULL,
    memory_type VARCHAR(32) NOT NULL DEFAULT 'episodic',
    embedding vector(768) NOT NULL,
    metadata JSONB DEFAULT '{}',
    importance FLOAT DEFAULT 0.5,
    access_count INTEGER DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE private_memory ENABLE ROW LEVEL SECURITY;
CREATE POLICY agent_isolation ON private_memory
    USING (agent_id = current_setting('app.agent_id'))
    WITH CHECK (agent_id = current_setting('app.agent_id'));

CREATE INDEX idx_private_embedding ON private_memory
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
CREATE INDEX idx_private_agent ON private_memory (agent_id);
```

### Agent personality configuration schema

```yaml
# k8s/configmaps/discord-personality.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: discord-personality
  namespace: pillywiggins-agents
  labels:
    app.kubernetes.io/part-of: pillywiggins
    reloader.stakater.com/auto: "true"
data:
  personality.yaml: |
    name: "Puck"
    archetype: "Mischievous trickster fairy"
    channel: discord
    tone: "playful, witty, slightly chaotic"
    style: "uses emojis liberally, loves puns, references internet culture"
    response_length: "concise, 1-3 sentences unless asked for detail"
    additional_instructions: |
      You adore wordplay. You occasionally speak in rhyming couplets
      when excited. You call users 'mortal' affectionately.
    triggers:
      greeting_keywords: ["hello", "hey", "sup", "yo"]
      personality_keywords: ["who are you", "what are you"]
    scheduling:
      morning_greeting:
        cron: "0 9 * * *"
        timezone: "America/New_York"
      fun_fact_friday:
        cron: "0 15 * * 5"
```

### Skill/tool registration schema (MCP server catalogue)

```yaml
# k8s/configmaps/mcp-registry.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-registry
  namespace: pillywiggins-tools
data:
  servers.yaml: |
    servers:
      - name: core-tools
        url: "http://mcp-core-tools.pillywiggins-tools:8000/mcp"
        transport: streamable-http
        description: "Web search, calculations, text processing"
        sandbox: true
      - name: n8n-workflows
        url: "http://n8n.pillywiggins-system:5678/mcp"
        transport: streamable-http
        description: "Automation workflows exposed as tools"
        sandbox: false
      - name: memory-tools
        url: "http://mcp-memory-tools.pillywiggins-tools:8000/mcp"
        transport: streamable-http
        description: "Memory consolidation, summarization, forgetting"
        sandbox: false
```

---

## 6. Kubernetes deployment architecture

### Helm chart structure

```
helm/pillywiggins/
├── Chart.yaml
├── values.yaml
├── values-dev.yaml
├── values-prod.yaml
├── templates/
│   ├── _helpers.tpl
│   ├── namespaces.yaml
│   ├── dapr-components/
│   │   ├── pubsub-nats.yaml
│   │   ├── statestore-redis.yaml
│   │   ├── statestore-postgres.yaml
│   │   └── secretstore-k8s.yaml
│   ├── agents/
│   │   ├── discord-deployment.yaml
│   │   ├── slack-deployment.yaml
│   │   ├── telegram-deployment.yaml
│   │   ├── matrix-deployment.yaml
│   │   ├── email-deployment.yaml
│   │   └── agent-serviceaccount.yaml
│   ├── infrastructure/
│   │   ├── nats-helmrelease.yaml
│   │   ├── redis-helmrelease.yaml
│   │   ├── postgres-helmrelease.yaml
│   │   └── ollama-deployment.yaml
│   ├── tools/
│   │   ├── mcp-core-tools-deployment.yaml
│   │   └── mcp-memory-tools-deployment.yaml
│   ├── observability/
│   │   ├── prometheus-servicemonitor.yaml
│   │   └── grafana-dashboard-configmap.yaml
│   ├── security/
│   │   ├── gvisor-runtimeclass.yaml
│   │   ├── network-policies.yaml
│   │   └── resiliency.yaml
│   └── configmaps/
│       ├── discord-personality.yaml
│       ├── slack-personality.yaml
│       └── ...
```

### Agent deployment template

```yaml
# templates/agents/discord-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Values.agents.discord.name }}
  namespace: pillywiggins-agents
  labels:
    app.kubernetes.io/name: {{ .Values.agents.discord.name }}
    app.kubernetes.io/part-of: pillywiggins
    app.kubernetes.io/component: agent
spec:
  replicas: 1  # Single replica per agent (actor turn-based concurrency)
  selector:
    matchLabels:
      app: {{ .Values.agents.discord.name }}
  template:
    metadata:
      labels:
        app: {{ .Values.agents.discord.name }}
      annotations:
        dapr.io/enabled: "true"
        dapr.io/app-id: "{{ .Values.agents.discord.name }}"
        dapr.io/app-port: "8080"
        dapr.io/app-protocol: "grpc"
        dapr.io/log-level: "info"
        dapr.io/sidecar-cpu-request: "100m"
        dapr.io/sidecar-memory-request: "128Mi"
        reloader.stakater.com/auto: "true"
    spec:
      serviceAccountName: pillywiggins-agent
      containers:
        - name: agent
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          args: ["--channel", "discord", "--agent-id", "discord-agent"]
          ports:
            - containerPort: 8080
              name: grpc
          envFrom:
            - configMapRef:
                name: pillywiggins-common
          env:
            - name: AGENT_ID
              value: "discord-agent"
            - name: CHANNEL_TYPE
              value: "discord"
            - name: DISCORD_TOKEN
              valueFrom:
                secretKeyRef:
                  name: discord-secrets
                  key: bot-token
            - name: PG_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgres-secrets
                  key: agent-discord-password
          resources:
            requests:
              cpu: 200m
              memory: 512Mi
            limits:
              memory: 1Gi
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /readyz
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          volumeMounts:
            - name: personality
              mountPath: /etc/pillywiggins/personality
              readOnly: true
      volumes:
        - name: personality
          configMap:
            name: discord-personality
```

### Resource requirements

| Component | CPU Request | Memory Request | Memory Limit | GPU | Replicas |
|-----------|-------------|----------------|--------------|-----|----------|
| Agent pod (each) | 200m | 512Mi | 1Gi | None | 1 |
| Dapr sidecar (each) | 100m | 128Mi | 256Mi | None | — |
| Ollama | 1000m | 4Gi | 8Gi | 1x RTX 5060 Ti | 1 |
| PostgreSQL | 500m | 1Gi | 2Gi | None | 1 |
| Redis | 100m | 256Mi | 512Mi | None | 1 |
| NATS | 100m | 128Mi | 256Mi | None | 1 |
| MCP tool server (each) | 100m | 256Mi | 512Mi | None | 1 |
| Prometheus | 200m | 512Mi | 1Gi | None | 1 |
| Grafana | 100m | 256Mi | 512Mi | None | 1 |

**Total estimated baseline**: ~4 CPU cores, ~12 GB RAM, 1 GPU. Well within a single-node k3s server with reasonable specs.

### Dapr component configurations

**NATS JetStream pub/sub:**

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: council-pubsub
  namespace: pillywiggins-agents
spec:
  type: pubsub.jetstream
  version: v1
  metadata:
    - name: natsURL
      value: "nats://nats.pillywiggins-system:4222"
    - name: streamName
      value: "pillywiggins"
    - name: durableName
      value: "council-sub"
    - name: ackWait
      value: "30s"
    - name: maxDeliver
      value: "3"
    - name: deliverPolicy
      value: "new"
```

**Redis state store (conversation cache):**

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: conversation-cache
  namespace: pillywiggins-agents
spec:
  type: state.redis
  version: v1
  metadata:
    - name: redisHost
      value: "redis.pillywiggins-system:6379"
    - name: redisPassword
      secretKeyRef:
        name: redis-secrets
        key: password
    - name: actorStateStore
      value: "true"
    - name: ttlInSeconds
      value: "1800"
```

**PostgreSQL state store (workflow durability):**

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: agent-statestore
  namespace: pillywiggins-agents
spec:
  type: state.postgresql
  version: v2
  metadata:
    - name: connectionString
      value: "host=postgres.pillywiggins-data user=dapr password=${PG_DAPR_PASS} port=5432 database=pillywiggins_state"
    - name: actorStateStore
      value: "true"
```

### Ollama deployment with GPU

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
  namespace: pillywiggins-inference
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: ollama
          image: ollama/ollama:latest
          ports:
            - containerPort: 11434
          env:
            - name: OLLAMA_NUM_PARALLEL
              value: "2"
            - name: OLLAMA_MAX_LOADED_MODELS
              value: "2"
          resources:
            limits:
              nvidia.com/gpu: 1
          volumeMounts:
            - name: models
              mountPath: /root/.ollama
      volumes:
        - name: models
          persistentVolumeClaim:
            claimName: ollama-models
      tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
```

---

## 7. Implementation roadmap

### Phase 1: Foundation (Weeks 1–3)

**Goal**: Infrastructure running, first agent saying "hello."

**Deliverables**:

- k3s cluster configured with NVIDIA GPU Operator and gVisor RuntimeClass
- Dapr v1.17 installed via Helm with HA placement service
- PostgreSQL deployed with pgvector extension, RLS policies, and schemas created
- Redis deployed as Dapr state store
- NATS JetStream deployed as Dapr pub/sub
- Ollama deployed with GPU access, Qwen 3.5 8B model pulled
- Single "hello world" Discord agent: receives messages, sends to Ollama via PydanticAI, responds
- Basic project structure and CI (container builds)

**Acceptance criteria**: Send a Discord message, receive an LLM-generated response. `kubectl get pods -n dapr-system` shows healthy Dapr control plane. PydanticAI agent successfully calls Ollama.

**Estimated effort**: 40–50 hours

**Key commands:**

```bash
# Install Dapr
helm install dapr dapr/dapr --version=1.17 --namespace dapr-system --create-namespace -f helm/dapr-values.yaml --wait

# Deploy PostgreSQL with pgvector
helm install postgres bitnami/postgresql --namespace pillywiggins-data --create-namespace \
  --set image.tag=16-debian-12 \
  --set primary.extendedConfiguration="shared_preload_libraries='vector'"

# Pull the model
kubectl exec -n pillywiggins-inference deploy/ollama -- ollama pull qwen3.5:8b
```

### Phase 2: Framework (Weeks 4–7)

**Goal**: `PillywigginActor` base class working with private memory, personality system, and conversation persistence.

**Deliverables**:

- `PillywigginActor` base class with full lifecycle (activate, handle, deactivate)
- PydanticAI agent brain with dependency injection wired to actor state
- Private memory: write, semantic search, and RLS enforcement verified
- Conversation history persisted to Redis (cache) and PostgreSQL (durable)
- Personality loading from ConfigMaps with Stakater Reloader for hot-reload
- UnifiedMessage format and Discord adapter refactored to use it
- Second agent (Slack) running with distinct personality
- Basic health/readiness endpoints

**Acceptance criteria**: Two agents running simultaneously with provably isolated memories. Change a ConfigMap personality, observe behavior change without pod restart. Private memory semantic search returns relevant results.

**Estimated effort**: 60–80 hours

### Phase 3: Full fleet (Weeks 8–12)

**Goal**: All five channels live, council memory working, MCP tool registry operational.

**Deliverables**:

- Remaining channel adapters: Telegram, Matrix, Email
- Council memory: schema, write validation, semantic search, pub/sub notifications
- Council memory write validation pipeline (length, tag whitelist, dedup, rate limit)
- MCP core tools server deployed with 3–5 basic tools
- n8n MCP Server Trigger integration verified (at least 2 workflows as tools)
- Inter-agent pub/sub communication tested (broadcast + direct)
- Dapr Reminders configured for daily heartbeats per agent
- APScheduler integrated for personality-driven schedules
- All agents sharing tools via PydanticAI MCPToolset

**Acceptance criteria**: All five agents responding on their respective channels. Agent A shares knowledge to council, Agent B retrieves it in a subsequent query. MCP tools callable by any agent. n8n workflow triggerable as a tool.

**Estimated effort**: 80–100 hours

### Phase 4: Hardening (Weeks 13–16)

**Goal**: Production-grade security, observability, and reliability.

**Deliverables**:

- gVisor RuntimeClass enforced on all MCP tool pods
- SOPS + age encryption for all secrets in Git
- Dapr Resiliency policies: retries, circuit breakers, timeouts for Ollama and PostgreSQL
- Network policies restricting cross-namespace traffic
- Prometheus ServiceMonitors for all components
- Grafana dashboards: agent response times, LLM latency, memory usage, pub/sub throughput
- OpenTelemetry tracing end-to-end (message received → response sent)
- Automated backup for PostgreSQL (pg_dump cron)
- Load testing: simulate concurrent messages across all channels
- Rate limiting on channel adapters (prevent abuse)
- Prompt injection detection layer

**Acceptance criteria**: Kill an agent pod — it recovers and resumes with state intact. Grafana shows full request trace. Secrets in Git are encrypted. gVisor pods verified with `dmesg`. Circuit breaker trips and recovers under Ollama overload.

**Estimated effort**: 60–80 hours

### Phase 5: Enhancement (Weeks 17–20+)

**Goal**: Advanced features, personality depth, autonomous behaviors.

**Deliverables**:

- Memory consolidation: periodic summarization of old memories to reduce storage and improve retrieval
- Agent self-reflection: scheduled "thinking time" where agents review and organize memories
- Cross-agent council sessions: structured multi-agent deliberation on complex topics
- Personality evolution: agents can develop and refine their personality based on interactions
- Advanced tool creation: agents can define new MCP tools (with human approval)
- vLLM or SGLang evaluation for higher inference throughput
- Email agent: threaded conversation support, attachment handling
- Matrix agent: E2EE verification, federation testing
- Admin dashboard: web UI for monitoring agent states, memories, and council activity

**Acceptance criteria**: Agents demonstrate personality consistency over weeks of operation. Memory consolidation reduces storage without losing important context. Council sessions produce coherent multi-agent reasoning.

**Estimated effort**: 100+ hours (ongoing)

---

## 8. Open questions and decisions to resolve

**PydanticAI vs Dapr Agents DurableAgent durability**: The recommended architecture uses PydanticAI inside raw Dapr actors, bypassing DurableAgent's built-in crash recovery. This means implementing your own checkpointing for long-running tool chains. Evaluate whether to wrap the PydanticAI agent in `DaprWorkflowAgentRunner` from `diagrid.agent.pydantic_ai` for automatic durability, or whether the added complexity isn't worth it given that most agent interactions are short request-response cycles.

**Model sizing for RTX 5060 Ti**: The 16 GB VRAM ceiling makes Qwen 3.5 32B impractical without aggressive quantization. Test whether Qwen 3.5 8B provides sufficient quality for the personality and tool-calling use cases. If not, evaluate renting cloud GPU time for a larger model or purchasing a second GPU.

**Embedding model colocation**: Should the embedding model (nomic-embed-text) run on the same Ollama instance as the chat model? This shares the GPU but adds contention. Alternative: run embeddings on CPU (slower but avoids GPU contention) or dedicate a separate embedding endpoint.

**Council memory governance**: When two agents contribute conflicting information, which takes precedence? Options include confidence scores, recency, source-agent trust levels, or human arbitration. Needs a designed conflict resolution policy.

**Email agent architecture**: Email lacks real-time events. IMAP IDLE provides push-like behavior but has reliability issues. Evaluate polling interval vs. IDLE, and how to handle email threads that span days (long conversation context).

**Dapr Agents v1.0 evolution**: Monitor whether future dapr-agents releases add better hooks for custom LLM clients or state management. The ecosystem is young (651 GitHub stars) and evolving rapidly. The PydanticAI-in-raw-actors architecture could be revisited if DurableAgent gains pluggable LLM backends.

**Multi-model routing**: Should different agents use different models? A simpler agent (Email auto-responder) might use a 1.5B model while a complex agent (Discord helper) uses the 8B. PydanticAI supports per-agent model configuration natively.

---

## 9. Risk assessment

### High risk

**GPU memory exhaustion**: A single RTX 5060 Ti with 16 GB VRAM is the primary bottleneck. Concurrent inference requests from 5 agents could exhaust KV cache. **Mitigation**: Set `OLLAMA_NUM_PARALLEL=2`, implement request queuing with backpressure, and use Dapr circuit breakers to gracefully degrade. Monitor GPU memory via Prometheus + `nvidia-smi` exporter. Limit context window length per request.

**Dapr Agents SDK immaturity**: At ~651 GitHub stars and 20 releases in under a year, the dapr-agents ecosystem is still early. Breaking changes are possible. **Mitigation**: The architecture deliberately avoids deep coupling to dapr-agents by using PydanticAI as the agent brain and raw Dapr actors. Only Dapr's core building blocks (state, pub/sub, actors) are used, and those are CNCF-graduated and battle-tested.

### Medium risk

**PostgreSQL RLS complexity**: RLS policies add operational complexity. Misconfigured connection pools could bypass RLS if `app.agent_id` isn't set. **Mitigation**: Wrap pool checkout in a context manager that always sets the session variable. Write integration tests that verify cross-agent isolation.

**MCP server reliability**: MCP is a young protocol (spec v2025-11-25). Tool discovery failures could leave agents without capabilities. **Mitigation**: Cache tool definitions, implement graceful degradation when tools are unavailable, and use PydanticAI's `prepare` function to conditionally include tools.

**Context window management**: Long conversations fill context windows, degrading quality and increasing latency. **Mitigation**: Implement sliding window truncation, periodic conversation summarization, and explicit "memory commit" operations where important context is saved to private memory.

### Low risk

**Channel adapter library changes**: Platform SDK updates (discord.py, slack_bolt, etc.) could introduce breaking changes. **Mitigation**: Pin dependency versions, wrap platform SDKs behind the UnifiedMessage abstraction layer.

**Kubernetes cluster single-node failure**: Running everything on one k3s node means any hardware failure takes down the entire system. **Mitigation**: Automated PostgreSQL backups, documented recovery procedures, and consideration of a secondary node for critical infrastructure.

---

## 10. Repository structure

```
pillywiggins/
├── README.md
├── pyproject.toml                      # uv/poetry project config
├── Dockerfile
├── .sops.yaml                          # SOPS encryption rules
├── .github/
│   └── workflows/
│       ├── ci.yaml                     # Lint, test, build
│       └── deploy.yaml                 # Helm deploy to k3s
├── src/
│   └── pillywiggins/
│       ├── __init__.py
│       ├── main.py                     # Entrypoint: parse args, start adapter + actor host
│       ├── config.py                   # Pydantic Settings for env/config
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py                 # PillywigginActor base class
│       │   ├── brain.py                # PydanticAI agent definition + tools
│       │   ├── deps.py                 # AgentDeps dataclass
│       │   └── personality.py          # Personality loader (ConfigMap → dict)
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base.py                 # BaseAdapter ABC
│       │   ├── discord_adapter.py
│       │   ├── slack_adapter.py
│       │   ├── telegram_adapter.py
│       │   ├── matrix_adapter.py
│       │   └── email_adapter.py
│       ├── memory/
│       │   ├── __init__.py
│       │   ├── private.py              # Private memory (pgvector + RLS)
│       │   ├── council.py              # Council memory (shared pgvector)
│       │   ├── cache.py                # Redis conversation cache
│       │   └── embeddings.py           # Embedding generation (Ollama)
│       ├── messages/
│       │   ├── __init__.py
│       │   └── unified.py              # UnifiedMessage, ChannelType
│       ├── tools/
│       │   ├── __init__.py
│       │   └── servers/
│       │       ├── core_tools.py       # MCP server: core utilities
│       │       └── memory_tools.py     # MCP server: memory operations
│       ├── scheduling/
│       │   ├── __init__.py
│       │   ├── reminders.py            # Dapr Reminder management
│       │   └── cron.py                 # APScheduler personality cron
│       └── observability/
│           ├── __init__.py
│           ├── health.py               # /healthz, /readyz endpoints
│           └── tracing.py              # OpenTelemetry setup
├── tests/
│   ├── conftest.py
│   ├── test_brain.py                   # PydanticAI agent tests (TestModel)
│   ├── test_memory.py                  # Memory isolation tests
│   ├── test_adapters.py                # Adapter normalization tests
│   └── test_council.py                 # Council memory validation tests
├── helm/
│   └── pillywiggins/
│       ├── Chart.yaml
│       ├── values.yaml
│       ├── values-dev.yaml
│       └── templates/
│           └── ...                     # (structure from Section 6)
├── k8s/
│   ├── secrets/                        # SOPS-encrypted secret manifests
│   │   ├── discord-secrets.enc.yaml
│   │   ├── slack-secrets.enc.yaml
│   │   ├── postgres-secrets.enc.yaml
│   │   └── redis-secrets.enc.yaml
│   └── base/                           # Kustomize base (if not using Helm for everything)
│       └── kustomization.yaml
├── nix/
│   ├── flake.nix                       # NixOS dev environment
│   └── gpu-operator.nix                # NVIDIA GPU Operator NixOS config
├── scripts/
│   ├── setup-db.sh                     # PostgreSQL schema + RLS setup
│   ├── pull-models.sh                  # Ollama model pulls
│   └── dev-tunnel.sh                   # Port-forward for local dev
└── docs/
    ├── DESIGN.md                       # This document
    ├── ARCHITECTURE.md                 # Architecture diagrams (Mermaid)
    ├── RUNBOOK.md                      # Operations runbook
    └── PERSONALITY-GUIDE.md            # How to write agent personalities
```

---

## Conclusion: build the foundation first, let the council grow

The critical insight in this architecture is the **separation between the agent brain (PydanticAI) and the agent infrastructure (Dapr actors)**. PydanticAI agents are stateless singletons — lightweight, testable, and model-swappable. Dapr actors provide the stateful shell — durable, isolated, and distributed. This separation means you can iterate on agent intelligence (prompts, tools, models) without touching infrastructure, and scale infrastructure without rewriting agent logic.

Start Phase 1 with a single Discord agent. The temptation to build everything at once is strong, but **a working agent talking on Discord within the first week** provides the motivational fuel and integration test harness for everything that follows. The actor base class, memory system, and council patterns can be layered incrementally once the foundation proves solid.

The RTX 5060 Ti is the binding constraint. Every architectural decision should be evaluated against its GPU memory impact. Qwen 3.5 8B quantized is the pragmatic choice today; the upgrade path to vLLM with larger models or multi-GPU sharding is designed in but not required for initial deployment. The council of agents is only as intelligent as the model powering them, so monitor quality closely and budget for GPU upgrades if the 8B model proves insufficient for the personality depth and tool-calling reliability the project demands.