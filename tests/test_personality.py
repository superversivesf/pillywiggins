from pathlib import Path

import pytest
import yaml

from pillywiggins.agents.personality import Personality, load_personality

PERSONALITIES_DIR = Path(__file__).resolve().parent.parent / "personalities"


def _all_personality_yamls():
    if not PERSONALITIES_DIR.exists():
        return []
    return sorted(p for p in PERSONALITIES_DIR.glob("*.yaml"))


def test_personality_dataclass_fields():
    p = Personality(
        name="puck",
        channel="telegram",
        description="A mischievous fairy",
        system_prompt="You are Puck.",
    )
    assert p.name == "puck"
    assert p.channel == "telegram"
    assert p.description == "A mischievous fairy"
    assert p.system_prompt == "You are Puck."
    assert p.traits == []
    assert p.schedules == []


def test_personality_dataclass_with_all_fields():
    p = Personality(
        name="oberon",
        channel="discord",
        description="King of the fairies",
        system_prompt="You are Oberon, king of fairies.",
        traits=["regal", "wise", "jealous"],
    )
    assert p.name == "oberon"
    assert p.channel == "discord"
    assert p.traits == ["regal", "wise", "jealous"]


def test_load_personality_from_yaml(tmp_path):
    data = {
        "name": "puck",
        "channel": "telegram",
        "description": "A mischievous fairy",
        "system_prompt": "You are Puck, a mischievous fairy.",
        "traits": ["playful", "trickster"],
    }
    path = tmp_path / "personality.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    assert p.name == "puck"
    assert p.channel == "telegram"
    assert p.description == "A mischievous fairy"
    assert p.system_prompt == "You are Puck, a mischievous fairy."
    assert p.traits == ["playful", "trickster"]


def test_load_personality_missing_optional_fields(tmp_path):
    data = {
        "name": "titania",
        "channel": "slack",
        "description": "Queen of the fairies",
        "system_prompt": "You are Titania.",
    }
    path = tmp_path / "minimal.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    assert p.name == "titania"
    assert p.channel == "slack"
    assert p.traits == []
    assert p.schedules == []


def test_load_personality_empty_traits(tmp_path):
    data = {
        "name": "cobweb",
        "channel": "matrix",
        "description": "A fairy attendant",
        "system_prompt": "You are Cobweb.",
        "traits": [],
    }
    path = tmp_path / "empty_opts.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    assert p.traits == []
    assert p.schedules == []


def test_load_personality_file_not_found():
    import pytest

    with pytest.raises(FileNotFoundError):
        load_personality("/nonexistent/path/personality.yaml")


def test_load_personality_missing_required_field(tmp_path):
    data = {"name": "puck"}
    path = tmp_path / "incomplete.yaml"
    path.write_text(yaml.dump(data))
    import pytest

    with pytest.raises(KeyError):
        load_personality(str(path))


