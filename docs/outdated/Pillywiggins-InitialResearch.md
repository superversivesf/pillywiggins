# Building Pillywiggins: a multi-agent framework from scratch

**Python plus Dapr virtual actors on k3s is the fastest path to a production-quality implementation of your per-channel-agent architecture.** This combination pairs Python's unmatched AI ecosystem — PydanticAI for agent brains, mature channel adapters for every platform — with Dapr's Kubernetes-native actor model that enforces per-agent isolation, persistence, and scheduling out of the box. The architecture maps cleanly: each channel agent becomes a Dapr virtual actor with private state, all actors share a skill registry and council memory via pub/sub and PostgreSQL, and NATS JetStream handles inter-agent messaging. What follows is a complete blueprint to get Pillywiggins running on your k3s cluster with NVIDIA GPUs, Ollama, and n8n.

---

## Python wins the language battle, but not for the obvious reason

The intuitive argument for Python is ecosystem depth — and that argument is correct. **PydanticAI v1** (stable since September 2025, 16K+ stars) provides type-safe agent construction with dependency injection, perfect for stamping out per-channel agents with different personalities. LangGraph 1.0 shipped in October 2025 with durable execution and checkpointing. CrewAI raised $18M and runs at 60% of Fortune 500 companies. Every model provider SDK (OpenAI, Anthropic, Ollama), every vector database client (Qdrant, ChromaDB, pgvector), and every embedding library (sentence-transformers, HuggingFace transformers) is Python-first. No other language comes close.

But the real reason Python wins for Pillywiggins is that **Dapr Agents — released March 2025 by CNCF — provides a Python-native actor model framework purpose-built for AI agents on Kubernetes**. This eliminates Python's traditional weakness (no built-in actor/isolation primitives) while preserving its ecosystem advantage. Each channel agent becomes a Dapr virtual actor with private state, single-threaded message processing, and persistent reminders for scheduling — the exact isolation semantics you need, enforced by the runtime rather than by convention.

C#/.NET with Orleans deserves serious consideration. Orleans invented virtual actors, and its Grains map perfectly to per-channel agents: private state, identity-based activation, built-in timers and reminders, and location transparency. The newly GA'd Microsoft Agent Framework 1.0 (April 3, 2026) unifies Semantic Kernel and AutoGen into a production-grade agent platform. The fatal flaw is channel adapter coverage: **Slack has no official Bolt SDK for .NET**, and Matrix support is immature (LibMatrix is actively developed but small-community). If your channel mix were different, Orleans would be the technically superior choice.

TypeScript excels at channel adapters — discord.js (2M+ weekly npm downloads) and grammY are best-in-class — and its event loop handles thousands of concurrent WebSocket connections elegantly. But it lacks local ML inference, has shallower vector DB integrations, and its agent frameworks (Vercel AI SDK 6, Mastra) trail Python's by 12–18 months of maturity. A polyglot approach (TypeScript for adapters, Python for AI) sounds appealing but adds operational complexity that a solo developer should avoid: two runtimes, two build pipelines, cross-service debugging, and serialization overhead on every message.

| Criterion | Python | TypeScript | C#/.NET |
|---|---|---|---|
| AI ecosystem depth | ★★★★★ | ★★★ | ★★★★ |
| Channel adapter coverage | ★★★★★ | ★★★★★ | ★★★ |
| Per-agent isolation primitives | ★★★★ (via Dapr) | ★★ | ★★★★★ (Orleans) |
| Per-agent scheduling | ★★★★★ (Dapr + APScheduler) | ★★★★ (BullMQ) | ★★★★★ (Orleans Reminders) |
| K8s deployment | ★★★★ | ★★★★ | ★★★★★ |
| Solo developer velocity | ★★★★★ | ★★★★ | ★★★ |

---

## The Dapr actor model makes per-channel isolation a first-class primitive

The core insight driving this architecture is that Pillywiggins' per-channel-agent pattern is isomorphic to the virtual actor model. Each channel agent is a stateful, message-driven, isolated entity with a unique identity — that's literally the definition of an actor. Dapr Actors, purpose-built for Kubernetes, provide this mapping with zero custom infrastructure.

Each agent pod contains two containers: your Python agent code and a Dapr sidecar (`daprd`) injected automatically via annotation. The sidecar handles state management, pub/sub messaging, service invocation, secrets access, and metrics — all through a simple localhost HTTP/gRPC API. Your agent code never touches Kubernetes APIs, NATS clients, or database drivers directly. Deploying a new channel agent is as simple as adding a Deployment YAML with `dapr.io/enabled: "true"` and `dapr.io/app-id: "discord-agent"`.

