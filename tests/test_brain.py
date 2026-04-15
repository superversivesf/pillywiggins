import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext

from pillywiggins.agents.brain import (
    create_brain,
    recall_private_memory,
    save_to_private_memory,
    query_council_memory,
    share_to_council,
    _make_skill_tool,
    build_skill,
    review_skill_code,
    deploy_skill_code,
)
from pillywiggins.agents.deps import AgentDeps
from pillywiggins.skills.registry import Skill, SkillRegistry


def _make_ctx(agent_id="puck", channel="discord", private_memory=None, skill_registry=None, council_memory=None, nats_bus=None):
    ctx = MagicMock(spec=RunContext)
    ctx.deps = AgentDeps(
        agent_id=agent_id,
        channel=channel,
        private_memory=private_memory,
        skill_registry=skill_registry,
        council_memory=council_memory,
        nats_bus=nats_bus,
    )
    return ctx


def _make_skill(name="test_skill", description="A test skill", run_func=None, meta=None, permissions=None):
    if run_func is None:
        run_func = AsyncMock(return_value="ok")
    if meta is None:
        meta = {"name": name, "description": description}
    if permissions is None:
        permissions = {"network": False, "subprocess": False, "file_write": False}
    return Skill(name=name, description=description, run_func=run_func, meta=meta, permissions=permissions)


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


