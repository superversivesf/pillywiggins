# Building a 24/7 autonomous AI agent on self-hosted infrastructure in 2026

**The stack that works today: LangGraph or OpenClaw for orchestration, vLLM or SGLang for inference, Qwen 3.5 or DeepSeek V3.2 as the model, Mem0 for persistent memory, MCP for tool integration, and Temporal for durable workflow execution — all deployed on k3s with NVIDIA GPUs managed by NixOS.** The open-source agent ecosystem has matured dramatically since late 2025, anchored by OpenClaw's explosive growth (247,000+ GitHub stars in four months) which proved that always-on, multi-channel AI agents are architecturally tractable. This report covers every layer of the stack with specific, actionable technical guidance for a self-hosted k3s deployment.

---

## OpenClaw established the reference architecture for always-on agents

OpenClaw, created by Peter Steinberger and launched in November 2025, is the dominant open-source framework for personal AI agents. Its MIT-licensed, Node.js-based architecture runs as a background daemon connecting **24+ messaging platforms** to an LLM-powered agent runtime. It accumulated 247,000+ GitHub stars by March 2026 — one of the fastest-growing repos in GitHub history. Steinberger joined OpenAI in February 2026; a non-profit foundation now stewards the project.

OpenClaw's architecture separates into three clean layers. The **Channel Layer** normalizes messages from WhatsApp, Telegram, Slack, Discord, Signal, Matrix, IRC, Microsoft Teams, and 16+ other platforms into a unified message object. The **Brain Layer** is a WebSocket-based gateway at `ws://127.0.0.1:18789` handling routing, authentication, and serialized execution — it never touches the model directly. The **Body Layer** provides tools, browser automation, file access, and MCP integration for external tool access.

The architectural insight that makes OpenClaw feel "alive" is its **five input types**: standard messages from channels, heartbeats (timer fires every ~30 minutes to check inbox/calendar/tasks), cron jobs (crontab-syntax scheduled events), hooks (internal state changes trigger custom prompts), and webhooks (external systems push real-time events). All five follow the same pattern: event enters queue, agent processes, state updates.

OpenClaw's memory is deliberately transparent — flat markdown files in `~/.openclaw/workspace/` including `MEMORY.md` for long-term facts, `SOUL.md` for personality, daily ephemeral logs, and JSONL session transcripts. Context compaction summarizes older turns when the window fills. This file-based approach survives restarts trivially and remains human-readable.

**NanoClaw** is the security-first alternative, built by Lazer and Gavriel Cohen in just **~3,900 lines of code across 15 files** versus OpenClaw's ~430,000 lines. Its key innovation is **OS-level container isolation** — each agent session runs in an ephemeral Docker container as an unprivileged user with explicit mount allowlists blocking `.ssh`, `.gnupg`, `.aws`, and `.env` by default. NanoClaw uses SQLite instead of flat files and builds on Anthropic's Agent SDK. The trade-off is fewer channel adapters (WhatsApp native, others via skills) and a more constrained feature set.

For building your own OpenClaw-style system from scratch on k3s, the core pattern is: channel adapter layer → message queue (Redis Streams for single-node, NATS or Kafka for scale) → agent runtime with per-session serialized execution → response router that formats replies per platform. The **Vercel Chat SDK** (`npm i chat`, MIT licensed, February 2026) deserves special attention — it provides type-safe adapters for Slack, Discord, Telegram, Teams, Google Chat, and WhatsApp with JSX components that render natively per platform and first-class AI SDK streaming integration.

---

## LangGraph leads for production agent orchestration, but the field is rich

**LangGraph** (by LangChain, ~24.8K stars, 34.5M+ downloads in 2025) is the strongest choice for a 24/7 autonomous agent requiring fault tolerance. Its graph-based architecture uses directed cyclic graphs where nodes are functions, edges are transitions, and conditional edges enable decisions. The killer feature is **built-in checkpointing with PostgreSQL and Redis backends** — the graph state snapshots at every super-step, enabling fault recovery (if a node fails at step 7/10, it resumes from step 7), time-travel debugging, and durable execution across pod restarts. Thread-based state management with a `Store` interface provides both short-term and long-term memory. Production users include Uber, Cisco, and Klarna ($60M annual savings reported). The trade-off is a steep learning curve (4–8 weeks to production) and a large dependency tree from the LangChain ecosystem.

