from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pillywiggins.memory.private import PrivateMemory
    from pillywiggins.skills.registry import SkillRegistry


@dataclass
class AgentDeps:
    agent_id: str
    channel: str
    private_memory: Any = field(default=None)
    skill_registry: Any = field(default=None)
    council_memory: Any = field(default=None)
    nats_bus: Any = field(default=None)
    scheduler: Any = field(default=None)