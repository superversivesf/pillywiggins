import os

from pillywiggins.agents.brain import create_brain


def test_create_brain_ollama_sets_base_url(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    agent = create_brain(
        personality_prompt="You are Puck.",
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://ollama-host:11434",
        api_key="",
    )
    assert os.environ["OLLAMA_BASE_URL"] == "http://ollama-host:11434"
    assert "OLLAMA_API_KEY" not in os.environ


def test_create_brain_ollama_default_base_url(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    agent = create_brain(
        personality_prompt="You are Puck.",
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="",
        api_key="",
    )
    assert os.environ["OLLAMA_BASE_URL"] == "http://localhost:11434"


def test_create_brain_ollama_sets_api_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    create_brain(
        personality_prompt="Hello",
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="sk-ollama-key",
    )
    assert os.environ["OLLAMA_API_KEY"] == "sk-ollama-key"


def test_create_brain_ollama_no_api_key_when_empty(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    create_brain(
        personality_prompt="Hello",
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
    )
    assert "OLLAMA_API_KEY" not in os.environ


def test_create_brain_openai_sets_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    agent = create_brain(
        personality_prompt="You are Puck.",
        model_name="gpt-4o",
        provider="openai",
        base_url="",
        api_key="sk-test-key",
    )
    assert os.environ["OPENAI_API_KEY"] == "sk-test-key"
    assert "OPENAI_BASE_URL" not in os.environ


def test_create_brain_openai_sets_base_url(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    create_brain(
        personality_prompt="Hello",
        model_name="gpt-4o",
        provider="openai",
        base_url="https://api.custom-openai.com/v1",
        api_key="sk-test-key",
    )
    assert os.environ["OPENAI_BASE_URL"] == "https://api.custom-openai.com/v1"


def test_create_brain_openai_no_base_url_when_empty(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    create_brain(
        personality_prompt="Hello",
        model_name="gpt-4o",
        provider="openai",
        base_url="",
        api_key="sk-test-key",
    )
    assert "OPENAI_BASE_URL" not in os.environ


def test_create_brain_system_prompt(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    agent = create_brain(
        personality_prompt="You are a mischievous fairy named Puck.",
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
    )
    assert agent._system_prompts == ("You are a mischievous fairy named Puck.",)


def test_create_brain_env_vars_cleanup(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    create_brain(
        personality_prompt="Hello",
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://my-ollama:11434",
        api_key="key123",
    )
    assert os.environ["OLLAMA_BASE_URL"] == "http://my-ollama:11434"
    assert os.environ["OLLAMA_API_KEY"] == "key123"