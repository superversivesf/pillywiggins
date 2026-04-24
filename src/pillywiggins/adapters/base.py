from abc import ABC, abstractmethod

from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.messaging.unified import UnifiedMessage


class BaseAdapter(ABC):
    def __init__(self, agent: PillywigginAgent):
        self.agent = agent

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def listen(self) -> None: ...

    @abstractmethod
    async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None: ...

    @abstractmethod
    def normalize(self, raw_message: dict) -> UnifiedMessage: ...
