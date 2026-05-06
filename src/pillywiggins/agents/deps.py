from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pillywiggins.config import Settings
    from pillywiggins.logging_utils import AgentLogger
    from pillywiggins.agents.personality import Personality
    from pillywiggins.memory.council import CouncilMemory
    from pillywiggins.memory.private import PrivateMemory
    from pillywiggins.messaging.nats_bus import NatsBus
    from pillywiggins.scheduling.scheduler import AgentScheduler
    from pillywiggins.skills.registry import SkillRegistry


@dataclass
class AgentDeps:
    agent_id: str
    channel: str
    channel_user_id: str = field(default="")
    metadata: dict[str, str] = field(default_factory=dict)
    personality: Personality | None = field(default=None)
    private_memory: PrivateMemory | None = field(default=None)
    skill_registry: SkillRegistry | None = field(default=None)
    council_memory: CouncilMemory | None = field(default=None)
    nats_bus: NatsBus | None = field(default=None)
    scheduler: AgentScheduler | None = field(default=None)
    conversation_key: str = field(default="")
    conversation_info: Callable[[], dict[str, int]] = field(default=lambda: {"message_count": 0, "estimated_tokens": 0})
    logger: AgentLogger | None = field(default=None)
    settings: Settings | None = field(default=None)