**Agno** (formerly Phidata, 39,100+ stars) is the strongest alternative with a production-first design. Its stateless, session-scoped architecture is inherently Kubernetes-friendly with built-in memory (session + cross-session), knowledge integration with 20+ vector stores, MCP + A2A protocol support, and a self-hosted runtime (AgentOS) with **3μs agent instantiation**. Agno supports Ollama for local open-weight models and provides Kubernetes deployment templates.

**CrewAI** (44,300+ stars) excels at rapid prototyping with its intuitive role-based multi-agent design — define agents with role, backstory, and goal, assemble them into crews. However, it **lacks built-in durable checkpointing**, which is a critical weakness for 24/7 operation. Teams commonly prototype with CrewAI and migrate to LangGraph for production.

**smolagents** (HuggingFace, 26,300+ stars) deserves attention for its **best-in-class open-weight model integration**. Its code-first approach (the LLM writes Python to invoke tools, using 30% fewer tokens than JSON tool calls) is transparent and hackable. Native HuggingFace integration means seamless local model support. The limitation is no built-in persistence — you must wrap it in your own checkpointing layer.

**DSPy** (Stanford, ~28K stars, v3.0) is not an orchestration framework but a complementary tool for **optimizing open-weight model performance**. It compiles declarative Python programs into optimized prompts and weights, making smaller models (7B–70B) competitive with much larger ones. Use DSPy to tune the LLM calls within whatever orchestration framework you choose.

**Microsoft Agent Framework 1.0** shipped April 3, 2026, merging AutoGen and Semantic Kernel. It offers enterprise-grade multi-agent orchestration with A2A and MCP support, but is optimized for the Azure ecosystem and less natural for self-hosted open-weight model deployments. AutoGen itself is now in maintenance mode.

Two other noteworthy frameworks: **Mastra** (22,276+ stars, by the Gatsby team) is TypeScript-native with graph-based workflows and 3,300+ model routing — excellent if you prefer TypeScript but not ideal for Python/GPU-focused stacks. **Haystack** (by deepset) provides strong pipeline-based architecture with breakpoint save/resume capability, best suited for RAG-heavy agent workloads.

---

## vLLM and SGLang dominate inference for agentic workloads

For serving open-weight models on k3s with NVIDIA GPUs, two inference engines stand above the rest. **vLLM** (74,900 stars) offers the most complete tool-calling implementation with native parsers for Hermes, Llama3 JSON, Mistral, Granite, and other formats. Launch it with `--enable-auto-tool-choice --tool-call-parser hermes` and you get OpenAI-compatible function calling that works with Qwen, DeepSeek, and Llama models. Structured output support is comprehensive — JSON schema, regex, EBNF grammar — backed by XGrammar (fastest), Outlines, and LLGuidance. Multi-GPU tensor parallelism, official Docker images, Helm charts, and broad model support make vLLM the safest production choice. Throughput on H100: **~12,500 tok/s** for Llama 3.1 8B at bf16.

**SGLang** (25,400 stars) is **29% faster than vLLM** in raw throughput (~16,200 tok/s on the same benchmark) and **3.1x faster on DeepSeek models** — it is the officially endorsed engine for DeepSeek. Its RadixAttention system automatically reuses KV cache entries via a radix tree, delivering 10–20% improvements on multi-turn agent workflows with shared context. Structured output via compressed FSM is 3x faster than unconstrained generation. SGLang is the better choice if your workload is agent-heavy with many multi-turn conversations or if you plan to run DeepSeek models.

The practical recommendation: use **vLLM** as the default (most mature Kubernetes integration, broadest tool-calling support, largest community) and **SGLang** if you're running DeepSeek models or need maximum throughput for multi-turn workloads.

**TGI (HuggingFace) entered maintenance mode in December 2025** — do not adopt for new deployments. **Ollama** (167K stars) is excellent for development and prototyping with its single-command simplicity, but processes requests sequentially with limited batching — not suitable for production agentic workloads. **ExLlamaV2** remains the best choice for consumer GPUs (RTX 3090/4090) where EXL2 quantization provides superior quality-per-bit. **LMDeploy** matches SGLang's throughput and excels with quantized models (INT4 runs 2.4x faster than FP16). **TensorRT-LLM** delivers the highest peak throughput on NVIDIA hardware but requires a 28+ minute compilation step.

