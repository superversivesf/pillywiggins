import os
from pathlib import Path

import pytest

from pillywiggins.config import Settings


@pytest.fixture(autouse=True)
def _clear_embedding_env(monkeypatch):
    """Remove EMBEDDING_* env vars before each test to avoid cross-test pollution."""
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_DIMENSION", raising=False)


def test_settings_with_explicit_unknown_embedding_model_logs_warning(caplog):
    """An explicit embedding_model not in KNOWN_EMBEDDING_DIMENSIONS shouldn't crash."""
    s = Settings(embedding_model="totally-unknown-model-v1")
    with caplog.at_level("INFO", logger="pillywiggins.config"):
        s.resolve_embedding_config()
    assert "has unknown dimension; using default" in caplog.text
    assert s.embedding_dimension == 768  # the default stays intact


def test_settings_resolve_embedding_fallback_writes_empty_model_safely(monkeypatch, caplog):
    """When falling back to HF, os.environ IS written with EMBEDDING_MODEL=''
    (safe now that log guards dim). A second Settings() sees the empty string."""
    from unittest.mock import AsyncMock

    # Patch the resolver so that Ollama discovery returns nothing (fallback)
    monkeypatch.setattr(
        "pillywiggins.embeddings.resolver.discover_ollama_embedding_model",
        AsyncMock(return_value=None),
    )

    # Ensure env vars are cleared before test
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_DIMENSION", raising=False)

    s = Settings(embedding_model="auto")
    with caplog.at_level("INFO", logger="pillywiggins.config"):
        s.resolve_embedding_config()

    # ensure fallback happened
    assert s.embedding_model == ""
    # env IS written with empty string so later Settings() instances don't re-read 'auto'
    assert os.environ.get("EMBEDDING_MODEL") == ""
    # ensure dimension was set from DEFAULT_HF_MODEL
    assert s.embedding_dimension == 384

    # A fresh Settings() instance should read the empty string, not "auto"
    s2 = Settings()
    assert s2.embedding_model == ""
    # Calling resolve again on the second instance must not crash
    s2.resolve_embedding_config()
    assert s2.embedding_model == ""

    # cleanup: remove env vars so subsequent tests aren't affected
    os.environ.pop("EMBEDDING_DIMENSION", None)
    os.environ.pop("EMBEDDING_MODEL", None)


def test_settings_defaults():
    # When a local .env file exists, it overrides defaults.
    # This test only asserts fields that have stable defaults regardless of .env.
    s = Settings()
    assert s.agent_id == "puck"
    assert s.channel == "telegram"
    assert s.personality_file == "/config/fey_court/puck.yaml"
    assert s.database_url == "postgresql://pillywiggins:changeme@postgres:5432/pillywiggins"
    assert s.pg_password == "changeme"
    assert s.redis_url == "redis://redis:6379/0"
    assert s.nats_url == "nats://nats:4222"
    assert s.llm_provider == "ollama"
    assert s.llm_base_url == "http://host.docker.internal:11434/v1"
    assert s.llm_api_key == ""
    assert s.model_name == "qwen3.5:8b"
    assert s.telegram_bot_token == ""


def test_settings_embedding_model_default_without_env(monkeypatch):
    """When .env doesn't override, embedding_model defaults to 'auto'."""
    # Prevent .env from being read by passing an explicit empty override
    monkeypatch.setenv("EMBEDDING_MODEL", "auto")
    s = Settings()
    assert s.embedding_model == "auto"


def test_settings_override_all_fields():
    s = Settings(
        agent_id="oberon",
        channel="discord",
        personality_file="/config/discord.yaml",
        database_url="postgresql://user:pass@db:5432/mydb",
        pg_password="secret",
        redis_url="redis://myredis:6379/1",
        nats_url="nats://mynats:4222",
        llm_provider="openai",
        llm_base_url="https://api.openai.com/v1",
        llm_api_key="sk-abc123",
        model_name="gpt-4o",
        embedding_model="text-embedding-3-small",
        telegram_bot_token="123456:ABC",
    )
    assert s.agent_id == "oberon"
    assert s.channel == "discord"
    assert s.personality_file == "/config/discord.yaml"
    assert s.database_url == "postgresql://user:pass@db:5432/mydb"
    assert s.pg_password == "secret"
    assert s.redis_url == "redis://myredis:6379/1"
    assert s.nats_url == "nats://mynats:4222"
    assert s.llm_provider == "openai"
    assert s.llm_base_url == "https://api.openai.com/v1"
    assert s.llm_api_key == "sk-abc123"
    assert s.model_name == "gpt-4o"
    assert s.embedding_model == "text-embedding-3-small"
    assert s.telegram_bot_token == "123456:ABC"


