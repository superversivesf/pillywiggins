from dataclasses import dataclass, field

import yaml


@dataclass
class Personality:
    name: str
    channel: str
    description: str = ""
    system_prompt: str = ""
    traits: list[str] = field(default_factory=list)
    scheduling: dict = field(default_factory=dict)
    schedules: list[dict] = field(default_factory=list)
    bot_chat_limit: int = 3
    timezone: str = "UTC"
    # New schema fields for forward compatibility
    archetype: str = ""
    tone: str = ""
    style: str = ""
    response_length: str = ""
    additional_instructions: str = ""

    def build_system_prompt(self) -> str:
        """Assemble a system prompt from whichever schema fields are present."""
        parts = [f"You are {self.name}."]
        if self.description:
            parts.append(self.description)
        if self.traits:
            parts.append(f"Your personality traits: {', '.join(self.traits)}.")
        if self.system_prompt:
            parts.append(self.system_prompt)
        elif self.archetype:
            if self.archetype:
                parts.append(f"Archetype: {self.archetype}.")
            if self.tone:
                parts.append(f"Tone: {self.tone}.")
            if self.style:
                parts.append(f"Style: {self.style}.")
            if self.response_length:
                parts.append(f"Response length: {self.response_length}.")
            if self.additional_instructions:
                parts.append(self.additional_instructions)
        return "\n\n".join(parts)


def load_personality(path: str) -> Personality:
    with open(path) as f:
        data = yaml.safe_load(f)
    if not data:
        raise TypeError(f"Personality file {path} is empty or invalid")
    limit = data.get("bot_chat_limit", 3)
    if isinstance(limit, str) and limit.strip().lower() == "unlimited":
        limit = -1

    # Support both old schema (description/system_prompt/traits) and new schema
    # (archetype/tone/style/response_length).
    description = data.get("description", "")
    system_prompt = data.get("system_prompt", "")
    archetype = data.get("archetype", "")
    tone = data.get("tone", "")
    style = data.get("style", "")
    response_length = data.get("response_length", "")
    additional_instructions = data.get("additional_instructions", "")

    # Derive missing old-schema fields from new-schema fields when present.
    if not description and archetype:
        description = archetype

    if not system_prompt and (
        archetype or tone or style or response_length or additional_instructions
    ):
        parts = [f"You are {data['name']}, a {archetype}."]
        if tone:
            parts.append(f"Tone: {tone}.")
        if style:
            parts.append(f"Style: {style}.")
        if response_length:
            parts.append(f"Response length: {response_length}.")
        if additional_instructions:
            parts.append(additional_instructions)
        system_prompt = "\n".join(parts)

    return Personality(
        name=data["name"],
        channel=data["channel"],
        description=description,
        system_prompt=system_prompt,
        traits=data.get("traits", []),
        scheduling=data.get("scheduling", {}),
        schedules=data.get("schedules", []),
        bot_chat_limit=int(limit),
        timezone=data.get("timezone", "UTC"),
        archetype=archetype,
        tone=tone,
        style=style,
        response_length=response_length,
        additional_instructions=additional_instructions,
    )
