import asyncio
import logging
from typing import Optional

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
        self._lock = asyncio.Lock()
        self._brain: Agent = create_brain(
            personality.system_prompt, model_name, provider, base_url, api_key,
            skill_registry=skill_registry,
        )
        self._message_history: list[ModelMessage] = []

    async def load_history(self, conversation_key: Optional[str] = None) -> None:
        if self._cache is not None:
            cached = await self._cache.load(self.agent_id)
            if cached is not None:
                self._message_history = cached
                logger.info("Loaded %d messages from Redis for %s", len(cached), self.agent_id)
                return
        if self._store is not None and conversation_key is not None:
            stored = await self._store.load(conversation_key)
            if stored is not None:
                self._message_history = stored
                logger.info("Loaded %d messages from PostgreSQL for %s/%s", len(stored), self.agent_id, conversation_key)

    async def start(self) -> None:
        if self._database_url is not None:
            try:
                council = CouncilMemory(self._database_url, self.agent_id)
                await council.connect()
                self._council_memory = council
                logger.info("Council memory connected for %s", self.agent_id)
            except Exception:
                logger.warning("Failed to connect council memory for %s", self.agent_id, exc_info=True)
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

    @property
    def model_name(self) -> str:
        return self._model_name

    def switch_model(self, new_model: str) -> None:
        self._model_name = new_model
        self._brain = create_brain(
            self.personality.system_prompt, new_model, self._provider, self._base_url, self._api_key,
        )
        logger.info("Switched model to %s", new_model)

    def clear_history(self) -> None:
        self._message_history = []
        logger.info("Cleared conversation history")

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

    async def compact_history(self) -> str:
        keep_count = self._compact_keep_messages
        total = len(self._message_history)

        if total <= keep_count:
            return f"Nothing to compact — only {total} messages."

        old_messages = self._message_history[:-keep_count]
        kept_messages = self._message_history[-keep_count:]

        summary_prompt = ModelRequest(
            parts=[UserPromptPart(content="Summarize this conversation so far in 2-3 concise sentences.")]
        )
        deps = AgentDeps(
            agent_id=self.agent_id,
            channel="system",
            private_memory=self._private_memory,
            skill_registry=self._skill_registry,
            council_memory=self._council_memory,
            nats_bus=self._nats_bus,
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
            for part in (msg.parts if hasattr(msg, "parts") else []):
                if hasattr(part, "content") and isinstance(part.content, str):
                    if len(part.content) > self._compact_truncate_message_chars:
                        truncated = part.content[:self._compact_truncate_message_chars] + "...[truncated]"
                        new_parts.append(TextPart(content=truncated))
                    else:
                        new_parts.append(part)
                else:
                    new_parts.append(part)
            if hasattr(msg, "kind") and msg.kind == "request":
                truncated_kept.append(ModelRequest(parts=new_parts))
            else:
                truncated_kept.append(ModelResponse(parts=new_parts))

        self._message_history = [summary_prompt, summary_response, *truncated_kept]
        return f"Compacted {len(old_messages)} messages into summary. Keeping {keep_count} recent."

    async def handle_message(self, message: UnifiedMessage) -> str:
        async with self._lock:
            deps = AgentDeps(
                agent_id=self.agent_id,
                channel=message.channel.value,
                private_memory=self._private_memory,
                skill_registry=self._skill_registry,
                council_memory=self._council_memory,
                nats_bus=self._nats_bus,
            )
            result = await self._brain.run(
                message.content,
                deps=deps,
                message_history=self._message_history,
            )
            self._message_history = result.all_messages()
            if self._cache is not None:
                await self._cache.save(self.agent_id, self._message_history)
            if self._store is not None:
                await self._store.save(message.conversation_key, self._message_history)
            return result.output