from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AgentDeps:
    agent_id: str
    channel: str
    private_memory: Any = field(default=None)