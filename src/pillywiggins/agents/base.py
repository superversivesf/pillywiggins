import asyncio
import logging
import re
import time
from typing import Any, Optional

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from pillywiggins.agents.brain import Agent, create_brain
from pillywiggins.agents.deps import AgentDeps
from pillywiggins.agents.personality import Personality
from pillywiggins.logging_utils import AgentLogger
from pillywiggins.memory.cache import ConversationCache
from pillywiggins.memory.council import CouncilMemory
from pillywiggins.memory.private import PrivateMemory
from pillywiggins.memory.store import ConversationStore
from pillywiggins.skills.registry import SkillRegistry
from pillywiggins.messaging.nats_bus import NatsBus
from pillywiggins.messaging.unified import UnifiedMessage, ChannelType
from pillywiggins.scheduling.scheduler import AgentScheduler

logger = logging.getLogger(__name__)

_ACTIVE_AGENTS: dict[str, "PillywigginAgent"] = {}

# Matches an explicit agent address at the start of a message:
#   @name      (mention/tag)
#   name:     (name followed by colon)
#   name,     (name followed by comma)
_ADDRESS_PATTERN = re.compile(
    r"^(?:@([a-zA-Z0-9_\-]+)|([a-zA-Z0-9_\-]+)[,:])",
    re.UNICODE,
)


async def _builtin_heartbeat_handler(**kwargs: Any) -> None:
    agent_id = kwargs.get("agent_id", "")
    agent = _ACTIVE_AGENTS.get(agent_id)
    if agent is None or agent._nats_bus is None:
        logger.info("heartbeat for %s (no NATS bus)", agent_id)
        return
    try:
        await agent._nats_bus.publish_broadcast("heartbeat", {"agent_id": agent_id})
    except Exception:
        logger.warning("Failed to broadcast heartbeat for %s", agent_id, exc_info=True)


async def _builtin_send_message_handler(**kwargs: Any) -> None:
    agent_id = kwargs.get("agent_id", "")
    args = kwargs.get("args", {})
    agent = _ACTIVE_AGENTS.get(agent_id)
    if agent is None:
        logger.warning("send_message: agent %s not found", agent_id)
        return
    conversation_key = args.get("conversation_key", "")
    chat_id = args.get("chat_id", conversation_key)
    prompt = args.get("prompt", "Send a brief friendly check-in message.")

    if not conversation_key:
        logger.warning("send_message action missing conversation_key for %s", agent_id)
        return

    if agent._adapter is None:
        logger.warning("send_message action but no adapter for %s", agent_id)
        return

    try:
        result = await agent._brain.run(
            user_prompt=prompt,
            deps=AgentDeps(
                agent_id=agent.agent_id,
                channel="telegram",
                personality=agent.personality,
                private_memory=agent._private_memory,
                skill_registry=agent._skill_registry,
                council_memory=agent._council_memory,
                nats_bus=agent._nats_bus,
                scheduler=agent._scheduler,
                conversation_key=conversation_key,
            ),
        )
        message_text = result.output
        await agent._adapter.send(conversation_key, message_text, {"chat_id": chat_id})
        logger.info("send_message for %s to %s", agent_id, conversation_key)
    except Exception:
        logger.exception("send_message failed for %s", agent_id)