---

## Qwen 3.5 and DeepSeek V3.2 lead open models for agent tasks

The open-weight model landscape for agentic tasks has a clear top tier. **Qwen 3.5** (Alibaba, March 2026) is the most versatile choice — the 397B-A17B MoE variant uses only 17B active parameters while competing with GPT-5 and Claude 4.5 on many benchmarks. The size range spans 0.8B to 397B with **262K native context extending to 1M+ tokens**, native tool calling in Hermes-compatible format, switchable thinking modes, and the most permissive **Apache 2.0 license**. The 27B dense model fits a single 48GB GPU; the 9B model fits a 24GB GPU at Q4 quantization.

**DeepSeek V3.2** is the strongest reasoning + agent model, trained on **1,800+ environments and 85,000+ agent tasks**. It was the first model to integrate thinking directly into tool-use — supporting tool calls in both thinking and non-thinking modes. The MIT license is fully permissive. The catch: it requires **8x H200 GPUs** for efficient serving of the full 671B model (37B active). SGLang is required for competitive performance.

**Gemma 4** (Google, Apache 2.0) is the best single-GPU option — the 31B dense model fits one H100 at FP16 with native function calling and structured output support, while the 26B-A4B MoE variant has only 3.8B active parameters for near-4B serving cost with 256K context. **Kimi K2.5** (Moonshot AI, 1T total / 32B active, Modified MIT) leads open-weight coding agents at **76.8% on SWE-bench Verified**. **GLM-5** (Zhipu AI, MIT) achieves 77.8% on SWE-bench and the GLM-4.5 variant leads the BFCL function-calling leaderboard at 70.85% overall accuracy.

For a k3s deployment, the hardware-to-model mapping is clear: single 24GB GPU → **Qwen 3.5-9B or Gemma 4 E4B**; single 48GB → **Gemma 4 31B or Qwen 3.5-27B**; single 80GB H100 → **Gemma 4 31B FP16 or Llama 3.3 70B FP8**; 2x 80GB → **Qwen 3.5-122B-A10B**; 8x 80GB → **DeepSeek V3.2 or Qwen 3.5-397B**.

---

## Mem0 and Letta provide the strongest memory architectures

Persistent memory is non-negotiable for a 24/7 agent. **Mem0** (48K+ stars, Apache 2.0, published at ECAI 2025) is the best standalone memory layer — framework-agnostic, self-hostable, with a three-tier memory system (user, session, agent scopes) backed by a hybrid store combining vectors, graph relationships, and key-value lookups. Its Memory Compression Engine achieves **up to 80% reduction in prompt tokens** while maintaining 26% higher response accuracy versus OpenAI's memory and **91% lower p95 latency** on the LOCOMO benchmark. It supports 19 vector backends including Qdrant, Chroma, pgvector, and Redis, and the FastEmbed integration enables fully local embedding with zero API calls.

**Letta** (formerly MemGPT) takes a fundamentally different approach — it is an entire agent runtime, not just a memory component. Its OS-inspired memory hierarchy provides Core Memory (always in-context, like RAM), Recall Memory (searchable conversation history, like disk cache), and Archival Memory (long-term storage via tool calls, like cold storage). The agent self-edits memory using explicit tools: `memory_replace`, `memory_insert`, `memory_rethink`. This is the most sophisticated memory model for long-running autonomous agents but requires adopting Letta as your entire platform — switching away means rewriting everything.

**Zep** (built on Graphiti, Apache 2.0) excels at **temporal reasoning** — its bi-temporal knowledge graph tracks when events occurred and when they were recorded, with edge invalidation when facts change. It achieves 94.8% on the DMR benchmark and sub-50ms average query latency via hybrid search with no LLM calls during retrieval. Choose Zep when your agent needs to reason about how facts evolve over time. **LangMem** integrates tightly with LangGraph and uniquely supports procedural memory (agents updating their own system instructions), but has concerning search latencies (p50: 17.99s, p95: 59.82s).

