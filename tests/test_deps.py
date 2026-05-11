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
    assert f["council_memory"].default is None
    assert f["nats_bus"].default is None
    assert f["scheduler"].default is None


def test_init_with_required_fields_only():
    deps = AgentDeps(agent_id="puck", channel="telegram")

    assert deps.agent_id == "puck"
    assert deps.channel == "telegram"
    assert deps.private_memory is None
    assert deps.skill_registry is None
    assert deps.council_memory is None
    assert deps.nats_bus is None
    assert deps.scheduler is None


def test_init_with_all_fields():
    mock_memory = object()
    mock_registry = object()
    mock_council = object()
    mock_nats = object()
    mock_scheduler = object()
    mock_logger = object()
    deps = AgentDeps(
        agent_id="puck",
        channel="discord",
        private_memory=mock_memory,
        skill_registry=mock_registry,
        council_memory=mock_council,
        nats_bus=mock_nats,
        scheduler=mock_scheduler,
        logger=mock_logger,
        embedding_model="nomic-embed-text",
        llm_base_url="http://ollama:11434/v1",
        llm_api_key="",
        llm_provider="ollama",
        embedding_dimension=768,
    )

    assert deps.agent_id == "puck"
    assert deps.channel == "discord"
    assert deps.private_memory is mock_memory
    assert deps.skill_registry is mock_registry
    assert deps.council_memory is mock_council
    assert deps.nats_bus is mock_nats
    assert deps.scheduler is mock_scheduler
    assert deps.logger is mock_logger
    assert deps.embedding_model == "nomic-embed-text"
    assert deps.llm_base_url == "http://ollama:11434/v1"
    assert deps.llm_api_key == ""
    assert deps.llm_provider == "ollama"
    assert deps.embedding_dimension == 768


def test_optional_fields_are_properly_typed():
    f = {f.name: f for f in fields(AgentDeps)}
    assert f["private_memory"].type is not str
    type_str = str(f["private_memory"].type)
    assert "PrivateMemory" in type_str


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
    deps.council_memory = "council"
    deps.nats_bus = "nats"
    deps.scheduler = "scheduler"

    assert deps.agent_id == "oberon"
    assert deps.channel == "discord"
    assert deps.private_memory == "memory"
    assert deps.skill_registry == "registry"
    assert deps.council_memory == "council"
    assert deps.nats_bus == "nats"
    assert deps.scheduler == "scheduler"


def test_different_instances_are_independent():
    deps_a = AgentDeps(agent_id="puck", channel="telegram")
    deps_b = AgentDeps(agent_id="oberon", channel="discord", private_memory=object())

    assert deps_a.agent_id != deps_b.agent_id
    assert deps_a.channel != deps_b.channel
    assert deps_a.private_memory is None
    assert deps_b.private_memory is not None