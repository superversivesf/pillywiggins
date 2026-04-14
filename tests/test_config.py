from pillywiggins.config import Settings


def test_settings_defaults():
    s = Settings()
    assert s.agent_id == "puck"
    assert s.channel == "telegram"
    assert s.personality_file == "/config/telegram.yaml"
    assert s.database_url == "postgresql://pillywiggins:changeme@postgres:5432/pillywiggins"
    assert s.pg_password == "changeme"
    assert s.redis_url == "redis://redis:6379/0"
    assert s.nats_url == "nats://nats:4222"
    assert s.llm_provider == "ollama"
    assert s.llm_base_url == "http://localhost:11434"
    assert s.llm_api_key == ""
    assert s.model_name == "qwen3.5:8b"
    assert s.embedding_model == "nomic-embed-text"
    assert s.telegram_bot_token == ""


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