class PillywigginAgent:
    def __init__(
        self,
        agent_id: str,
        personality: Personality,
        model_name: str,
        provider: str,
        base_url: str,
        api_key: str,
        cache: Optional[ConversationCache] = None,
        store: Optional[ConversationStore] = None,
        private_memory: Optional[PrivateMemory] = None,
        skill_registry: Optional[SkillRegistry] = None,
        compact_keep_messages: int = 6,
        compact_truncate_message_chars: int = 2000,
        database_url: Optional[str] = None,
        nats_url: Optional[str] = None,
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
        self._database_url = database_url
        self._nats_url = nats_url
        self._council_memory: Optional[CouncilMemory] = None
        self._nats_bus: Optional[NatsBus] = None
        self._scheduler: Optional[AgentScheduler] = None
        self._adapter: Any = None
        self._lock = asyncio.Lock()
        self._agent_logger = AgentLogger(agent_id)
        # Rate limiting: max 10 LLM calls per minute per agent
        self._llm_call_timestamps: list[float] = []
        self._llm_rate_limit = 10  # calls
        self._llm_rate_window = 60.0  # seconds
        self._brain: Agent = create_brain(
            model_name,
            provider,
            base_url,
            api_key,
            skill_registry=skill_registry,
        )
        self._message_history: list[ModelMessage] = []
        self._conversation_histories: dict[str, list[ModelMessage]] = {}

    async def load_history(self, conversation_key: Optional[str] = None) -> None:
        if self._cache is not None:
            cache_key = conversation_key or ""
            cached = await self._cache.load(self.agent_id, conversation_key=cache_key)
            if cached is not None:
                if conversation_key:
                    self._conversation_histories[conversation_key] = cached
                else:
                    self._message_history = cached
                logger.info(
                    "Loaded %d messages from Redis for %s/%s",
                    len(cached),
                    self.agent_id,
                    conversation_key or "default",
                )
                return
        if self._store is not None and conversation_key is not None:
            stored = await self._store.load(conversation_key)
            if stored is not None:
                self._message_history = stored
                logger.info(
                    "Loaded %d messages from PostgreSQL for %s/%s",
                    len(stored),
                    self.agent_id,
                    conversation_key,
                )

    async def _on_nats_message(self, msg_type: str, data: dict) -> None:
        logger.info("Agent %s handling NATS message type=%s from=%s", self.agent_id, msg_type, data.get("from", "?"))
        if msg_type == "message":
            try:
                channel = ChannelType(data.get("channel", "telegram"))
            except ValueError:
                channel = ChannelType.TELEGRAM
            msg = UnifiedMessage(
                channel=channel,
                channel_user_id=data.get("channel_user_id", ""),
                content=data.get("content", ""),
                conversation_key=data.get("conversation_key", ""),
                metadata=data.get("metadata", {}),
            )
            logger.info("Agent %s processing inbound direct message from %s", self.agent_id, data.get("from", "?"))
            response = await self.process_message(msg)
            if response and self._nats_bus is not None:
                sender = data.get("from")
                if sender:
                    await self._nats_bus.publish_direct(
                        target_agent_id=sender,
                        message_type="direct_reply",
                        data={"reply": response},
                    )
        elif msg_type == "insight":
            if self._council_memory is not None:
                await self._council_memory.write_entry(
                    content=data.get("content", ""),
                    tags=data.get("tags", []),
                    embedding=data.get("embedding", []),
                    message_type="insight",
                    confidence=1.0,
                )
        elif msg_type == "skill_published":
            if self._skill_registry is not None:
                self._skill_registry.load_all()
                self._refresh_brain_tools()
        else:
            logger.warning("Agent %s unknown NATS message type: %s", self.agent_id, msg_type)

    async def start(self) -> None:
        from pillywiggins.config import Settings

        _ACTIVE_AGENTS[self.agent_id] = self
        settings = Settings()
        if self._database_url is not None:
            try:
                council = CouncilMemory(self._database_url, self.agent_id, embedding_dimension=settings.embedding_dimension)
                await council.connect()
                self._council_memory = council
                logger.info("Council memory connected for %s", self.agent_id)
            except Exception:
                logger.warning(
                    "Failed to connect council memory for %s", self.agent_id, exc_info=True
                )
                self._council_memory = None
        if self._nats_url is not None:
            try:
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
        if settings.scheduler_enabled and settings.redis_url:
            try:
                schedules = {}
                if self.personality.schedules:
                    for s in self.personality.schedules:
                        name = s.get("name", "unnamed")
                        schedules[name] = s
                scheduler = AgentScheduler(settings.redis_url, self.agent_id)
                await scheduler.start(yaml_schedules=schedules)
                self._scheduler = scheduler
                self._register_scheduler_handlers()
                logger.info("Scheduler started for %s", self.agent_id)
            except Exception:
                logger.warning("Failed to start scheduler for %s", self.agent_id, exc_info=True)
                self._scheduler = None

    async def shutdown(self) -> None:
        _ACTIVE_AGENTS.pop(self.agent_id, None)
        if self._council_memory is not None:
            try:
                await self._council_memory.close()
            except Exception:
                logger.warning("Error closing council memory for %s", self.agent_id, exc_info=True)
            self._council_memory = None
        if self._nats_bus is not None:
            try:
                await self._nats_bus.close()
            except Exception:
                logger.warning("Error closing NATS bus for %s", self.agent_id, exc_info=True)
            self._nats_bus = None
        if self._scheduler is not None:
            try:
                await self._scheduler.stop()
            except Exception:
                logger.warning("Error stopping scheduler for %s", self.agent_id, exc_info=True)
            self._scheduler = None

    def set_adapter(self, adapter: Any) -> None:
        self._adapter = adapter

    def _register_scheduler_handlers(self) -> None:
        if self._scheduler is not None:
            self._scheduler.register_handler("heartbeat", _builtin_heartbeat_handler)
            self._scheduler.register_handler("send_message", _builtin_send_message_handler)

    @property
    def model_name(self) -> str:
        return self._model_name

    def _refresh_brain_tools(self) -> None:
        """Re-register tools when skills change (e.g. after skill_published)."""
        self._brain = create_brain(
            self._model_name,
            self._provider,
            self._base_url,
            self._api_key,
            skill_registry=self._skill_registry,
        )
        logger.info("Refreshed brain tools for %s", self.agent_id)

    def switch_model(self, new_model: str) -> None:
        self._model_name = new_model
        self._brain = create_brain(
            new_model,
            self._provider,
            self._base_url,
            self._api_key,
            skill_registry=self._skill_registry,
        )
        logger.info("Switched model to %s", new_model)

    def _get_history(self, conversation_key: str | None = None) -> list:
        if conversation_key and conversation_key in self._conversation_histories:
            return self._conversation_histories[conversation_key]
        return self._message_history

    def _set_history(self, history: list, conversation_key: str | None = None) -> None:
        if conversation_key:
            self._conversation_histories[conversation_key] = history
        else:
            self._message_history = history

    async def clear_history(self, conversation_key: str | None = None) -> None:
        if conversation_key and conversation_key in self._conversation_histories:
            del self._conversation_histories[conversation_key]
            logger.info("Cleared conversation history for key %s", conversation_key)
        else:
            self._message_history = []
            logger.info("Cleared conversation history")

        # Persist the cleared state so restart doesn't reload stale data
        empty_messages: list[ModelMessage] = []
        if conversation_key:
            self._conversation_histories[conversation_key] = empty_messages
        if self._cache is not None:
            await self._cache.save(
                self.agent_id, empty_messages, conversation_key=conversation_key or ""
            )
        if self._store is not None and conversation_key is not None:
            await self._store.save(conversation_key, empty_messages)

    def get_status(self) -> dict:
        total_chars = sum(
            len(getattr(p, "content", "")) if hasattr(p, "content") else len(str(p))
            for msg in self._message_history
            for p in (msg.parts if hasattr(msg, "parts") else [])
        )
        return {
            "model_name": self._model_name,
            "message_count": len(self._message_history),
            "estimated_tokens": round(total_chars / 4),
            "agent_id": self.agent_id,
            "channel": self.personality.channel,
        }

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
            personality=self.personality,
            private_memory=self._private_memory,
            skill_registry=self._skill_registry,
            council_memory=self._council_memory,
            nats_bus=self._nats_bus,
            scheduler=self._scheduler,
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

    def should_process_message(self, message: UnifiedMessage) -> bool:
        """Decide whether this agent should process the given message.

        Returns ``False`` only when the message is explicitly addressed to
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

        match = _ADDRESS_PATTERN.match(content)
        if match:
            addressed_to = match.group(1) or match.group(2)
            # Case-insensitive comparison so "Wormwood" == "wormwood"
            if addressed_to.lower() != self.agent_id.lower():
                logger.info(
                    "Agent %s ignoring message addressed to %s", self.agent_id, addressed_to
                )
                return False

        return True

    async def process_message(self, message: UnifiedMessage) -> str:
        if not self.should_process_message(message):
            return ""
        return await self.handle_message(message)

    def _check_rate_limit(self) -> str | None:
        """Check if agent has exceeded LLM call rate limit. Returns error message if limited."""
        now = time.monotonic()
        cutoff = now - self._llm_rate_window
        self._llm_call_timestamps = [ts for ts in self._llm_call_timestamps if ts > cutoff]
        if len(self._llm_call_timestamps) >= self._llm_rate_limit:
            logger.warning(
                "Agent %s rate limit hit (%d calls in %ds)",
                self.agent_id,
                self._llm_rate_limit,
                int(self._llm_rate_window),
            )
            return (
                "I'm processing a lot of messages right now. "
                "Please wait a moment and try again."
            )
        self._llm_call_timestamps.append(now)
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
                personality=self.personality,
                private_memory=self._private_memory,
                skill_registry=self._skill_registry,
                council_memory=self._council_memory,
                nats_bus=self._nats_bus,
                scheduler=self._scheduler,
                conversation_key=conversation_key or "",
                conversation_info=_get_conversation_info,
                logger=agent_logger,
            )

            total_start = time.perf_counter()
            result = await self._brain.run(
                message.content,
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
            return result.output
