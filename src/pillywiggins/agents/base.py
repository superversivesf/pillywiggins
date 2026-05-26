from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from pillywiggins.config import Settings

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from pillywiggins.agents.brain import Agent, create_brain, get_canary_token
from pillywiggins.agents.deps import AgentDeps
from pillywiggins.agents.personality import Personality
from pillywiggins.logging_utils import AgentLogger
from pillywiggins.memory.cache import ConversationCache
from pillywiggins.memory.council import CouncilMemory, TAG_WHITELIST
from pillywiggins.memory.private import PrivateMemory
from pillywiggins.memory.store import ConversationStore
from pillywiggins.skills.registry import SkillRegistry
from pillywiggins.messaging.nats_bus import NatsBus
from pillywiggins.messaging.unified import UnifiedMessage, ChannelType
from pillywiggins.scheduling.scheduler import AgentScheduler
from pillywiggins.security.prompt_sanitizer import (
    PromptSanitizer,
    PromptInjectionError,
    sanitize_or_default,
    sanitize_output,
    check_canary,
)

logger = logging.getLogger(__name__)

# Matches an explicit agent address at the start of a message:
#   @name      (mention/tag)
#   name:     (name followed by colon)
#   name,     (name followed by comma)
_ADDRESS_PATTERN = re.compile(
    r"^(?:@([a-zA-Z0-9_\-]+)|([a-zA-Z0-9_\-]+)[,:])",
    re.UNICODE,
)

# Matches @mentions anywhere in the message body
_MENTION_PATTERN = re.compile(
    r"@([a-zA-Z0-9_\-]+)",
    re.UNICODE,
)



