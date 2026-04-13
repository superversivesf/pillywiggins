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


def load_personality(path: str) -> Personality:
    with open(path) as f:
        data = yaml.safe_load(f)
    return Personality(
        name=data["name"],
        channel=data["channel"],
        description=data["description"],
        system_prompt=data["system_prompt"],
        traits=data.get("traits", []),
        scheduling=data.get("scheduling", {}),
    )