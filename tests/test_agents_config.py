import os
from unittest.mock import patch

import pytest
import yaml

from pillywiggins.agents_config import AgentConfig, apply_agent_env, get_agent_config, load_agents_config


def _write_agents_yaml(tmp_path, data):
    path = tmp_path / "agents.yaml"
    path.write_text(yaml.dump(data))
    return str(path)


def test_load_agents_config_single_agent(tmp_path):
    data = {
        "agents": [
            {
                "id": "puck",
                "personality": "/config/puck.yaml",
                "channel": "telegram",
                "allowed_user_ids": "all",
                "environment": {"TELEGRAM_BOT_TOKEN": "${PUCK_TELEGRAM_TOKEN}"},
            }
        ]
    }
    path = _write_agents_yaml(tmp_path, data)
    configs = load_agents_config(path)
    assert len(configs) == 1
    assert configs[0].id == "puck"
    assert configs[0].personality == "/config/puck.yaml"
    assert configs[0].channel == "telegram"
    assert configs[0].allowed_user_ids == "all"
    assert configs[0].environment == {"TELEGRAM_BOT_TOKEN": "${PUCK_TELEGRAM_TOKEN}"}


def test_load_agents_config_multiple_agents(tmp_path):
    data = {
        "agents": [
            {"id": "puck", "personality": "/config/puck.yaml", "channel": "telegram"},
            {"id": "oberon", "personality": "/config/oberon.yaml", "channel": "discord"},
        ]
    }
    path = _write_agents_yaml(tmp_path, data)
    configs = load_agents_config(path)
    assert len(configs) == 2
    assert configs[0].id == "puck"
    assert configs[1].id == "oberon"


def test_load_agents_config_defaults(tmp_path):
    data = {"agents": [{"id": "puck", "personality": "/config/puck.yaml", "channel": "telegram"}]}
    path = _write_agents_yaml(tmp_path, data)
    configs = load_agents_config(path)
    assert configs[0].allowed_user_ids == "all"
    assert configs[0].environment == {}


def test_load_agents_config_file_not_found():
    with pytest.raises(FileNotFoundError, match="Agents config file not found"):
        load_agents_config("/nonexistent/agents.yaml")


def test_load_agents_config_missing_agents_key(tmp_path):
    path = tmp_path / "agents.yaml"
    path.write_text("something_else: true")
    with pytest.raises(ValueError, match="missing 'agents' key"):
        load_agents_config(str(path))


def test_load_agents_config_empty_file(tmp_path):
    path = tmp_path / "agents.yaml"
    path.write_text("")
    with pytest.raises(ValueError, match="missing 'agents' key"):
        load_agents_config(str(path))


def test_get_agent_config_found(tmp_path):
    data = {
        "agents": [
            {"id": "puck", "personality": "/config/puck.yaml", "channel": "telegram"},
            {"id": "oberon", "personality": "/config/oberon.yaml", "channel": "discord"},
        ]
    }
    path = _write_agents_yaml(tmp_path, data)
    config = get_agent_config("oberon", path=path)
    assert config.id == "oberon"
    assert config.channel == "discord"


def test_get_agent_config_not_found(tmp_path):
    data = {"agents": [{"id": "puck", "personality": "/config/puck.yaml", "channel": "telegram"}]}
    path = _write_agents_yaml(tmp_path, data)
    with pytest.raises(ValueError, match="Agent 'oberon' not found"):
        get_agent_config("oberon", path=path)


def test_apply_agent_env_expands_vars(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "secret123")
    cfg = AgentConfig(
        id="puck",
        personality="/config/puck.yaml",
        channel="telegram",
        environment={"TELEGRAM_BOT_TOKEN": "${MY_TOKEN}"},
    )
    apply_agent_env(cfg)
    assert os.environ["TELEGRAM_BOT_TOKEN"] == "secret123"


def test_apply_agent_env_missing_var(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    cfg = AgentConfig(
        id="puck",
        personality="/config/puck.yaml",
        channel="telegram",
        environment={"SOME_KEY": "${MISSING_VAR}"},
    )
    apply_agent_env(cfg)
    assert os.environ["SOME_KEY"] == ""


def test_apply_agent_env_plain_value():
    cfg = AgentConfig(
        id="puck",
        personality="/config/puck.yaml",
        channel="telegram",
        environment={"PLAIN_KEY": "no_vars_here"},
    )
    apply_agent_env(cfg)
    assert os.environ["PLAIN_KEY"] == "no_vars_here"


def test_apply_agent_env_empty_environment():
    cfg = AgentConfig(
        id="puck",
        personality="/config/puck.yaml",
        channel="telegram",
        environment={},
    )
    old_env = dict(os.environ)
    apply_agent_env(cfg)
    assert os.environ == old_env


def test_apply_agent_env_multiple_vars(monkeypatch):
    monkeypatch.setenv("TOKEN_A", "aaa")
    monkeypatch.setenv("TOKEN_B", "bbb")
    cfg = AgentConfig(
        id="puck",
        personality="/config/puck.yaml",
        channel="telegram",
        environment={
            "KEY_A": "${TOKEN_A}",
            "KEY_B": "${TOKEN_B}",
        },
    )
    apply_agent_env(cfg)
    assert os.environ["KEY_A"] == "aaa"
    assert os.environ["KEY_B"] == "bbb"


def test_agent_config_dataclass():
    cfg = AgentConfig(id="puck", personality="/config/puck.yaml", channel="telegram")
    assert cfg.id == "puck"
    assert cfg.allowed_user_ids == "all"
    assert cfg.environment == {}


def test_apply_agent_env_resets_settings(monkeypatch):
    monkeypatch.setenv("AGENT_ID", "puck")
    monkeypatch.setenv("MY_SECRET", "tok_123")
    cfg = AgentConfig(
        id="puck",
        personality="/config/puck.yaml",
        channel="telegram",
        environment={"TELEGRAM_BOT_TOKEN": "${MY_SECRET}"},
    )
    apply_agent_env(cfg)
    from pillywiggins.config import Settings
    s = Settings()
    assert s.telegram_bot_token == "tok_123"
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)