class PillywigginAgent:
    def __init__(
        self,
        agent_id: str,
        personality: Personality,
        model_name: str,
        provider: str,
        base_url: str,
        api_key: str,
        cache: ConversationCache | None = None,
        store: ConversationStore | None = None,
        private_memory: PrivateMemory | None = None,
        skill_registry: SkillRegistry | None = None,
        compact_keep_messages: int = 6,
        compact_truncate_message_chars: int = 2000,
        database_url: str | None = None,
        nats_url: str | None = None,
        mcp_servers: list[dict[str, Any]] | None = None,
        settings: Settings | None = None,
    ):
        self.agent_id = agent_id
        self.personality = personality
        self._model_name = model_name
        self._provider = provider
        self._base_url = base_url
        self._api_key = api_key
        self._cache = cache
        self._store = store
        self._private_memory = private_memory
        self._skill_registry = skill_registry
        self._compact_keep_messages = compact_keep_messages
        self._compact_truncate_message_chars = compact_truncate_message_chars
        self._compact_summary_enabled = (
            settings.compact_summary_enabled if settings is not None else True
        )
        self._compact_threshold_messages = (
            settings.compact_threshold_messages if settings is not None else 20
        )
        self._database_url = database_url
        self._nats_url = nats_url
        self._mcp_servers: list[dict[str, Any]] | None = mcp_servers
        self._settings = settings
        self._aliases: list[str] = [agent_id.lower()]
        self._nats_bus: NatsBus | None = None
        self._scheduler: AgentScheduler | None = None
        self._adapter: Any = None
        self._lock = asyncio.Lock()
        self._agent_logger = AgentLogger(agent_id)
        # Token bucket rate limiter: max calls per window, smoothed via token refill
        if settings:
            self._max_tokens: float = float(getattr(settings, '_llm_rate_limit', 10))
            window: float = float(getattr(settings, '_llm_rate_window', 60.0))
            self._token_rate: float = self._max_tokens / max(window, 1.0)
        else:
            self._max_tokens: float = 10.0
            self._token_rate: float = 10.0 / 60.0
        self._tokens: float = self._max_tokens
        self._last_refill: float = time.monotonic()
        self._brain: Agent = self._rebuild_brain()
        self._seen_mentions_this_limit_cycle: dict[str, int] = {}
        self._conversation_histories: dict[str, list[ModelMessage]] = {}

    def _safe_output(self, output: str) -> str:
        """Apply output sanitization and canary token check."""
        result = sanitize_output(output)
        canary = get_canary_token()
        if check_canary(result, canary):
            logger.warning(
                "Canary token detected in output for %s, replacing response",
                self.agent_id,
            )
            return "[Response filtered for security]"
        return result

    def _rebuild_brain(self) -> Agent:
        """Re-create the brain agent with the current model and skill registry."""
        retries = self._settings.llm_retries if self._settings else 2
        return create_brain(
            self._model_name,
            self._provider,
            self._base_url,
            self._api_key,
            skill_registry=self._skill_registry,
            mcp_servers=self._mcp_servers,
            retries=retries,
        )

    async def load_history(self, conversation_key: str | None = None) -> None:
        key = conversation_key or ""
        if self._cache is not None:
            cached = await self._cache.load(self.agent_id, conversation_key=key)
            if cached is not None:
                self._conversation_histories[key] = cached
                logger.info(
                    "Loaded %d messages from Redis for %s/%s",
                    len(cached),
                    self.agent_id,
                    key or "default",
                )
                return
        if self._store is not None and conversation_key is not None:
            stored = await self._store.load(conversation_key)
            if stored is not None:
                self._conversation_histories[conversation_key] = stored
                logger.info(
                    "Loaded %d messages from PostgreSQL for %s/%s",
                    len(stored),
                    self.agent_id,
                    conversation_key,
                )

    async def _on_nats_message(self, msg_type: str, data: dict, from_agent: str = "", timestamp: str = "") -> None:
        logger.info("Agent %s handling NATS message type=%s from=%s", self.agent_id, msg_type, from_agent or "?")
        if msg_type == "message":
            try:
                channel = ChannelType(data.get("channel", "telegram"))
            except ValueError:
                channel = ChannelType.TELEGRAM
            raw_content = data.get("content", "")
            sanitized_content = sanitize_or_default(raw_content, default="")
            msg = UnifiedMessage(
                channel=channel,
                channel_user_id=data.get("channel_user_id", ""),
                content=sanitized_content,
                conversation_key=data.get("conversation_key", ""),
                metadata={"from_agent": from_agent, "timestamp": timestamp, **data.get("metadata", {})},
            )
            logger.info("Agent %s processing inbound direct message from %s", self.agent_id, from_agent or "?")
            response = await self.process_message(msg)
            if response:
                routing_info = data.get("routing_info")
                if routing_info and routing_info.get("original_channel") == self.personality.channel and self._adapter is not None:
                    conv_key = routing_info.get("original_conversation_key", "")
                    orig_metadata = routing_info.get("original_metadata", {})
                    await self._adapter.send(conv_key, response, orig_metadata)
                    logger.info("Agent %s sent reply directly to user via %s", self.agent_id, self.personality.channel)
                elif self._nats_bus is not None and from_agent:
                    await self._nats_bus.publish_direct(
                        target_agent_id=from_agent,
                        message_type="direct_reply",
                        data={"reply": response, "routing_info": routing_info},
                    )
        elif msg_type == "insight":
            if self._council_memory is not None:
                raw_tags = [from_agent, timestamp, *data.get("tags", [])]
                filtered_tags = [t for t in raw_tags if t in TAG_WHITELIST]
                result = await self._council_memory.write_entry(
                    content=data.get("content", ""),
                    tags=filtered_tags,
                    embedding=data.get("embedding", []),
                    message_type="insight",
                    confidence=1.0,
                )
                success = result.get("success") if isinstance(result, dict) else None
                if not success:
                    logger.warning(
                        "Agent %s council write_entry failed: %s", self.agent_id, result.get("error") if isinstance(result, dict) else result
                    )
        elif msg_type == "direct_reply":
            routing_info = data.get("routing_info")
            reply = data.get("reply", "")
            if routing_info and routing_info.get("original_channel") == self.personality.channel and self._adapter is not None:
                conv_key = routing_info.get("original_conversation_key", "")
                orig_metadata = routing_info.get("original_metadata", {})
                await self._adapter.send(conv_key, reply, orig_metadata)
                logger.info("Agent %s forwarded direct_reply to user via %s", self.agent_id, self.personality.channel)
            else:
                logger.warning("Agent %s received direct_reply but cannot route to user (no adapter or channel mismatch)", self.agent_id)
        elif msg_type in ("skill_published", "skill_deployed"):
            if self._skill_registry is not None:
                self._skill_registry.load_all()
                self._refresh_brain_tools()
        else:
            logger.warning("Agent %s unknown NATS message type: %s", self.agent_id, msg_type)

    async def _start_council_memory(self) -> None:
        if self._database_url is None:
            return
        try:
            settings = self._settings
            council = CouncilMemory(self._database_url, self.agent_id, embedding_dimension=settings.embedding_dimension)
            await council.connect()
            self._council_memory = council
            logger.info("Council memory connected for %s", self.agent_id)
        except Exception:
            logger.warning(
                "Failed to connect council memory for %s", self.agent_id, exc_info=True
            )
            self._council_memory = None

    async def _start_private_memory(self) -> None:
        if self._private_memory is None:
            return
        try:
            if self._private_memory._pool is None:
                await self._private_memory.connect()
                logger.info("Private memory connected for %s", self.agent_id)
        except Exception:
            logger.warning(
                "Failed to connect private memory for %s", self.agent_id, exc_info=True
            )

    async def _start_nats_bus(self) -> None:
        if self._nats_url is None:
            return
        try:
            settings = self._settings
            bus = NatsBus(
                self._nats_url,
                self.agent_id,
                connect_timeout=settings.nats_connect_timeout,
                reconnect_attempts=settings.nats_reconnect_attempts,
            )
            connected = await bus.connect_or_log()
            if connected:
                self._nats_bus = bus
                await bus.subscribe_broadcast(self._on_nats_message)
                await bus.subscribe_direct(self._on_nats_message)
                logger.info("NATS bus connected and subscribed for %s", self.agent_id)
            else:
                self._nats_bus = None
        except Exception:
            logger.warning("Failed to connect NATS bus for %s", self.agent_id, exc_info=True)
            self._nats_bus = None

    async def _start_scheduler(self) -> None:
        settings = self._settings
        if not settings.scheduler_enabled or not settings.redis_url:
            return
        try:
            schedules = {}
            if self.personality.schedules:
                for s in self.personality.schedules:
                    name = s.get("name", "unnamed")
                    schedules[name] = s
            scheduler = AgentScheduler(
                settings.redis_url, self.agent_id,
                channel=self.personality.channel,
                agent_handler=self,
            )
            await scheduler.start(yaml_schedules=schedules)
            scheduler.register_agent_handler(self)
            self._scheduler = scheduler
            self._register_scheduler_handlers()
            logger.info("Scheduler started for %s", self.agent_id)
        except Exception:
            logger.warning("Failed to start scheduler for %s", self.agent_id, exc_info=True)
            self._scheduler = None

    async def start(self) -> None:
        await self._start_council_memory()
        await self._start_private_memory()
        await self._start_nats_bus()
        await self._start_scheduler()

    async def _safe_close(self, resource: Any, name: str) -> None:
        if resource is not None:
            try:
                await resource.close()
            except Exception:
                logger.warning("Error closing %s for %s", name, self.agent_id, exc_info=True)

    async def shutdown(self) -> None:
        await self._safe_close(self._council_memory, "council memory")
        self._council_memory = None
        await self._safe_close(self._private_memory, "private memory")
        self._private_memory = None
        await self._safe_close(self._nats_bus, "NATS bus")
        self._nats_bus = None
        if self._scheduler is not None:
            try:
                await self._scheduler.stop()
            except Exception:
                logger.warning("Error stopping scheduler for %s", self.agent_id, exc_info=True)
            self._scheduler = None
        await self._safe_close(self._store, "store")
        self._store = None
        await self._safe_close(self._cache, "cache")
        self._cache = None

    def set_adapter(self, adapter: Any) -> None:
        self._adapter = adapter

    def _register_scheduler_handlers(self) -> None:
        if self._scheduler is not None:
            self._scheduler.register_handler("heartbeat", self._builtin_heartbeat_handler)
            self._scheduler.register_handler("send_message", self._builtin_send_message_handler)

    async def _builtin_heartbeat_handler(self, **kwargs: Any) -> None:
        if self._nats_bus is None:
            logger.info("heartbeat for %s (no NATS bus)", self.agent_id)
            return
        try:
            await self._nats_bus.publish_broadcast("heartbeat", {"agent_id": self.agent_id})
        except Exception:
            logger.warning("Failed to broadcast heartbeat for %s", self.agent_id, exc_info=True)

    async def _builtin_send_message_handler(self, **kwargs: Any) -> None:
        args = kwargs.get("args", {})
        conversation_key = args.get("conversation_key", "")
        chat_id = args.get("chat_id", conversation_key)
        prompt = args.get("prompt", "Send a brief friendly check-in message.")
        sanitized_prompt = sanitize_or_default(prompt, default="Send a brief friendly check-in message.")

        if not conversation_key:
            logger.warning("send_message action missing conversation_key for %s", self.agent_id)
            return

        if self._adapter is None:
            logger.warning("send_message action but no adapter for %s", self.agent_id)
            return

        try:
            history = self._get_history(conversation_key)

            result = await self._brain.run(
                user_prompt=sanitized_prompt,
                deps=AgentDeps(
                    agent_id=self.agent_id,
                    channel="telegram",
                    channel_user_id="",
                    metadata={},
                    personality=self.personality,
                    private_memory=self._private_memory,
                    skill_registry=self._skill_registry,
                    council_memory=self._council_memory,
                    nats_bus=self._nats_bus,
                    scheduler=self._scheduler,
                    conversation_key=conversation_key,
                    settings=self._settings,
                    embedding_model=self._settings.embedding_model,
                    llm_base_url=self._settings.llm_base_url,
                    llm_api_key=self._settings.llm_api_key,
                    llm_provider=self._settings.llm_provider,
                    embedding_dimension=self._settings.embedding_dimension,
                ),
                message_history=history,
            )
            message_text = self._safe_output(result.output)
            new_history = result.all_messages()
            self._set_history(new_history, conversation_key)
            if self._cache is not None:
                await self._cache.save(
                    self.agent_id, new_history, conversation_key=conversation_key
                )
            if self._store is not None:
                await self._store.save(conversation_key, new_history)

            await self._adapter.send(conversation_key, message_text, {"chat_id": chat_id})
            logger.info("send_message for %s to %s", self.agent_id, conversation_key)
        except Exception:
            logger.exception("send_message failed for %s", self.agent_id)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def skill_registry(self) -> SkillRegistry | None:
        return self._skill_registry

    @property
    def has_council_memory(self) -> bool:
        return self._council_memory is not None

    @property
    def has_nats_bus(self) -> bool:
        return self._nats_bus is not None

    def refresh_skills(self) -> None:
        """Re-register tools when skills change (e.g. after skill_published)."""
        self._brain = self._rebuild_brain()
        logger.info("Refreshed brain tools for %s", self.agent_id)

    # Backwards-compatible alias
    _refresh_brain_tools = refresh_skills

    def switch_model(self, new_model: str) -> None:
        self._model_name = new_model
        self._brain = self._rebuild_brain()
        logger.info("Switched model to %s", new_model)

    def get_history(self, conversation_key: str | None = None) -> list[ModelMessage]:
        return self._conversation_histories.get(conversation_key or "", [])

    def set_history(self, history: list[ModelMessage], conversation_key: str | None = None) -> None:
        self._conversation_histories[conversation_key or ""] = history

    # Backwards-compatible aliases
    _get_history = get_history
    _set_history = set_history

    async def clear_history(self, conversation_key: str | None = None) -> None:
        key = conversation_key or ""
        self._conversation_histories.pop(key, None)
        logger.info("Cleared conversation history for key %s", key or "default")

        # Persist the cleared state so restart doesn't reload stale data
        empty_messages: list[ModelMessage] = []
        self._conversation_histories[key] = empty_messages
        if self._cache is not None:
            await self._cache.save(
                self.agent_id, empty_messages, conversation_key=key
            )
        if self._store is not None and conversation_key is not None:
            await self._store.save(conversation_key, empty_messages)

    def get_status(self) -> dict[str, Any]:
        total_chars = 0
        total_messages = 0
        for history in self._conversation_histories.values():
            total_messages += len(history)
            total_chars += sum(
                len(getattr(p, "content", "")) if hasattr(p, "content") else len(str(p))
                for msg in history
                for p in (msg.parts if hasattr(msg, "parts") else [])
            )
        return {
            "model_name": self._model_name,
            "provider": self._provider,
            "message_count": total_messages,
            "estimated_tokens": round(total_chars / 4),
            "agent_id": self.agent_id,
            "channel": self.personality.channel,
        }

    async def _maybe_summarize_history(
        self, conversation_key: str | None = None
    ) -> str | None:
        """Auto-summarize history if it exceeds the compact threshold.

        Called before each brain.run() to keep context window manageable.
        Returns the summary text if compaction occurred, or None if not needed.
        """
        if not self._compact_summary_enabled:
            return None

        history = self._get_history(conversation_key)
        if len(history) <= self._compact_threshold_messages:
            return None

        logger.info(
            "Auto-summarizing history for %s (%d messages exceeds threshold of %d)",
            self.agent_id,
            len(history),
            self._compact_threshold_messages,
        )

        result = await self.compact_history(conversation_key)
        return result

    async def compact_history(self, conversation_key: str | None = None) -> str:
        history = self._get_history(conversation_key)
        keep_count = self._compact_keep_messages
        total = len(history)

        if total <= keep_count:
            return f"Nothing to compact — only {total} messages."

        old_messages = history[:-keep_count]
        kept_messages = history[-keep_count:]

        summary_prompt = ModelRequest(
            parts=[
                UserPromptPart(
                    content="Summarize this conversation so far in 2-3 concise sentences."
                )
            ]
        )
        deps = AgentDeps(
            agent_id=self.agent_id,
            channel="system",
            channel_user_id="",
            metadata={},
            personality=self.personality,
            private_memory=self._private_memory,
            skill_registry=self._skill_registry,
            council_memory=self._council_memory,
            nats_bus=self._nats_bus,
            scheduler=self._scheduler,
            settings=self._settings,
            embedding_model=self._settings.embedding_model,
            llm_base_url=self._settings.llm_base_url,
            llm_api_key=self._settings.llm_api_key,
            llm_provider=self._settings.llm_provider,
            embedding_dimension=self._settings.embedding_dimension,
        )
        result = await self._brain.run(
            "",
            deps=deps,
            message_history=[summary_prompt, *old_messages],
        )

        summary_text = result.output
        summary_parts = [
            p for p in result.all_messages() if hasattr(p, "kind") and p.kind == "response"
        ]
        if summary_parts:
            summary_response = summary_parts[-1]
        else:
            summary_response = ModelResponse(parts=[TextPart(content=summary_text)])

        truncated_kept = []
        for msg in kept_messages:
            new_parts = []
            for part in msg.parts if hasattr(msg, "parts") else []:
                if hasattr(part, "content") and isinstance(part.content, str):
                    if len(part.content) > self._compact_truncate_message_chars:
                        truncated = (
                            part.content[: self._compact_truncate_message_chars] + "...[truncated]"
                        )
                        new_parts.append(TextPart(content=truncated))
                    else:
                        new_parts.append(part)
                else:
                    new_parts.append(part)
            if hasattr(msg, "kind") and msg.kind == "request":
                truncated_kept.append(ModelRequest(parts=new_parts))
            else:
                truncated_kept.append(ModelResponse(parts=new_parts))

        new_history = [summary_prompt, summary_response, *truncated_kept]
        self._set_history(new_history, conversation_key)
        return f"Compacted {len(old_messages)} messages into summary. Keeping {keep_count} recent."

    def add_alias(self, name: str) -> None:
        """Register an additional name this agent responds to (e.g. Telegram @username)."""
        if name and name.lower() not in self._aliases:
            self._aliases.append(name.lower())

    def is_addressed_to_me(self, content: str) -> bool:
        """Check if the text contains an explicit mention/address of this agent."""
        mentions = {m.group(1).lower() for m in _MENTION_PATTERN.finditer(content)}
        addr_match = _ADDRESS_PATTERN.match(content)
        aliases = set(self._aliases)
        addr_lower = (addr_match.group(1) or addr_match.group(2)).lower() if addr_match else ""
        return bool(mentions & aliases) or addr_lower in aliases

    def should_process_message(
        self,
        message: UnifiedMessage,
        bot_chat_limit: int | None = None,
    ) -> bool:
        """Decide whether this agent should process the given message.

        Returns ``False`` when the message is explicitly addressed to
        another agent by name (e.g. "@wormwood …").  Messages with no
        explicit mention, or with an explicit mention of this agent, are
        processed normally.

        In private (DM) contexts the agent always processes the message — there
        is no other agent in the room.
        """
        is_group = message.metadata.get("is_group", False)
        if not is_group:
            return True

        content = message.content.strip()
        if not content:
            return True

        addressed_to = None
        match = _ADDRESS_PATTERN.match(content)
        if match:
            addressed_to = match.group(1) or match.group(2)
            if addressed_to.lower() not in set(self._aliases):
                logger.info(
                    "Agent %s ignoring message addressed to %s", self.agent_id, addressed_to
                )
                return False

        # bot_chat_limit governs how many consecutive bot messages we join in
        # on when NOT explicitly addressed.  It does NOT apply to DMs or when
        # the user directly addresses us.
        limit = bot_chat_limit
        if limit is None:
            limit = getattr(self.personality, "bot_chat_limit", None)
        if limit is None:
            limit = 3  # sensible default

        convo = message.conversation_key
        is_bot = message.metadata.get("is_bot", False)

        if not is_bot:
            # Human spoke — reset the bot-chatter counter.
            self._seen_mentions_this_limit_cycle[convo] = 0

        if addressed_to is None and isinstance(limit, int) and limit >= 0:
            count = self._seen_mentions_this_limit_cycle.get(convo, 0)
            if is_bot and count >= limit:
                logger.info(
                    "Agent %s ignoring bot message in %s (bot_chat_limit %d reached)",
                    self.agent_id,
                    convo,
                    limit,
                )
                return False
            # We are going to process it; increment counter for bot messages
            # that are not explicitly addressed to us.
            if is_bot and not self.is_addressed_to_me(content):
                self._seen_mentions_this_limit_cycle[convo] = count + 1

        return True

    async def process_message(self, message: UnifiedMessage) -> str:
        if not self.should_process_message(message):
            return ""
        return await self.handle_message(message)

    def _check_rate_limit(self) -> str | None:
        """Token-bucket rate limiter: refills tokens based on elapsed time, then
        consumes 1 token per LLM call. Returns error message if bucket is empty."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        # Refill: add earned tokens, cap at bucket capacity
        self._tokens = min(self._max_tokens, self._tokens + elapsed * self._token_rate)
        self._last_refill = now

        if self._tokens < 1:
            logger.warning(
                "Agent %s token bucket empty (max=%.0f calls/%.0fs)",
                self.agent_id,
                self._max_tokens,
                self._max_tokens / self._token_rate if self._token_rate > 0 else 0,
            )
            return (
                "I'm processing a lot of messages right now. "
                "Please wait a moment and try again."
            )
        self._tokens -= 1
        return None

    async def handle_message(self, message: UnifiedMessage) -> str:
        async with self._lock:
            rate_err = self._check_rate_limit()
            if rate_err:
                return rate_err

            conversation_key = message.conversation_key
            history = self._get_history(conversation_key)
            agent_logger = self._agent_logger

            agent_logger.log_user_message(message.content)

            def _get_conversation_info():
                hist = self._get_history(conversation_key)
                return {
                    "message_count": len(hist),
                    "estimated_tokens": sum(len(str(m)) // 4 for m in hist) if hist else 0,
                }

            deps = AgentDeps(
                agent_id=self.agent_id,
                channel=message.channel.value,
                channel_user_id=message.channel_user_id,
                metadata=message.metadata,
                personality=self.personality,
                private_memory=self._private_memory,
                skill_registry=self._skill_registry,
                council_memory=self._council_memory,
                nats_bus=self._nats_bus,
                scheduler=self._scheduler,
                conversation_key=conversation_key or "",
                conversation_info=_get_conversation_info,
                logger=agent_logger,
                settings=self._settings,
                embedding_model=self._settings.embedding_model,
                llm_base_url=self._settings.llm_base_url,
                llm_api_key=self._settings.llm_api_key,
                llm_provider=self._settings.llm_provider,
                embedding_dimension=self._settings.embedding_dimension,
            )

            total_start = time.perf_counter()

            # Sanitize inbound message content before passing to brain
            sanitizer = PromptSanitizer()
            try:
                sanitized_content = sanitizer.sanitize(message.content)
            except PromptInjectionError as exc:
                logger.warning(
                    "Prompt injection blocked from %s: score=%d, patterns=%s",
                    message.channel_user_id,
                    exc.score,
                    exc.matched_patterns,
                )
                return "I cannot process that request."

            wrapped_content = f"<user_message>\n{sanitized_content}\n</user_message>"

            try:
                await self._maybe_summarize_history(conversation_key)
            except Exception:
                pass

            result = await self._brain.run(
                wrapped_content,
                deps=deps,
                message_history=history,
            )
            total_duration_ms = (time.perf_counter() - total_start) * 1000

            new_history = result.all_messages()
            self._set_history(new_history, conversation_key)

            # Persist history
            persist_start = time.perf_counter()
            if self._cache is not None:
                await self._cache.save(
                    self.agent_id, new_history, conversation_key=conversation_key
                )
            if self._store is not None:
                await self._store.save(conversation_key, new_history)
            persist_duration_ms = (time.perf_counter() - persist_start) * 1000
            if persist_duration_ms > 1:
                agent_logger.log_timing("persist_history", persist_duration_ms)

            agent_logger.log_llm_response(result.output, total_duration_ms)
            return sanitize_output(result.output)
