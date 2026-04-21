import asyncio
import logging
from typing import Any, Optional

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

from pillywiggins.agents.brain import Agent, create_brain
from pillywiggins.agents.deps import AgentDeps
from pillywiggins.agents.personality import Personality
from pillywiggins.memory.cache import ConversationCache
from pillywiggins.memory.council import CouncilMemory
from pillywiggins.memory.private import PrivateMemory
from pillywiggins.memory.store import ConversationStore
from pillywiggins.skills.registry import SkillRegistry
from pillywiggins.messaging.nats_bus import NatsBus
from pillywiggins.messaging.unified import UnifiedMessage
from pillywiggins.scheduling.scheduler import AgentScheduler

logger = logging.getLogger(__name__)


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

    async def start(self) -> None:
        from pillywiggins.config import Settings

        settings = Settings()
        if self._database_url is not None:
            try:
                council = CouncilMemory(self._database_url, self.agent_id)
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
                bus = NatsBus(self._nats_url, self.agent_id)
                await bus.connect()
                self._nats_bus = bus
                logger.info("NATS bus connected for %s", self.agent_id)
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
        async def _heartbeat_handler(**kwargs):
            if self._nats_bus is not None:
                try:
                    await self._nats_bus.publish_broadcast("heartbeat", {"agent_id": self.agent_id})
                except Exception:
                    logger.warning(
                        "Failed to broadcast heartbeat for %s", self.agent_id, exc_info=True
                    )
            else:
                logger.info("heartbeat for %s (no NATS bus)", self.agent_id)

        async def _memory_review_handler(**kwargs):
            logger.info("memory review for %s", self.agent_id)

        async def _skill_reload_handler(**kwargs):
            logger.info("skill reload for %s", self.agent_id)

        async def _send_message_handler(**kwargs):
            args = kwargs.get("args", {})
            conversation_key = args.get("conversation_key", "")
            chat_id = args.get("chat_id", conversation_key)
            prompt = args.get("prompt", "Send a brief friendly check-in message.")

            if not conversation_key:
                logger.warning("send_message action missing conversation_key for %s", self.agent_id)
                return

            if self._adapter is None:
                logger.warning("send_message action but no adapter for %s", self.agent_id)
                return

            try:
                result = await self._brain.run(
                    user_prompt=prompt,
                    deps=AgentDeps(
                        agent_id=self.agent_id,
                        channel="telegram",
                        personality=self.personality,
                        private_memory=self._private_memory,
                        skill_registry=self._skill_registry,
                        council_memory=self._council_memory,
                        nats_bus=self._nats_bus,
                        scheduler=self._scheduler,
                    ),
                )
                message_text = result.output
                await self._adapter.send(conversation_key, message_text, chat_id=chat_id)
                logger.info("send_message for %s to %s", self.agent_id, conversation_key)
            except Exception:
                logger.exception("send_message failed for %s", self.agent_id)

        if self._scheduler is not None:
            self._scheduler.register_handler("heartbeat", _heartbeat_handler)
            self._scheduler.register_handler("memory_review", _memory_review_handler)
            self._scheduler.register_handler("skill_reload", _skill_reload_handler)
            self._scheduler.register_handler("send_message", _send_message_handler)

    @property
    def model_name(self) -> str:
        return self._model_name

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

    async def handle_message(self, message: UnifiedMessage) -> str:
        async with self._lock:
            conversation_key = message.conversation_key
            history = self._get_history(conversation_key)
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
            )
            result = await self._brain.run(
                message.content,
                deps=deps,
                message_history=history,
            )
            new_history = result.all_messages()
            self._set_history(new_history, conversation_key)
            if self._cache is not None:
                await self._cache.save(
                    self.agent_id, new_history, conversation_key=conversation_key
                )
            if self._store is not None:
                await self._store.save(conversation_key, new_history)
            return result.output