def test_load_personality_none_yaml(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("")
    import pytest

    with pytest.raises(TypeError):
        load_personality(str(path))


def test_personality_dataclass_equality():
    p1 = Personality(name="puck", channel="telegram", description="A fairy", system_prompt="Hi")
    p2 = Personality(name="puck", channel="telegram", description="A fairy", system_prompt="Hi")
    assert p1 == p2


def test_personality_traits_mutation_isolation():
    p = Personality(name="puck", channel="telegram", description="desc", system_prompt="sp")
    p.traits.append("playful")
    p2 = Personality(name="puck", channel="telegram", description="desc", system_prompt="sp")
    assert p2.traits == []


@pytest.mark.parametrize("yaml_path", _all_personality_yamls(), ids=lambda p: p.stem)
def test_personality_yaml_loadable(yaml_path):
    p = load_personality(str(yaml_path))
    assert isinstance(p, Personality)


@pytest.mark.parametrize("yaml_path", _all_personality_yamls(), ids=lambda p: p.stem)
def test_personality_yaml_has_name(yaml_path):
    p = load_personality(str(yaml_path))
    assert isinstance(p.name, str)
    assert len(p.name) > 0


@pytest.mark.parametrize("yaml_path", _all_personality_yamls(), ids=lambda p: p.stem)
def test_personality_yaml_has_system_prompt(yaml_path):
    p = load_personality(str(yaml_path))
    assert isinstance(p.system_prompt, str)
    assert len(p.system_prompt) > 0


@pytest.mark.parametrize("yaml_path", _all_personality_yamls(), ids=lambda p: p.stem)
def test_personality_yaml_has_channel(yaml_path):
    p = load_personality(str(yaml_path))
    assert isinstance(p.channel, str)
    assert len(p.channel) > 0


@pytest.mark.parametrize("yaml_path", _all_personality_yamls(), ids=lambda p: p.stem)
def test_personality_yaml_has_description(yaml_path):
    p = load_personality(str(yaml_path))
    assert isinstance(p.description, str)
    assert len(p.description) > 0


def test_personality_timezone_default():
    p = Personality(
        name="testbot",
        channel="telegram",
        description="A test bot",
        system_prompt="You are a test bot.",
    )
    assert p.timezone == "UTC"


def test_personality_timezone_custom():
    p = Personality(
        name="puck",
        channel="telegram",
        description="A fairy",
        system_prompt="You are Puck.",
        timezone="America/Los_Angeles",
    )
    assert p.timezone == "America/Los_Angeles"


def test_load_personality_with_timezone(tmp_path):
    data = {
        "name": "puck",
        "channel": "telegram",
        "description": "A fairy",
        "system_prompt": "You are Puck.",
        "timezone": "America/Los_Angeles",
    }
    path = tmp_path / "tz_personality.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    assert p.timezone == "America/Los_Angeles"


def test_load_personality_timezone_defaults_to_utc(tmp_path):
    data = {
        "name": "acorn",
        "channel": "telegram",
        "description": "A squirrel",
        "system_prompt": "You are Acorn.",
    }
    path = tmp_path / "no_tz.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    assert p.timezone == "UTC"


@pytest.mark.parametrize("yaml_path", _all_personality_yamls(), ids=lambda p: p.stem)
def test_personality_yaml_has_timezone(yaml_path):
    p = load_personality(str(yaml_path))
    assert isinstance(p.timezone, str)
    assert len(p.timezone) > 0


def test_load_personality_puck_has_los_angeles_timezone():
    puck_path = PERSONALITIES_DIR / "puck.yaml"
    if puck_path.exists():
        p = load_personality(str(puck_path))
        assert p.timezone == "America/Los_Angeles"


# ---- New schema support (archetype / tone / style / response_length) ----


def test_load_personality_new_schema(tmp_path):
    data = {
        "name": "Puck",
        "channel": "discord",
        "archetype": "Mischievous fairy trickster",
        "tone": "playful, witty, slightly chaotic",
        "style": "uses emojis freely, loves puns",
        "response_length": "concise, 1-3 sentences unless asked for more",
    }
    path = tmp_path / "new_schema.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    assert p.name == "Puck"
    assert p.channel == "discord"
    assert p.archetype == "Mischievous fairy trickster"
    assert p.tone == "playful, witty, slightly chaotic"
    assert p.style == "uses emojis freely, loves puns"
    assert p.response_length == "concise, 1-3 sentences unless asked for more"


def test_load_personality_new_schema_missing_channel_raises(tmp_path):
    data = {
        "name": "Puck",
        "archetype": "Mischievous fairy trickster",
        "tone": "playful",
        "style": "snarky",
    }
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.dump(data))
    with pytest.raises(KeyError):
        load_personality(str(path))


def test_load_personality_new_schema_defaults(tmp_path):
    data = {
        "name": "Puck",
        "channel": "discord",
        "archetype": "Trickster",
        "tone": "playful",
        "style": "snarky",
        "response_length": "short",
    }
    path = tmp_path / "defaults.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    assert p.traits == []
    assert p.schedules == []
    assert p.bot_chat_limit == 3
    assert p.timezone == "UTC"