For vector storage, the 2026 trend is clear: **pgvector with pgvectorscale** (benchmarked at 471 QPS at 99% recall on 50M vectors) is the top choice if you already run PostgreSQL — one database for everything. **Qdrant** (Rust-based, excellent self-hosting) is the best dedicated vector DB. **LanceDB** (embedded, serverless, zero-ops) is the "SQLite of vector databases" — perfect for privacy-sensitive deployments where you want in-process vector search with zero network latency.

---

## MCP has become the universal standard for tool integration

The **Model Context Protocol** (MCP), introduced by Anthropic in November 2024, has achieved ecosystem dominance at unprecedented speed. In December 2025, Anthropic donated MCP to the **Agentic AI Foundation under the Linux Foundation**, co-founded with Block and OpenAI, with supporting members including AWS, Google, Microsoft, and Cloudflare. The numbers are staggering: **97 million monthly SDK downloads**, **5,800+ MCP servers**, and **300+ MCP clients**. OpenAI deprecated its Assistants API in favor of MCP (sunset mid-2026).

MCP uses JSON-RPC 2.0 transport and follows the Language Server Protocol pattern — write a tool once as an MCP server, and it works with any MCP-compatible client regardless of the underlying model. For a self-hosted agent, this means building your tools (file access, database queries, web search, calendar integration) as MCP servers and connecting them to your agent framework. smolagents, LangGraph, CrewAI, and Haystack all have MCP client support. Key MCP servers already exist for GitHub, Notion, Stripe, Hugging Face, and Graphiti (Zep's memory).

For open models, tool calling works through inference server parsing rather than API-level support. vLLM provides built-in parsers for multiple formats — `hermes` (used by Qwen models), `llama3_json`, `mistral`, `granite4`. Launch vLLM with `--enable-auto-tool-choice --tool-call-parser hermes` and tool definitions in the `/v1/chat/completions` endpoint work identically to OpenAI's API. **Native function calling has largely superseded ReAct** for production use — modern models like DeepSeek V3.2 integrate reasoning directly into tool-use, eliminating the verbose thought-action-observation loop.

A critical reliability consideration: a model that is **90% reliable per tool-calling step achieves only 59% reliability across 5 sequential steps**. For 24/7 agents making dozens of tool calls per task, implement retry middleware with exponential backoff, structured output enforcement via vLLM's guided decoding (XGrammar backend), and circuit breakers at the application level. Budget for models at **30B+ parameters** for reliable multi-step tool calling — the minimum viable size for agentic work has dropped from 70B in early 2025 to roughly 30B in early 2026.

---

## Temporal provides the durable execution backbone for 24/7 operation

**Temporal** is the strongest orchestration choice for the agent core. It records full Event History — every LLM call, every tool invocation, every return value. If the application crashes, it replays deterministically and resumes exactly where it left off without re-running expensive LLM calls. **OpenAI uses Temporal for Codex**, validating it at massive scale. Its Python SDK provides `@workflow.defn` and `@activity.defn` decorators that cleanly separate deterministic orchestration (workflows) from non-deterministic I/O (activities: LLM calls, tool invocations). PydanticAI offers a native `TemporalAgent` wrapper for durable agent execution. Self-host the Temporal server on k3s via its Helm chart or use Temporal Cloud.

**n8n** (40,000+ stars, $2.5B valuation) serves a different role — it excels as a **visual integration and channel adapter layer** with 500+ native integrations, AI Agent nodes with ReAct loops, and LLM support including local models via Ollama. Its self-hosted AI Starter Kit (Docker Compose with n8n + Ollama + Qdrant + PostgreSQL) is the fastest path to a working prototype. Use n8n for webhook handling, channel adapters, and scheduled tasks alongside Temporal for the durable agent core.

For Kubernetes deployment on k3s with NVIDIA GPUs, the setup requires three steps. First, install the **NVIDIA GPU Operator via Helm** (v25.3.4) with k3s-specific containerd socket and config paths. Second, taint GPU nodes with `nvidia.com/gpu=true:NoSchedule` to prevent non-GPU workloads from landing there. Third, deploy vLLM with the **three-probe pattern**: a `startupProbe` hitting `/v1/models` with up to 30 minutes tolerance for model loading, a `livenessProbe` on `/health` for basic process checks, and a `readinessProbe` on `/v1/models` to ensure traffic routes only after the model loads. Set `resources.limits.nvidia.com/gpu: 1` and use PersistentVolumeClaims for model storage to avoid re-downloading 10–140GB models on every pod restart.

For autoscaling, standard CPU-based HPA is meaningless for GPU-bound inference. Use **KEDA with Prometheus metrics** — scale on `vllm_pending_requests_total` rather than CPU utilization. Monitor GPU health with the DCGM Exporter, which exposes `DCGM_FI_DEV_GPU_UTIL` and `DCGM_FI_DEV_FB_USED` for Prometheus scraping. The monitoring stack is three Helm commands: `kube-prometheus-stack` (Prometheus + Grafana + Alertmanager), `grafana/loki-stack` (log aggregation), and DCGM Exporter.

---

## NixOS delivers the strongest host-level infrastructure story

NixOS provides declarative, version-pinned, rollback-capable configuration for every host-level component. A single `configuration.nix` file manages NVIDIA drivers (`hardware.nvidia.package`), the container toolkit (`hardware.nvidia-container-toolkit.enable = true`), k3s service (`services.k3s.enable = true`), and firewall rules. The CUDA binary cache at `cache.nixos-cuda.org` (migrated November 2025) eliminates multi-hour CUDA compilations. Use Nix flakes for reproducible development environments with `cudatoolkit`, `cudaPackages.cudnn`, `python312`, `kubectl`, and `helm` pinned to exact versions. The `nixos-k3s` reference project demonstrates single-command reproducible k3s deployment with GitOps via Flux CD, SOPS for secrets, and declarative Helm chart deployment via `services.k3s.autoDeployCharts`.

---

## The recommended architecture, assembled

The complete system maps to six k3s namespaces. The `llm` namespace runs vLLM (or SGLang) with GPU allocation and model PVCs. The `agent` namespace contains your agent application (LangGraph or custom OpenClaw-style runtime), Temporal workers, and channel adapters. The `data` namespace hosts Qdrant (or pgvector in PostgreSQL) and PostgreSQL for relational data plus LangGraph checkpoints. The `infra` namespace runs the Temporal server, Redis for caching and message queuing, and optionally NATS for pub/sub. The `monitoring` namespace holds Prometheus, Grafana, Loki, and DCGM Exporter. The `integration` namespace optionally runs n8n for visual workflow automation and webhook handling.

The data flow for every user interaction: message arrives from any channel → channel adapter normalizes to unified format → enters message queue (Redis Streams) with per-session serialized processing → Temporal workflow orchestrates the agent loop → activities call vLLM for inference, query vector DB for context, execute MCP tools → Mem0 persists new memories → response routes back through the correct channel adapter with platform-specific formatting (Slack mrkdwn, Discord embeds, Telegram HTML).

- **Start with Docker Compose** using n8n's self-hosted AI starter kit for prototyping, then migrate to k3s manifests for production
- **Use PodDisruptionBudgets** (`minAvailable: 1`) on the vLLM deployment to prevent disruption during cluster maintenance
- **Set memory limits equal to memory requests** for LLM pods to prevent noisy-neighbor OOM kills
- **Implement graceful shutdown** — handle SIGTERM, drain in-flight requests, set `terminationGracePeriodSeconds: 60`
- **Track everything in Git** with ArgoCD or Flux for GitOps-managed k3s manifests

## Conclusion

The 24/7 autonomous agent stack has crystallized around a few clear winners at each layer. OpenClaw proved the architecture; LangGraph or Temporal provide the durable execution guarantees that keep agents running through crashes and restarts; vLLM and SGLang have pulled decisively ahead of all other inference engines; Qwen 3.5 and DeepSeek V3.2 have closed the gap with closed models on tool calling; MCP has unified tool integration under a single standard backed by every major AI company; and Mem0 has made persistent memory a solved problem rather than a research challenge. The most important architectural principle — validated by both OpenClaw and NanoClaw — is to **never expose raw LLM calls to user input**. Always interpose an orchestration gateway that handles routing, queuing, state management, and security enforcement. The second most important principle: implement checkpointing from day one. A 24/7 agent that loses state on restart is not a 24/7 agent — it is a chatbot with uptime aspirations.