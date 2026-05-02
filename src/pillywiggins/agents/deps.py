from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pillywiggins.memory.private import PrivateMemory
    from pillywiggins.skills.registry import SkillRegistry


@dataclass
class AgentDeps:
    agent_id: str
    channel: str
    personality: Any = field(default=None)
    private_memory: Any = field(default=None)
    skill_registry: Any = field(default=None)
    council_memory: Any = field(default=None)
    nats_bus: Any = field(default=None)
    scheduler: Any = field(default=None)
    conversation_key: str = field(default="")
    conversation_info: Callable = field(default=lambda: {"message_count": 0, "estimated_tokens": 0})
    logger: Any = field(default=None)