def test_settings_env_var_override(monkeypatch):
    monkeypatch.setenv("AGENT_ID", "titania")
    monkeypatch.setenv("CHANNEL", "slack")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-from-env")
    monkeypatch.setenv("MODEL_NAME", "gpt-4o-mini")
    s = Settings()
    assert s.agent_id == "titania"
    assert s.channel == "slack"
    assert s.llm_provider == "openai"
    assert s.llm_api_key == "sk-from-env"
    assert s.model_name == "gpt-4o-mini"


def test_settings_partial_override_keeps_defaults(monkeypatch):
    monkeypatch.setenv("AGENT_ID", "mustardseed")
    s = Settings()
    assert s.agent_id == "mustardseed"
    assert s.channel == "telegram"
    assert s.llm_provider == "ollama"
    assert s.llm_api_key == ""


def test_get_allowed_user_ids_empty_returns_empty():
    s = Settings(allowed_user_ids="")
    assert s.get_allowed_user_ids() == set()


def test_get_allowed_user_ids_all_returns_empty():
    s = Settings(allowed_user_ids="all")
    assert s.get_allowed_user_ids() == set()


def test_get_allowed_user_ids_all_case_insensitive():
    s = Settings(allowed_user_ids="ALL")
    assert s.get_allowed_user_ids() == set()


def test_get_allowed_user_ids_parses_comma_separated():
    s = Settings(allowed_user_ids="42,100,999")
    result = s.get_allowed_user_ids()
    assert result == {42, 100, 999}


def test_get_allowed_user_ids_strips_whitespace():
    s = Settings(allowed_user_ids=" 42 , 100 ")
    result = s.get_allowed_user_ids()
    assert result == {42, 100}


def test_get_allowed_user_ids_single_id():
    s = Settings(allowed_user_ids="42")
    result = s.get_allowed_user_ids()
    assert result == {42}


def test_get_allowed_user_ids_whitespace_only_returns_empty():
    s = Settings(allowed_user_ids="   ")
    result = s.get_allowed_user_ids()
    assert result == set()


def test_get_allowed_user_ids_mixed_empty_entries():
    s = Settings(allowed_user_ids="42,,100,")
    result = s.get_allowed_user_ids()
    assert result == {42, 100}


def test_get_allowed_user_ids_all_mixed_case():
    s = Settings(allowed_user_ids="All")
    result = s.get_allowed_user_ids()
    assert result == set()


def test_settings_compact_keep_messages_default():
    s = Settings()
    assert s.compact_keep_messages == 6


def test_settings_compact_truncate_message_chars_default():
    s = Settings()
    assert s.compact_truncate_message_chars == 2000


def test_settings_skills_dir_default():
    s = Settings()
    assert s.skills_dir == "/app/skills"


def test_settings_model_config_env_file():
    s = Settings()
    assert s.model_config["env_file"] == ".env"
    assert s.model_config["env_file_encoding"] == "utf-8"


def test_settings_override_compact_values():
    s = Settings(compact_keep_messages=10, compact_truncate_message_chars=500)
    assert s.compact_keep_messages == 10
    assert s.compact_truncate_message_chars == 500


def test_settings_agents_config_path_default():
    s = Settings()
    assert s.agents_config_path == "agents.yaml"


def test_settings_agents_config_path_override():
    s = Settings(agents_config_path="/custom/agents.yaml")
    assert s.agents_config_path == "/custom/agents.yaml"


def test_settings_agents_config_path_from_env(monkeypatch):
    monkeypatch.setenv("AGENTS_CONFIG_PATH", "/env/agents.yaml")
    s = Settings()
    assert s.agents_config_path == "/env/agents.yaml"


def test_dotenv_telegram_token_not_a_timezone_string():
    """PUCK_TELEGRAM_TOKEN must not be a timezone string (regression check)."""
    env_path = Path(".env")
    if env_path.exists():
        content = env_path.read_text()
        for line in content.splitlines():
            if line.startswith("PUCK_TELEGRAM_TOKEN="):
                value = line.split("=", 1)[1]
                assert value != "Europe/Helsinki", (
                    "PUCK_TELEGRAM_TOKEN should not be a timezone string "
                    "( Europe/Helsinki ) in .env"
                )
                return
        pytest.fail("PUCK_TELEGRAM_TOKEN not found in .env")
    else:
        pytest.skip("No .env file present")


def test_env_example_telegram_token_is_placeholder():
    """env.example must contain a placeholder, not a real token or timezone."""
    env_example_path = Path("env.example")
    assert env_example_path.exists(), "env.example should exist"
    content = env_example_path.read_text()
    for line in content.splitlines():
        if line.startswith("PUCK_TELEGRAM_TOKEN="):
            value = line.split("=", 1)[1]
            assert value != "Europe/Helsinki", (
                "PUCK_TELEGRAM_TOKEN should not be a timezone string in env.example"
            )
            assert value != "", "PUCK_TELEGRAM_TOKEN should not be empty in env.example"
            return
    pytest.fail("PUCK_TELEGRAM_TOKEN not found in env.example")
