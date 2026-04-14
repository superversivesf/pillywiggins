from dataclasses import dataclass


@dataclass
class AgentDeps:
    agent_id: str
    channel: str