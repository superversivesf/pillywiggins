from dataclasses import dataclass, field

import yaml


@dataclass
class Personality:
    name: str
    channel: str
    description: str
    system_prompt: str
    traits: list[str] = field(default_factory=list)
    scheduling: dict = field(default_factory=dict)
    schedules: list[dict] = field(default_factory=list)
    bot_chat_limit: int = 3


def load_personality(path: str) -> Personality:
    with open(path) as f:
        data = yaml.safe_load(f)
    if not data:
        raise TypeError(f"Personality file {path} is empty or invalid")
    limit = data.get("bot_chat_limit", 3)
    if isinstance(limit, str) and limit.strip().lower() == "unlimited":
        limit = -1
    return Personality(
        name=data["name"],
        channel=data["channel"],
        description=data["description"],
        system_prompt=data["system_prompt"],
        traits=data.get("traits", []),
        scheduling=data.get("scheduling", {}),
        schedules=data.get("schedules", []),
        bot_chat_limit=int(limit),
    )