def test_load_agents_config_duplicate_ids(tmp_path):
    data = {
        "agents": [
            {"id": "puck", "personality": "/config/puck.yaml", "channel": "telegram"},
            {"id": "puck", "personality": "/config/puck2.yaml", "channel": "discord"},
        ]
    }
    path = _write_agents_yaml(tmp_path, data)
    configs = load_agents_config(path)
    assert len(configs) == 2
    assert configs[0].id == "puck"
    assert configs[1].id == "puck"
    assert configs[0].channel == "telegram"
    assert configs[1].channel == "discord"


def test_get_agent_config_returns_first_on_duplicate_ids(tmp_path):
    data = {
        "agents": [
            {"id": "puck", "personality": "/config/puck.yaml", "channel": "telegram"},
            {"id": "puck", "personality": "/config/puck2.yaml", "channel": "discord"},
        ]
    }
    path = _write_agents_yaml(tmp_path, data)
    config = get_agent_config("puck", path=path)
    assert config.channel == "telegram"
    assert config.personality == "/config/puck.yaml"


def test_load_agents_config_empty_agents_list(tmp_path):
    data = {"agents": []}
    path = _write_agents_yaml(tmp_path, data)
    configs = load_agents_config(path)
    assert configs == []


def test_load_agents_config_missing_channel(tmp_path):
    data = {
        "agents": [
            {"id": "puck", "personality": "/config/puck.yaml"},
        ]
    }
    path = _write_agents_yaml(tmp_path, data)
    with pytest.raises(KeyError):
        load_agents_config(path)


def test_load_agents_config_missing_personality(tmp_path):
    data = {
        "agents": [
            {"id": "puck", "channel": "telegram"},
        ]
    }
    path = _write_agents_yaml(tmp_path, data)
    with pytest.raises(KeyError):
        load_agents_config(path)


def test_load_agents_config_missing_id(tmp_path):
    data = {
        "agents": [
            {"personality": "/config/puck.yaml", "channel": "telegram"},
        ]
    }
    path = _write_agents_yaml(tmp_path, data)
    with pytest.raises(KeyError):
        load_agents_config(path)


def test_apply_agent_env_does_not_overwrite_existing_unset_var(monkeypatch):
    monkeypatch.setenv("EXISTING_KEY", "original_value")
    monkeypatch.setenv("SRC_VAR", "new_value")
    cfg = AgentConfig(
        id="puck",
        personality="/config/puck.yaml",
        channel="telegram",
        environment={"EXISTING_KEY": "${SRC_VAR}"},
    )
    apply_agent_env(cfg)
    assert os.environ["EXISTING_KEY"] == "new_value"


def test_apply_agent_env_nested_var_references(monkeypatch):
    monkeypatch.setenv("BASE_TOKEN", "abc123")
    cfg = AgentConfig(
        id="puck",
        personality="/config/puck.yaml",
        channel="telegram",
        environment={"BOT_TOKEN": "prefix-${BASE_TOKEN}-suffix"},
    )
    apply_agent_env(cfg)
    assert os.environ["BOT_TOKEN"] == "prefix-abc123-suffix"


def test_apply_agent_env_multiple_nested_vars(monkeypatch):
    monkeypatch.setenv("REGION", "us-east")
    monkeypatch.setenv("STAGE", "prod")
    cfg = AgentConfig(
        id="puck",
        personality="/config/puck.yaml",
        channel="telegram",
        environment={"ENDPOINT": "https://${REGION}.${STAGE}.example.com"},
    )
    apply_agent_env(cfg)
    assert os.environ["ENDPOINT"] == "https://us-east.prod.example.com"


def test_apply_agent_env_preserves_plain_values_among_vars(monkeypatch):
    monkeypatch.setenv("DYN_TOKEN", "dynamic")
    cfg = AgentConfig(
        id="puck",
        personality="/config/puck.yaml",
        channel="telegram",
        environment={
            "STATIC_KEY": "plain_value",
            "DYNAMIC_KEY": "${DYN_TOKEN}",
        },
    )
    apply_agent_env(cfg)
    assert os.environ["STATIC_KEY"] == "plain_value"
    assert os.environ["DYNAMIC_KEY"] == "dynamic"


def test_load_agents_config_three_agents(tmp_path):
    data = {
        "agents": [
            {"id": "puck", "personality": "/config/puck.yaml", "channel": "telegram"},
            {"id": "bramblethorn", "personality": "/config/bramblethorn.yaml", "channel": "discord"},
            {"id": "foxglove", "personality": "/config/foxglove.yaml", "channel": "slack"},
        ]
    }
    path = _write_agents_yaml(tmp_path, data)
    configs = load_agents_config(path)
    assert len(configs) == 3
    assert [c.id for c in configs] == ["puck", "bramblethorn", "foxglove"]
    assert [c.channel for c in configs] == ["telegram", "discord", "slack"]


def test_agent_config_all_fields_specified():
    cfg = AgentConfig(
        id="puck",
        personality="/config/puck.yaml",
        channel="telegram",
        allowed_user_ids="42,100",
        environment={"TOKEN": "xyz"},
    )
    assert cfg.id == "puck"
    assert cfg.personality == "/config/puck.yaml"
    assert cfg.channel == "telegram"
    assert cfg.allowed_user_ids == "42,100"
    assert cfg.environment == {"TOKEN": "xyz"}