def test_new_schema_generates_system_prompt(tmp_path):
    data = {
        "name": "Puck",
        "channel": "discord",
        "archetype": "Mischievous fairy trickster",
        "tone": "playful, witty, slightly chaotic",
        "style": "uses emojis freely, loves puns, references internet culture",
        "response_length": "concise, 1-3 sentences unless asked for more",
    }
    path = tmp_path / "new_schema.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    prompt = p.build_system_prompt()
    assert "Puck" in prompt
    assert "Mischievous fairy trickster" in prompt
    assert "playful, witty, slightly chaotic" in prompt
    assert "uses emojis freely, loves puns, references internet culture" in prompt
    assert "concise, 1-3 sentences unless asked for more" in prompt


def test_old_schema_still_works(tmp_path):
    data = {
        "name": "Acorn",
        "channel": "telegram",
        "description": "A patient and visionary fae.",
        "system_prompt": "You are Acorn.",
        "traits": ["patient", "wise"],
    }
    path = tmp_path / "old_schema.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    assert p.name == "Acorn"
    assert p.description == "A patient and visionary fae."
    assert p.system_prompt == "You are Acorn."
    assert p.traits == ["patient", "wise"]


def test_old_schema_system_prompt_roundtrip(tmp_path):
    data = {
        "name": "Acorn",
        "channel": "telegram",
        "description": "A patient and visionary fae.",
        "system_prompt": "You are Acorn.",
    }
    path = tmp_path / "old_schema.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    prompt = p.build_system_prompt()
    assert "You are Acorn." in prompt
    assert "A patient and visionary fae." in prompt


def test_mixed_old_and_new_prefers_new_system_prompt_field(tmp_path):
    data = {
        "name": "Puck",
        "channel": "discord",
        "archetype": "Trickster",
        "tone": "playful",
        "style": "snarky",
        "response_length": "short",
        "system_prompt": "You are Puck.",
    }
    path = tmp_path / "mixed.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    # system_prompt explicitly provided still takes priority
    assert p.system_prompt == "You are Puck."
    assert p.archetype == "Trickster"


def test_backward_compat_existing_personalities_load():
    """All existing personalities/ YAMLs must still be loadable."""
    if not PERSONALITIES_DIR.exists():
        pytest.skip("No personalities directory found")
    for yaml_path in PERSONALITIES_DIR.glob("*.yaml"):
        p = load_personality(str(yaml_path))
        assert isinstance(p, Personality)
        assert p.system_prompt  # should be non-empty


def test_discord_personality_yaml_loads():
    """personalities/discord.yaml must load with new schema fields."""
    path = PERSONALITIES_DIR / "discord.yaml"
    if not path.exists():
        pytest.skip("discord.yaml not found")
    p = load_personality(str(path))
    assert p.name == "Robin"
    assert p.channel == "discord"
    assert p.archetype == "Mischievous fairy trickster"
    assert p.tone == "playful, witty, slightly chaotic"
    assert p.style == "uses emojis freely, loves puns, references internet culture"
    assert p.response_length == "concise, 1-3 sentences unless asked for more"
    assert p.timezone == "America/Los_Angeles"
    assert p.bot_chat_limit == 3
    assert len(p.schedules) == 3
    assert p.system_prompt
    prompt = p.build_system_prompt()
    assert "Robin" in prompt
    assert "Mischievous fairy trickster" in prompt
    assert "playful, witty, slightly chaotic" in prompt
    assert "uses emojis freely, loves puns, references internet culture" in prompt
    assert "concise, 1-3 sentences unless asked for more" in prompt


def test_schema_roundtrip_equality():
    p1 = Personality(name="puck", channel="telegram", description="desc", system_prompt="sp")
    p2 = Personality(name="puck", channel="telegram", archetype="desc", tone="sp")
    # Both should be valid because new schema fields are optional
    assert p1.name == p2.name == "puck"