```
┌─────────────────────────────────────┐
│          discord-agent pod          │
│  ┌──────────────┐ ┌──────────────┐  │
│  │ Python Agent  │ │ Dapr Sidecar │  │
│  │ - discord.py  │←→│ - State mgmt │  │
│  │ - PydanticAI  │ │ - Pub/sub    │  │
│  │ - Personality  │ │ - Secrets    │  │
│  │ - APScheduler │ │ - Metrics    │  │
│  └──────────────┘ └──────────────┘  │
└─────────────────────────────────────┘
```

The alternative actor frameworks fall short for this specific stack. **Orleans** is .NET-only — wrong for a Python-first approach. **Proto.Actor**'s Python SDK is unstable. **Akka.NET** is JVM/.NET-centric and requires manual Kubernetes integration. Dapr is the only framework that is simultaneously polyglot, Kubernetes-native, Python-supported, and CNCF-graduated. It scales to thousands of actors on a single core with **50ms scale-from-zero latency**, more than sufficient for five channel agents.

One pod per agent is the correct pod structure. This provides failure isolation (a crashing Telegram agent doesn't take down Discord), independent deployment (update Matrix agent without touching Slack), and clear resource boundaries. Shared infrastructure — Ollama, PostgreSQL, Redis, NATS, n8n — runs in separate pods within the same namespace.

---

## Council memory, private memory, and the skill registry

The three data planes in Pillywiggins — private agent memory, council memory, and the shared skill registry — each require different isolation guarantees and access patterns.

**Private memory** stores each agent's conversation history, personality state, and episodic memories. PostgreSQL with Row-Level Security enforces isolation at the database level, not the application level. Each agent's database connection sets `app.current_channel` to its UUID; an RLS policy ensures queries only return rows matching that channel, even if application code has bugs. This is defense-in-depth: a compromised Discord agent literally cannot read Slack agent memories through SQL. For vector similarity search on private memories, **pgvector** with HNSW indexing runs in the same PostgreSQL instance, achieving **471 QPS at 99% recall on 50M vectors** — vastly more than agent memory requires.

**Council memory** is the shared knowledge space where agents contribute tagged insights. The schema is simple: a `council_memories` table with `contributing_agent`, `tags[]` (PostgreSQL array), `content`, `embedding` (pgvector), and timestamps. Any agent can read all council entries. Writes go through a restricted path — either a dedicated "scribe" Dapr actor or a validated write endpoint — to prevent a compromised agent from flooding the council. Pub/sub notifications (via NATS through Dapr) alert all agents when new council entries arrive, so they can incorporate fresh insights into their context windows.

**The shared skill registry** is best implemented as MCP (Model Context Protocol) servers. MCP has become the de facto standard for tool connectivity — **7,000+ servers on the Smithery registry** — and every major agent framework supports it natively: PydanticAI, LangGraph, Semantic Kernel, CrewAI. Define each tool once as an MCP server (a small HTTP service), register it in a central gateway, and all agents discover and call it. Your existing n8n workflows become tools by exposing them as webhook-triggered MCP servers. The `mcp-gateway-registry` project provides centralized discovery, OAuth authentication, and security scanning for registered tools.

For the inter-agent message bus, **NATS JetStream** is the clear choice over Redis Streams, RabbitMQ, or Kafka. NATS is a single binary with an official Helm chart (`helm install my-nats nats/nats`), consumes ~50MB RAM, supports fire-and-forget pub/sub and durable streams in the same system, and integrates with Dapr as a pub/sub component with zero additional code. Subjects like `pillywiggins.council.memory.written` and `pillywiggins.skill.registered` cost nothing to create — no partition planning, no exchange configuration. Since you already run Redis for caching, keep Redis for state/caching and use NATS purely for messaging.

---

## Scheduling that actually works: Dapr Reminders plus APScheduler

Existing frameworks reportedly handle scheduling poorly. This is solvable with a two-tier approach: **Dapr Reminders** for persistent, crash-surviving schedules and **APScheduler** for flexible in-process cron within each agent.

Dapr Reminders are built into the actor model. Each agent actor can register named reminders ("daily-summary", "hourly-heartbeat") that persist across pod restarts and fire as messages to the actor's message handler. They integrate directly into the agent loop — a reminder triggers the same ReAct cycle as a channel message, just with a different context. APScheduler's `AsyncIOScheduler` adds finer-grained control: cron expressions, interval triggers, one-off delayed tasks, and persistent job stores backed by Redis or PostgreSQL. Running APScheduler in-process inside each agent pod means zero external dependencies beyond what you already have.

This combination covers every scheduling pattern: periodic health checks (Dapr timer, transient), daily channel summaries (Dapr reminder, persistent), complex cron expressions (APScheduler), and one-off delayed tasks (APScheduler with Redis job store). Kubernetes CronJobs are complementary for cluster-level operations (database backups, log rotation) but wrong for per-agent scheduling — they spin up new pods per execution with cold start overhead and no access to agent state.

---

## Security requires layers, not silver bullets

Multi-agent systems introduce attack surfaces that don't exist in single-agent architectures. The most dangerous is **prompt injection propagation**: a malicious message in one channel could manipulate that agent into writing poisoned content to council memory, which other agents then incorporate into their context windows. No defense is perfect — OpenAI stated in December 2025 that prompt injection "is unlikely to ever be fully solved" — so the strategy is defense-in-depth.

**The "Agents Rule of Two"** (from Meta's security research) is the foundational principle: never allow more than two of these three properties simultaneously per agent — access to private data, exposure to untrusted content, and ability to change state. Channel agents process untrusted messages and execute tools, so they should not have direct write access to other agents' private memory. Council memory writes should pass through a validation layer.

For tool execution sandboxing, **gVisor** (`runsc`) should be the default container runtime class in k3s. It intercepts syscalls via a user-space kernel, preventing container escapes that frontier LLMs can now discover and exploit (demonstrated in a 2026 SandboxEscapeBench paper). Configure containerd to use gVisor via RuntimeClass and apply it to all tool execution pods. Google's **Agent Sandbox** project (launched at KubeCon NA 2025) provides a Kubernetes-native `SandboxWarmPool` CRD for pre-booted sandboxed pods with sub-second cold starts. For tools requiring GPU access, gVisor works — Modal has demonstrated H100/A100 support. Firecracker microVMs offer stronger isolation (separate kernel per workload, no disclosed VM escapes) but lack GPU passthrough.

For secrets management, **SOPS with age encryption** is the right starting point for a k3s homelab. Encrypt secret values client-side, store encrypted YAML safely in Git, and decrypt at deploy time via Flux CD's native SOPS integration. No external cloud dependency, no Vault cluster to manage. Structure secrets per-platform: `discord-bot-token`, `slack-bot-token`, `telegram-bot-token`, each mounted only into its respective agent pod via RBAC-limited ServiceAccounts.

Rate limiting for LLM calls needs three layers: a **per-agent token bucket** (preventing one chatty channel from starving others), a **per-provider circuit breaker** (three-state: closed → open after 5 failures → half-open after 60s), and an **aggregate cost circuit breaker** (pause all agents if daily spending exceeds 5× baseline). Real incidents of $47,000 from a LangChain retry loop and $30,000 from an agent loop on Reddit demonstrate why the cost circuit breaker is non-negotiable. Semantic caching of LLM responses reduces API calls **60–80%** for repeated queries.

---

## The agent loop: from channel message to response

Each channel agent runs a modified ReAct loop triggered by three event types: channel messages (primary), cron/reminder firings, and council memory notifications. The loop follows a consistent pattern regardless of trigger source.

**Context assembly** is the most architecturally important step. The agent gathers its system prompt and personality (from a mounted ConfigMap, hot-reloadable without restart), conversation history (from Redis via Dapr state), relevant council memories (PostgreSQL vector search), and available tools (from the MCP skill registry). This assembled context goes to the LLM — Ollama at `http://ollama.ollama.svc:80/api/chat` for local inference, with fallback to cloud providers for capability gaps.

PydanticAI structures the agent brain cleanly. Each channel agent is a `PydanticAI Agent` instance with injected dependencies — channel-specific personality, memory namespace, scheduling config — and tools registered from the shared MCP registry. The type-safe tool contracts (Pydantic validation on inputs and outputs) are critical when multiple agents share tools: malformed inputs are caught at development time rather than production.

```python
class PillywigginAgent:
    def __init__(self, channel: str, personality: str):
        self.agent = Agent(
            model="ollama:llama3.2",
            system_prompt=personality,
            deps_type=ChannelDeps,
        )
        self.state = DaprStateStore(channel)
        self.scheduler = AsyncIOScheduler()

    async def handle_message(self, message: ChannelMessage):
        context = await self.assemble_context(message)
        result = await self.agent.run(context)
        await self.dispatch_response(result)
        await self.state.save_turn(message, result)
```

Hot-reloading personality and configuration without restarting pods uses ConfigMap volume mounts with a file watcher. Kubernetes updates mounted ConfigMap files via symlink swap within 30–60 seconds. The agent detects the change, reloads its system prompt, and the next message uses the new personality. **Stakater Reloader** handles the fallback case where environment variables change — it triggers rolling updates automatically.

---

## The complete Pillywiggins technology stack

| Component | Technology | Why |
|---|---|---|
| Language | Python 3.12+ | Deepest AI ecosystem, Dapr Agents SDK |
| Agent brain | PydanticAI v1 | Type-safe, model-agnostic, dependency injection |
| Actor framework | Dapr Actors + Dapr Agents | K8s-native, virtual actors, Python SDK |
| LLM inference | Ollama on k3s (GPU) | Local, self-hosted, Helm chart available |
| Message bus | NATS JetStream (via Dapr) | Single binary, ~50MB, CloudEvents native |
| Private memory | PostgreSQL + pgvector + RLS | Enforced isolation, unified vector search |
| Council memory | PostgreSQL (tagged table) | SQL queries on tags, agent attribution |
| Agent state cache | Redis (via Dapr state) | Fast conversation history reads |
| Skill registry | MCP servers + gateway | 7K+ existing tools, framework-agnostic |
| Scheduling | Dapr Reminders + APScheduler | Persistent + flexible cron |
| Channel: Discord | discord.py v2 | Async-native, mature, full API |
| Channel: Slack | slack_bolt (Python) | Official SDK, Socket Mode |
| Channel: Telegram | python-telegram-bot v21 | Async, full Bot API, excellent docs |
| Channel: Matrix | matrix-nio + NioBot | Async, E2EE support |
| Channel: Email | aiosmtplib + imap-tools | Standard async SMTP/IMAP |
| Secrets | SOPS + age | GitOps-safe, no cloud dependency |
| Sandboxing | gVisor RuntimeClass | Prevents container escapes |
| Observability | Prometheus + Grafana | Built into Dapr sidecar (port 9090) |
| Config reload | Stakater Reloader | Zero-downtime personality updates |
| Automation | n8n (existing) | Workflows exposed as MCP tools |

---

## Phased implementation: running in two weeks

**Phase 1 (Days 1–5): Foundation.** Deploy NATS, PostgreSQL (with pgvector extension), and Redis via Helm on your k3s cluster. Install Dapr (`dapr init -k`). Verify Ollama is accessible from within the cluster. Build a single Discord agent: discord.py adapter → PydanticAI agent with a hardcoded personality → Ollama inference → Discord response. This validates the end-to-end path.

**Phase 2 (Days 6–10): Framework.** Extract the `PillywigginAgent` base class with configurable personality, the ReAct loop, Dapr state integration, and health probes. Build the council memory table in PostgreSQL. Add APScheduler with one test cron job per agent. Create a parameterized Helm chart where channel type, personality, and model are values. Deploy a second agent (Slack or Telegram) to validate multi-agent coexistence.

**Phase 3 (Days 11–15): Full fleet.** Deploy all five channel agents. Wire NATS pub/sub for council memory notifications. Build the MCP skill registry and register your first shared tools (including n8n webhook bridges). Add PostgreSQL RLS policies for private memory isolation. Implement the council memory read/write flow.

**Phase 4 (Weeks 3–4): Hardening.** Add gVisor RuntimeClass for tool execution pods. Implement rate limiting and circuit breakers. Set up Prometheus scraping of Dapr metrics and Grafana dashboards per agent. Add SOPS-encrypted secrets to your Git repo. Configure Stakater Reloader for zero-downtime config updates.

## Conclusion

Pillywiggins' architecture is unusual but not complex when you recognize its isomorphism with the actor model. The per-channel agent pattern maps directly to virtual actors; council memory is a shared event stream with tagged entries; the skill registry is an MCP server catalogue. **Dapr Agents eliminates the gap between Python's weak isolation primitives and the runtime-enforced isolation you need**, without requiring C#/.NET or abandoning Python's AI ecosystem. The most underrated decision in this stack is PostgreSQL RLS for memory isolation — it means a bug in your application code cannot leak one agent's memories to another, because the database enforces boundaries regardless of what queries your code generates. Start with one agent, validate the loop, and expand. The architecture scales to dozens of channels without structural changes.