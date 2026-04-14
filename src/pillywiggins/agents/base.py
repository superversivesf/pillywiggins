import asyncio
import logging
import os

from pydantic_ai.messages import ModelMessage

from pillywiggins.agents.brain import Agent, create_brain
from pillywiggins.agents.deps import AgentDeps
from pillywiggins.agents.personality import Personality
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
    ):
        self.agent_id = agent_id
        self.personality = personality
        self._model_name = model_name
        self._provider = provider
        self._base_url = base_url
        self._api_key = api_key
        self._lock = asyncio.Lock()
        self._brain: Agent = create_brain(
            personality.system_prompt, model_name, provider, base_url, api_key,
        )
        self._message_history: list[ModelMessage] = []

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

    async def handle_message(self, message: UnifiedMessage) -> str:
        async with self._lock:
            deps = AgentDeps(
                agent_id=self.agent_id,
                channel=message.channel.value,
            )
            result = await self._brain.run(
                message.content,
                deps=deps,
                message_history=self._message_history,
            )
            self._message_history = result.all_messages()
            return result.output