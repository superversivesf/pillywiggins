from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.agents.brain import create_brain, recall_private_memory
from pillywiggins.agents.deps import AgentDeps


def test_create_brain_registers_recall_tool(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    agent = create_brain(
        personality_prompt="You are Puck.",
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
    )
    tool_names = [t.name for t in agent._function_toolset.tools.values()]
    assert "recall_private_memory" in tool_names


@pytest.mark.asyncio
async def test_recall_private_memory_no_memory():
    deps = AgentDeps(agent_id="puck", channel="telegram", private_memory=None)
    mock_ctx = MagicMock()
    mock_ctx.deps = deps

    result = await recall_private_memory(mock_ctx, "test query")

    assert result == "Private memory is not available."


@pytest.mark.asyncio
async def test_recall_private_memory_returns_results():
    mock_memory = MagicMock()
    mock_memory.search = AsyncMock(return_value=[
        {"content": "remembered thing", "similarity": 0.95},
        {"content": "another memory", "similarity": 0.80},
    ])

    deps = AgentDeps(agent_id="puck", channel="telegram", private_memory=mock_memory)
    mock_ctx = MagicMock()
    mock_ctx.deps = deps

    mock_settings = MagicMock()
    mock_settings.llm_base_url = "http://localhost:11434"
    mock_settings.llm_api_key = ""
    mock_settings.llm_provider = "ollama"
    mock_settings.embedding_model = "nomic-embed-text"

    with patch("pillywiggins.memory.embeddings.embed", new_callable=AsyncMock, return_value=[0.1, 0.2, 0.3]), \
         patch("pillywiggins.config.Settings", return_value=mock_settings):
        result = await recall_private_memory(mock_ctx, "test query")

    assert "remembered thing" in result
    assert "0.95" in result
    assert "another memory" in result


@pytest.mark.asyncio
async def test_recall_private_memory_no_results():
    mock_memory = MagicMock()
    mock_memory.search = AsyncMock(return_value=[])

    deps = AgentDeps(agent_id="puck", channel="telegram", private_memory=mock_memory)
    mock_ctx = MagicMock()
    mock_ctx.deps = deps

    mock_settings = MagicMock()
    mock_settings.llm_base_url = "http://localhost:11434"
    mock_settings.llm_api_key = ""
    mock_settings.llm_provider = "ollama"
    mock_settings.embedding_model = "nomic-embed-text"

    with patch("pillywiggins.memory.embeddings.embed", new_callable=AsyncMock, return_value=[0.1, 0.2, 0.3]), \
         patch("pillywiggins.config.Settings", return_value=mock_settings):
        result = await recall_private_memory(mock_ctx, "test query")

    assert result == "No memories found matching that query."


@pytest.mark.asyncio
async def test_recall_private_memory_embedding_fails():
    mock_memory = MagicMock()

    deps = AgentDeps(agent_id="puck", channel="telegram", private_memory=mock_memory)
    mock_ctx = MagicMock()
    mock_ctx.deps = deps

    mock_settings = MagicMock()
    mock_settings.llm_base_url = "http://localhost:11434"
    mock_settings.llm_api_key = ""
    mock_settings.llm_provider = "ollama"
    mock_settings.embedding_model = "nomic-embed-text"

    with patch("pillywiggins.memory.embeddings.embed", new_callable=AsyncMock, return_value=None), \
         patch("pillywiggins.config.Settings", return_value=mock_settings):
        result = await recall_private_memory(mock_ctx, "test query")

    assert result == "Could not generate embedding for search."