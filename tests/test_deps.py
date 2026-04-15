from dataclasses import fields

import pytest

from pillywiggins.agents.deps import AgentDeps


def test_required_fields_are_agent_id_and_channel():
    f = {f.name: f for f in fields(AgentDeps)}
    assert "agent_id" in f
    assert "channel" in f


def test_optional_fields_default_to_none():
    f = {f.name: f for f in fields(AgentDeps)}
    assert f["private_memory"].default is None
    assert f["skill_registry"].default is None


def test_init_with_required_fields_only():
    deps = AgentDeps(agent_id="puck", channel="telegram")

    assert deps.agent_id == "puck"
    assert deps.channel == "telegram"
    assert deps.private_memory is None
    assert deps.skill_registry is None


def test_init_with_all_fields():
    mock_memory = object()
    mock_registry = object()
    deps = AgentDeps(
        agent_id="puck",
        channel="discord",
        private_memory=mock_memory,
        skill_registry=mock_registry,
    )

    assert deps.agent_id == "puck"
    assert deps.channel == "discord"
    assert deps.private_memory is mock_memory
    assert deps.skill_registry is mock_registry


def test_optional_fields_are_typed_as_any():
    f = {f.name: f for f in fields(AgentDeps)}
    assert f["private_memory"].type is not str
    type_str = str(f["private_memory"].type)
    assert "Any" in type_str


def test_missing_required_field_raises():
    with pytest.raises(TypeError):
        AgentDeps(channel="telegram")


def test_missing_all_fields_raises():
    with pytest.raises(TypeError):
        AgentDeps()


def test_is_dataclass():
    from dataclasses import is_dataclass

    assert is_dataclass(AgentDeps)


def test_private_memory_accepts_arbitrary_object():
    sentinel = {"key": "value"}
    deps = AgentDeps(agent_id="puck", channel="slack", private_memory=sentinel)
    assert deps.private_memory is sentinel


def test_skill_registry_accepts_arbitrary_object():
    sentinel = [1, 2, 3]
    deps = AgentDeps(agent_id="puck", channel="slack", skill_registry=sentinel)
    assert deps.skill_registry is sentinel


def test_fields_are_mutable():
    deps = AgentDeps(agent_id="puck", channel="telegram")
    deps.agent_id = "oberon"
    deps.channel = "discord"
    deps.private_memory = "memory"
    deps.skill_registry = "registry"

    assert deps.agent_id == "oberon"
    assert deps.channel == "discord"
    assert deps.private_memory == "memory"
    assert deps.skill_registry == "registry"


def test_different_instances_are_independent():
    deps_a = AgentDeps(agent_id="puck", channel="telegram")
    deps_b = AgentDeps(agent_id="oberon", channel="discord", private_memory=object())

    assert deps_a.agent_id != deps_b.agent_id
    assert deps_a.channel != deps_b.channel
    assert deps_a.private_memory is None
    assert deps_b.private_memory is not None