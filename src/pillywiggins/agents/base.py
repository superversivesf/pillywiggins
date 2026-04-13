import asyncio
import logging

from pillywiggins.agents.brain import Agent, create_brain
from pillywiggins.agents.deps import AgentDeps
from pillywiggins.agents.personality import Personality
from pillywiggins.messaging.unified import UnifiedMessage

logger = logging.getLogger(__name__)


class PillywigginAgent:
    def __init__(self, agent_id: str, personality: Personality, model_name: str):
        self.agent_id = agent_id
        self.personality = personality
        self._lock = asyncio.Lock()
        self._brain: Agent = create_brain(personality.system_prompt, model_name)
        self._conversation_history: list = []

    async def handle_message(self, message: UnifiedMessage) -> str:
        async with self._lock:
            deps = AgentDeps(
                agent_id=self.agent_id,
                channel=message.channel.value,
                conversation_history=self._conversation_history,
            )
            result = await self._brain.run(message.content, deps=deps)
            self._conversation_history.append({"role": "user", "content": message.content})
            self._conversation_history.append({"role": "assistant", "content": result.data})
            return result.data