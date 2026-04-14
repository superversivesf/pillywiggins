import yaml

from pillywiggins.agents.personality import Personality, load_personality


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
    assert p.scheduling == {}


def test_personality_dataclass_with_all_fields():
    p = Personality(
        name="oberon",
        channel="discord",
        description="King of the fairies",
        system_prompt="You are Oberon, king of fairies.",
        traits=["regal", "wise", "jealous"],
        scheduling={"interval": 120, "enabled": True},
    )
    assert p.name == "oberon"
    assert p.channel == "discord"
    assert p.traits == ["regal", "wise", "jealous"]
    assert p.scheduling == {"interval": 120, "enabled": True}


def test_load_personality_from_yaml(tmp_path):
    data = {
        "name": "puck",
        "channel": "telegram",
        "description": "A mischievous fairy",
        "system_prompt": "You are Puck, a mischievous fairy.",
        "traits": ["playful", "trickster"],
        "scheduling": {"interval": 60},
    }
    path = tmp_path / "personality.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    assert p.name == "puck"
    assert p.channel == "telegram"
    assert p.description == "A mischievous fairy"
    assert p.system_prompt == "You are Puck, a mischievous fairy."
    assert p.traits == ["playful", "trickster"]
    assert p.scheduling == {"interval": 60}


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
    assert p.scheduling == {}


def test_load_personality_empty_traits(tmp_path):
    data = {
        "name": "cobweb",
        "channel": "matrix",
        "description": "A fairy attendant",
        "system_prompt": "You are Cobweb.",
        "traits": [],
        "scheduling": {},
    }
    path = tmp_path / "empty_opts.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    assert p.traits == []
    assert p.scheduling == {}


def test_load_personality_complex_scheduling(tmp_path):
    data = {
        "name": "puck",
        "channel": "telegram",
        "description": "A fairy",
        "system_prompt": "You are Puck.",
        "scheduling": {"interval": 30, "enabled": True, "timezone": "UTC"},
    }
    path = tmp_path / "complex.yaml"
    path.write_text(yaml.dump(data))
    p = load_personality(str(path))
    assert p.scheduling["interval"] == 30
    assert p.scheduling["enabled"] is True
    assert p.scheduling["timezone"] == "UTC"