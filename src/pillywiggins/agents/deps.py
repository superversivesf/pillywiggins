from dataclasses import dataclass, field


@dataclass
class AgentDeps:
    agent_id: str
    channel: str
    conversation_history: list = field(default_factory=list)