def test_create_brain_registers_builtin_tools(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    agent = create_brain(
        personality_prompt="Hello",
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
    )
    tool_names = list(agent._function_toolset.tools.keys())
    assert "recall_private_memory" in tool_names
    assert "save_to_private_memory" in tool_names
    assert "query_council_memory" in tool_names
    assert "share_to_council" in tool_names
    assert "build_skill" in tool_names
    assert "test_skill_code" in tool_names
    assert "review_skill_code" in tool_names
    assert "deploy_skill_code" in tool_names


def test_create_brain_registers_skill_tools(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    registry = MagicMock(spec=SkillRegistry)
    skill = _make_skill(name="weather_check", description="Checks weather")
    registry.list_skills.return_value = [skill]
    agent = create_brain(
        personality_prompt="Hello",
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
        skill_registry=registry,
    )
    tool_names = list(agent._function_toolset.tools.keys())
    assert "weather_check" in tool_names


def test_create_brain_no_skill_registry_no_skill_tools(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    agent = create_brain(
        personality_prompt="Hello",
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
        skill_registry=None,
    )
    tool_names = list(agent._function_toolset.tools.keys())
    assert "recall_private_memory" in tool_names
    assert "save_to_private_memory" in tool_names
    assert "query_council_memory" in tool_names
    assert "share_to_council" in tool_names
    assert len(tool_names) == 8
    assert "build_skill" in tool_names
    assert "test_skill_code" in tool_names
    assert "review_skill_code" in tool_names
    assert "deploy_skill_code" in tool_names


def test_create_brain_empty_skill_registry(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    registry = MagicMock(spec=SkillRegistry)
    registry.list_skills.return_value = []
    agent = create_brain(
        personality_prompt="Hello",
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
        skill_registry=registry,
    )
    tool_names = list(agent._function_toolset.tools.keys())
    assert len(tool_names) == 8


def test_create_brain_multiple_skill_tools(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    registry = MagicMock(spec=SkillRegistry)
    skill1 = _make_skill(name="weather", description="Weather skill")
    skill2 = _make_skill(name="calculator", description="Calc skill")
    skill3 = _make_skill(name="translator", description="Translate skill")
    registry.list_skills.return_value = [skill1, skill2, skill3]
    agent = create_brain(
        personality_prompt="Hello",
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
        skill_registry=registry,
    )
    tool_names = list(agent._function_toolset.tools.keys())
    assert "weather" in tool_names
    assert "calculator" in tool_names
    assert "translator" in tool_names
    assert len(tool_names) == 11


def test_create_brain_deps_type_is_agent_deps(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    agent = create_brain(
        personality_prompt="Hello",
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
    )
    assert agent._deps_type is AgentDeps


class TestRecallPrivateMemoryEdgeCases:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_private_memory_none(self):
        ctx = _make_ctx(private_memory=None)
        result = await recall_private_memory(ctx, "test query")
        assert result == "Private memory is not available."

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_message_when_embedding_is_none(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = None
        memory = MagicMock()
        ctx = _make_ctx(private_memory=memory)
        result = await recall_private_memory(ctx, "test")
        assert result == "Could not generate embedding for search."
        memory.search.assert_not_called()

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_not_found_when_search_empty(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        memory = MagicMock()
        memory.search = AsyncMock(return_value=[])
        ctx = _make_ctx(private_memory=memory)
        result = await recall_private_memory(ctx, "nothing here")
        assert result == "No memories found matching that query."

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_formatted_results_when_found(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        memory = MagicMock()
        memory.search = AsyncMock(return_value=[
            {"content": "I like tea", "similarity": 0.95},
            {"content": "I live in London", "similarity": 0.80},
        ])
        ctx = _make_ctx(private_memory=memory)
        result = await recall_private_memory(ctx, "preferences")
        assert "I like tea" in result
        assert "0.95" in result
        assert "I live in London" in result
        assert "0.80" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_search_uses_embedding_from_settings(self, mock_settings_cls, mock_embed):
        mock_settings = MagicMock()
        mock_settings.llm_base_url = "http://custom:11434"
        mock_settings.llm_api_key = "key"
        mock_settings.llm_provider = "ollama"
        mock_settings.embedding_model = "nomic-embed-text"
        mock_settings_cls.return_value = mock_settings
        mock_embed.return_value = [0.5]
        memory = MagicMock()
        memory.search = AsyncMock(return_value=[])
        ctx = _make_ctx(private_memory=memory)
        await recall_private_memory(ctx, "test")
        mock_embed.assert_awaited_once_with(
            "test",
            base_url="http://custom:11434",
            api_key="key",
            provider="ollama",
            model="nomic-embed-text",
        )


class TestSaveToPrivateMemoryEdgeCases:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_private_memory_none(self):
        ctx = _make_ctx(private_memory=None)
        result = await save_to_private_memory(ctx, "something")
        assert result == "Private memory is not available."

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_error_when_embedding_is_none(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = None
        memory = MagicMock()
        ctx = _make_ctx(private_memory=memory)
        result = await save_to_private_memory(ctx, "something")
        assert result == "Could not generate embedding — memory not saved."
        memory.save.assert_not_called()

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_saves_content_with_embedding(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        memory = MagicMock()
        memory.save = AsyncMock()
        ctx = _make_ctx(private_memory=memory)
        result = await save_to_private_memory(ctx, "I prefer tea over coffee")
        memory.save.assert_awaited_once_with("I prefer tea over coffee", [0.1, 0.2, 0.3])
        assert result == "Remembered: I prefer tea over coffee"

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_confirmation_includes_content(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.5]
        memory = MagicMock()
        memory.save = AsyncMock()
        ctx = _make_ctx(private_memory=memory)
        result = await save_to_private_memory(ctx, "user likes cats")
        assert "Remembered:" in result
        assert "user likes cats" in result


class TestQueryCouncilMemory:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_council_memory_none(self):
        ctx = _make_ctx(council_memory=None)
        result = await query_council_memory(ctx, "test query")
        assert result == "Council memory is not available."

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_not_found_when_search_empty(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.search = AsyncMock(return_value=[])
        ctx = _make_ctx(council_memory=council)
        result = await query_council_memory(ctx, "nothing here")
        assert result == "No council insights found matching that query."

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_formatted_results_when_found(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.search = AsyncMock(return_value=[
            {"content": "sky is blue", "contributing_agent": "puck", "message_type": "insight"},
            {"content": "water is wet", "contributing_agent": "oberon", "message_type": "observation"},
        ])
        ctx = _make_ctx(council_memory=council)
        result = await query_council_memory(ctx, "nature facts")
        assert "[insight]" in result
        assert "sky is blue" in result
        assert "puck" in result
        assert "[observation]" in result
        assert "water is wet" in result
        assert "oberon" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_message_when_embedding_is_none(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = None
        council = MagicMock()
        ctx = _make_ctx(council_memory=council)
        result = await query_council_memory(ctx, "test")
        assert result == "Could not generate embedding for council search."
        council.search.assert_not_called()


class TestShareToCouncil:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_council_memory_none(self):
        ctx = _make_ctx(council_memory=None)
        result = await share_to_council(ctx, "insight content")
        assert result == "Council memory is not available."

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_error_when_embedding_is_none(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = None
        council = MagicMock()
        ctx = _make_ctx(council_memory=council)
        result = await share_to_council(ctx, "something")
        assert result == "Could not generate embedding — council insight not shared."
        council.write_entry.assert_not_called()

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_writes_entry_with_parsed_tags(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.write_entry = AsyncMock(return_value={"success": True, "error": None, "id": "abc-123"})
        ctx = _make_ctx(council_memory=council, nats_bus=None)
        result = await share_to_council(ctx, "important finding", tags="idea, learning", message_type="insight")
        council.write_entry.assert_awaited_once_with(
            content="important finding",
            tags=["idea", "learning"],
            embedding=[0.1, 0.2, 0.3],
            message_type="insight",
        )
        assert result == "Shared to council: important finding"

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_writes_entry_with_empty_tags(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.write_entry = AsyncMock(return_value={"success": True, "error": None, "id": "abc-123"})
        ctx = _make_ctx(council_memory=council, nats_bus=None)
        result = await share_to_council(ctx, "tagless insight")
        council.write_entry.assert_awaited_once_with(
            content="tagless insight",
            tags=[],
            embedding=[0.1, 0.2, 0.3],
            message_type="insight",
        )
        assert result == "Shared to council: tagless insight"

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_publishes_via_nats_bus(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.write_entry = AsyncMock(return_value={"success": True, "error": None, "id": "abc-123"})
        nats = MagicMock()
        nats.publish_broadcast = AsyncMock()
        ctx = _make_ctx(council_memory=council, nats_bus=nats)
        result = await share_to_council(ctx, "shared finding", tags="idea", message_type="insight")
        nats.publish_broadcast.assert_awaited_once_with("insight", {"content": "shared finding", "tags": ["idea"]})
        assert result == "Shared to council: shared finding"

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_error_on_write_failure(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.write_entry = AsyncMock(return_value={"success": False, "error": "Rate limit exceeded", "id": None})
        ctx = _make_ctx(council_memory=council, nats_bus=None)
        result = await share_to_council(ctx, "too many posts")
        assert "Rate limit exceeded" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_nats_publish_failure_does_not_crash(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.write_entry = AsyncMock(return_value={"success": True, "error": None, "id": "abc-123"})
        nats = MagicMock()
        nats.publish_broadcast = AsyncMock(side_effect=ConnectionError("NATS down"))
        ctx = _make_ctx(council_memory=council, nats_bus=nats)
        result = await share_to_council(ctx, "still works")
        assert result == "Shared to council: still works"