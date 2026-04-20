import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class AgentConfig:
    id: str
    personality: str
    channel: str
    allowed_user_ids: str = "all"
    environment: dict[str, str] = field(default_factory=dict)


_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _expand_env_vars(value: str) -> str:
    def _replace(match):
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return _ENV_VAR_RE.sub(_replace, value)


def load_agents_config(path: str = "agents.yaml") -> list[AgentConfig]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Agents config file not found: {path}")
    with open(config_path) as f:
        data = yaml.safe_load(f)
    if not data or "agents" not in data:
        raise ValueError(f"Invalid agents config: missing 'agents' key in {path}")
    configs = []
    for entry in data["agents"]:
        agent_id = entry["id"]
        personality = entry["personality"]
        channel = entry["channel"]
        allowed_user_ids = entry.get("allowed_user_ids", "all")
        environment = entry.get("environment", {})
        configs.append(
            AgentConfig(
                id=agent_id,
                personality=personality,
                channel=channel,
                allowed_user_ids=allowed_user_ids,
                environment=environment,
            )
        )
    return configs


def get_agent_config(agent_id: str, path: str = "agents.yaml") -> AgentConfig:
    configs = load_agents_config(path)
    for config in configs:
        if config.id == agent_id:
            return config
    available = [c.id for c in configs]
    raise ValueError(f"Agent '{agent_id}' not found in {path}. Available: {available}")


def apply_agent_env(agent_config: AgentConfig) -> None:
    for key, value in agent_config.environment.items():
        expanded = _expand_env_vars(str(value))
        os.environ[key] = expanded
    if agent_config.allowed_user_ids:
        os.environ["ALLOWED_USER_IDS"] = agent_config.allowed_user_ids
