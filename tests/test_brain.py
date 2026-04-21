import json
import os
from pathlib import Path
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
    _should_sandbox,
    build_skill,
    test_skill_code as run_skill_test,
    review_skill_code,
    deploy_skill_code,
    schedule_task,
    unschedule_task,
)
from pillywiggins.agents.deps import AgentDeps
from pillywiggins.agents.personality import Personality
from pillywiggins.skills.registry import Skill, SkillRegistry


def _make_ctx(
    agent_id="puck",
    channel="discord",
    private_memory=None,
    skill_registry=None,
    council_memory=None,
    nats_bus=None,
    scheduler=None,
):
    ctx = MagicMock(spec=RunContext)
    ctx.deps = AgentDeps(
        agent_id=agent_id,
        channel=channel,
        personality=None,
        private_memory=private_memory,
        skill_registry=skill_registry,
        council_memory=council_memory,
        nats_bus=nats_bus,
        scheduler=scheduler,
    )
    return ctx


def _make_skill(
    name="test_skill",
    description="A test skill",
    run_func=None,
    meta=None,
    permissions=None,
    file_path=None,
):
    if run_func is None:
        run_func = AsyncMock(return_value="ok")
    if meta is None:
        meta = {"name": name, "description": description}
    if permissions is None:
        permissions = {"network": False, "subprocess": False, "file_write": False}
    return Skill(
        name=name,
        description=description,
        run_func=run_func,
        meta=meta,
        permissions=permissions,
        file_path=file_path,
    )


def test_create_brain_ollama_sets_base_url(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    agent = create_brain(
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://ollama-host:11434",
        api_key="",
    )
    assert os.environ["OPENAI_BASE_URL"] == "http://ollama-host:11434/v1"
    assert os.environ["OPENAI_API_KEY"] == "ollama"


def test_create_brain_ollama_default_base_url(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    create_brain(
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="",
        api_key="",
    )
    assert os.environ["OPENAI_BASE_URL"] == "http://host.docker.internal:11434/v1"


def test_create_brain_ollama_no_double_v1(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    create_brain(
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434/v1",
        api_key="",
    )
    assert os.environ["OPENAI_BASE_URL"] == "http://localhost:11434/v1"


def test_create_brain_ollama_sets_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    create_brain(
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="sk-ollama-key",
    )
    assert os.environ["OPENAI_API_KEY"] == "sk-ollama-key"


def test_create_brain_ollama_no_api_key_uses_ollama(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    create_brain(
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
    )
    assert os.environ["OPENAI_API_KEY"] == "ollama"


def test_create_brain_openai_sets_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    agent = create_brain(
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
        model_name="gpt-4o",
        provider="openai",
        base_url="https://api.custom-openai.com/v1",
        api_key="sk-test-key",
    )
    assert os.environ["OPENAI_BASE_URL"] == "https://api.custom-openai.com/v1"


def test_create_brain_openai_no_base_url_when_empty(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    create_brain(
        model_name="gpt-4o",
        provider="openai",
        base_url="",
        api_key="sk-test-key",
    )
    assert "OPENAI_BASE_URL" not in os.environ


def test_create_brain_dynamic_system_prompt(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    agent = create_brain(
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
    )
    personality = Personality(
        name="TestBot",
        channel="telegram",
        description="A test agent",
        system_prompt="You are a helpful assistant.",
        traits=["helpful", "curious"],
    )
    ctx = MagicMock(spec=RunContext)
    ctx.deps = AgentDeps(
        agent_id="test",
        channel="telegram",
        personality=personality,
    )
    prompt_fn = agent._system_prompt_functions[0].function
    result = prompt_fn(ctx)
    assert "TestBot" in result
    assert "A test agent" in result
    assert "You are a helpful assistant." in result
    assert "curious" in result


def test_create_brain_env_vars_cleanup(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    create_brain(
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://my-ollama:11434",
        api_key="key123",
    )
    assert os.environ["OPENAI_BASE_URL"] == "http://my-ollama:11434/v1"
    assert os.environ["OPENAI_API_KEY"] == "key123"


def test_create_brain_registers_builtin_tools(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    agent = create_brain(
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
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    registry = MagicMock(spec=SkillRegistry)
    skill = _make_skill(name="weather_check", description="Checks weather")
    registry.list_skills.return_value = [skill]
    agent = create_brain(
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
        skill_registry=registry,
    )
    tool_names = list(agent._function_toolset.tools.keys())
    assert "weather_check" in tool_names


def test_create_brain_no_skill_registry_no_skill_tools(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    agent = create_brain(
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
    assert len(tool_names) == 10
    assert "build_skill" in tool_names
    assert "test_skill_code" in tool_names
    assert "review_skill_code" in tool_names
    assert "deploy_skill_code" in tool_names
    assert "schedule_task" in tool_names
    assert "unschedule_task" in tool_names


def test_create_brain_empty_skill_registry(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    registry = MagicMock(spec=SkillRegistry)
    registry.list_skills.return_value = []
    agent = create_brain(
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
        skill_registry=registry,
    )
    tool_names = list(agent._function_toolset.tools.keys())
    assert len(tool_names) == 10


def test_create_brain_multiple_skill_tools(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    registry = MagicMock(spec=SkillRegistry)
    skill1 = _make_skill(name="weather", description="Weather skill")
    skill2 = _make_skill(name="calculator", description="Calc skill")
    skill3 = _make_skill(name="translator", description="Translate skill")
    registry.list_skills.return_value = [skill1, skill2, skill3]
    agent = create_brain(
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
    assert len(tool_names) == 13


def test_create_brain_deps_type_is_agent_deps(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    agent = create_brain(
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
        memory.search = AsyncMock(
            return_value=[
                {"content": "I like tea", "similarity": 0.95},
                {"content": "I live in London", "similarity": 0.80},
            ]
        )
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
        council.search = AsyncMock(
            return_value=[
                {"content": "sky is blue", "contributing_agent": "puck", "message_type": "insight"},
                {
                    "content": "water is wet",
                    "contributing_agent": "oberon",
                    "message_type": "observation",
                },
            ]
        )
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
        council.write_entry = AsyncMock(
            return_value={"success": True, "error": None, "id": "abc-123"}
        )
        ctx = _make_ctx(council_memory=council, nats_bus=None)
        result = await share_to_council(
            ctx, "important finding", tags="idea, learning", message_type="insight"
        )
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
        council.write_entry = AsyncMock(
            return_value={"success": True, "error": None, "id": "abc-123"}
        )
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
        council.write_entry = AsyncMock(
            return_value={"success": True, "error": None, "id": "abc-123"}
        )
        nats = MagicMock()
        nats.publish_broadcast = AsyncMock()
        ctx = _make_ctx(council_memory=council, nats_bus=nats)
        result = await share_to_council(ctx, "shared finding", tags="idea", message_type="insight")
        nats.publish_broadcast.assert_awaited_once_with(
            "insight", {"content": "shared finding", "tags": ["idea"]}
        )
        assert result == "Shared to council: shared finding"

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    @patch("pillywiggins.config.Settings")
    async def test_returns_error_on_write_failure(self, mock_settings_cls, mock_embed):
        mock_settings_cls.return_value = MagicMock()
        mock_embed.return_value = [0.1, 0.2, 0.3]
        council = MagicMock()
        council.write_entry = AsyncMock(
            return_value={"success": False, "error": "Rate limit exceeded", "id": None}
        )
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
        council.write_entry = AsyncMock(
            return_value={"success": True, "error": None, "id": "abc-123"}
        )
        nats = MagicMock()
        nats.publish_broadcast = AsyncMock(side_effect=ConnectionError("NATS down"))
        ctx = _make_ctx(council_memory=council, nats_bus=nats)
        result = await share_to_council(ctx, "still works")
        assert result == "Shared to council: still works"


class TestShouldSandbox:
    @patch("pillywiggins.config.Settings")
    def test_returns_true_when_sandbox_all(self, mock_settings_cls):
        mock_settings = MagicMock()
        mock_settings.should_sandbox_all.return_value = True
        mock_settings_cls.return_value = mock_settings
        assert _should_sandbox("any_skill") is True

    @patch("pillywiggins.config.Settings")
    def test_returns_true_when_skill_in_sandbox_list(self, mock_settings_cls):
        mock_settings = MagicMock()
        mock_settings.should_sandbox_all.return_value = False
        mock_settings.get_sandbox_skill_names.return_value = {"dangerous_skill", "web_search"}
        mock_settings_cls.return_value = mock_settings
        assert _should_sandbox("web_search") is True

    @patch("pillywiggins.config.Settings")
    def test_returns_false_when_skill_not_in_list(self, mock_settings_cls):
        mock_settings = MagicMock()
        mock_settings.should_sandbox_all.return_value = False
        mock_settings.get_sandbox_skill_names.return_value = {"dangerous_skill"}
        mock_settings_cls.return_value = mock_settings
        assert _should_sandbox("safe_skill") is False


class TestRunSandboxedSkill:
    @pytest.mark.asyncio
    async def test_skill_no_file_path_returns_error(self):
        from pillywiggins.agents.brain import _run_sandboxed_skill

        skill = _make_skill(name="nofile")
        result = await _run_sandboxed_skill(skill, {})
        assert "no source file" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.sandbox.run_sandboxed", new_callable=AsyncMock)
    async def test_sandbox_failure_returns_error(self, mock_run_sandboxed):
        from pillywiggins.agents.brain import _run_sandboxed_skill

        mock_run_sandboxed.return_value = MagicMock(
            success=False, error="timeout exceeded", result=None
        )
        skill = _make_skill(name="fail_skill", file_path=Path("/some/path/fail_skill.py"))
        with patch.object(Path, "read_text", return_value="code"):
            result = await _run_sandboxed_skill(skill, {})
        assert "Sandbox error" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.sandbox.run_sandboxed", new_callable=AsyncMock)
    async def test_sandbox_success_with_string_result(self, mock_run_sandboxed):
        from pillywiggins.agents.brain import _run_sandboxed_skill

        mock_run_sandboxed.return_value = MagicMock(success=True, error=None, result="hello world")
        skill = _make_skill(name="str_skill", file_path=Path("/some/path/str_skill.py"))
        with patch.object(Path, "read_text", return_value="code"):
            result = await _run_sandboxed_skill(skill, {})
        assert result == "hello world"

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.sandbox.run_sandboxed", new_callable=AsyncMock)
    async def test_sandbox_success_with_dict_result(self, mock_run_sandboxed):
        from pillywiggins.agents.brain import _run_sandboxed_skill

        mock_run_sandboxed.return_value = MagicMock(
            success=True, error=None, result={"key": "value"}
        )
        skill = _make_skill(name="dict_skill", file_path=Path("/some/path/dict_skill.py"))
        with patch.object(Path, "read_text", return_value="code"):
            result = await _run_sandboxed_skill(skill, {})
        parsed = json.loads(result)
        assert parsed == {"key": "value"}


class TestMakeSkillTool:
    def test_generates_tool_with_name_and_doc(self):
        skill = _make_skill(
            name="weather",
            description="Get the weather for a city",
            meta={"parameters": {"city": {"type": "string", "description": "City name"}}},
        )
        tool_fn = _make_skill_tool(skill)
        assert tool_fn.__name__ == "weather"
        assert "weather" in tool_fn.__doc__
        assert "city" in tool_fn.__doc__

    def test_generates_tool_with_permissions_in_doc(self):
        skill = _make_skill(
            name="net_skill",
            description="Network skill",
            permissions={"network": True, "subprocess": False, "file_write": False},
        )
        tool_fn = _make_skill_tool(skill)
        assert "network" in tool_fn.__doc__

    def test_generates_tool_with_default_parameter_values(self):
        skill = _make_skill(
            name="param_skill",
            description="Skill with defaults",
            meta={
                "parameters": {
                    "count": {"type": "int", "description": "Number", "default": 5},
                },
            },
        )
        tool_fn = _make_skill_tool(skill)
        assert "default: 5" in tool_fn.__doc__

    @pytest.mark.asyncio
    async def test_skill_tool_calls_execute(self):
        run_func = AsyncMock(return_value="executed")
        skill = _make_skill(name="test_skill", description="test", run_func=run_func)
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        with patch("pillywiggins.agents.brain._should_sandbox", return_value=False):
            result = await tool_fn(ctx, query="hello")
        run_func.assert_awaited_once_with(query="hello")
        assert result == "executed"

    @pytest.mark.asyncio
    async def test_skill_tool_returns_json_for_non_string(self):
        run_func = AsyncMock(return_value={"key": "value"})
        skill = _make_skill(name="json_skill", description="json test", run_func=run_func)
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        with patch("pillywiggins.agents.brain._should_sandbox", return_value=False):
            result = await tool_fn(ctx)
        import json

        parsed = json.loads(result)
        assert parsed == {"key": "value"}

    @pytest.mark.asyncio
    async def test_skill_tool_type_error_returns_available_params(self):
        run_func = AsyncMock(side_effect=TypeError("unexpected keyword argument 'bad_param'"))
        skill = _make_skill(
            name="strict_skill",
            description="strict",
            run_func=run_func,
            meta={"parameters": {"valid_param": {"type": "string"}}},
        )
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        with patch("pillywiggins.agents.brain._should_sandbox", return_value=False):
            result = await tool_fn(ctx, bad_param="oops")
        assert "Error" in result
        assert "valid_param" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.agents.brain._should_sandbox", return_value=True)
    @patch("pillywiggins.agents.brain._run_sandboxed_skill", new_callable=AsyncMock)
    async def test_skill_tool_sandbox_path(self, mock_run_sandboxed, mock_should_sandbox):
        skill = _make_skill(name="dangerous", description="dangerous skill")
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        mock_run_sandboxed.return_value = "sandboxed result"
        result = await tool_fn(ctx)
        mock_run_sandboxed.assert_awaited_once_with(skill, {})
        assert result == "sandboxed result"


class TestBuildSkill:
    @pytest.mark.asyncio
    async def test_build_skill_success(self):
        code = 'SKILL_META = {"name": "hello", "description": "says hi"}\nasync def run(**kwargs): return "hello"'
        ctx = _make_ctx()
        result = await build_skill(ctx, name="hello", code=code)
        assert "Draft created" in result
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_build_skill_validation_failure(self):
        code = "print('no meta or run')"
        ctx = _make_ctx()
        result = await build_skill(ctx, name="bad_skill", code=code)
        assert "validation failed" in result.lower()

    @pytest.mark.asyncio
    async def test_build_skill_with_permissions(self):
        code = (
            'SKILL_META = {"name": "net_skill", "description": "network skill", '
            '"permissions": {"network": True, "subprocess": False, "file_write": False}}\n'
            "async def run(**kwargs): return 'net'"
        )
        ctx = _make_ctx()
        result = await build_skill(ctx, name="net_skill", code=code)
        assert "Permissions requested: network" in result

    @pytest.mark.asyncio
    async def test_build_skill_no_permissions(self):
        code = (
            'SKILL_META = {"name": "safe_skill", "description": "safe"}\n'
            "async def run(**kwargs): return 'safe'"
        )
        ctx = _make_ctx()
        result = await build_skill(ctx, name="safe_skill", code=code)
        assert "Permissions: none" in result


class TestTestSkillCode:
    @pytest.mark.asyncio
    async def test_invalid_json(self):
        ctx = _make_ctx()
        result = await run_skill_test(ctx, name="skill", code="pass", test_cases_json="not json")
        assert "Invalid test_cases_json" in result

    @pytest.mark.asyncio
    async def test_not_array(self):
        ctx = _make_ctx()
        result = await run_skill_test(
            ctx, name="skill", code="pass", test_cases_json='{"key": "val"}'
        )
        assert "must be a JSON array" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_code_validation_failure(self, mock_draft):
        mock_draft.side_effect = ValueError("Code must contain a SKILL_META dict assignment")
        ctx = _make_ctx()
        result = await run_skill_test(ctx, name="skill", code="bad code", test_cases_json="[]")
        assert "validation failed" in result.lower()

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.test_skill", new_callable=AsyncMock)
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_successful_test_results(self, mock_draft, mock_test):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(name="hello", code="code", meta={}, status=DraftStatus.TESTED)
        mock_draft.return_value = draft
        draft_with_results = SkillDraft(
            name="hello", code="code", meta={}, status=DraftStatus.TESTED
        )
        draft_with_results.test_results = [
            {
                "args": {},
                "expected": "hello",
                "passed": True,
                "actual": "hello",
                "error": None,
                "execution_time_ms": 10.0,
            },
            {
                "args": {},
                "expected": "world",
                "passed": False,
                "actual": "hello",
                "error": None,
                "execution_time_ms": 5.0,
            },
        ]
        mock_test.return_value = draft_with_results
        ctx = _make_ctx()
        result = await run_skill_test(
            ctx, name="hello", code="code", test_cases_json='[{"args": {}}]'
        )
        assert "1/2 passed" in result
        assert "PASS" in result
        assert "FAIL" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.test_skill", new_callable=AsyncMock)
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_test_results_with_error_and_no_expected(self, mock_draft, mock_test):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(name="fail", code="code", meta={}, status=DraftStatus.TESTED)
        mock_draft.return_value = draft
        draft_with_results = SkillDraft(
            name="fail", code="code", meta={}, status=DraftStatus.TESTED
        )
        draft_with_results.test_results = [
            {
                "args": {},
                "expected": None,
                "passed": False,
                "actual": None,
                "error": "crashed",
                "execution_time_ms": 1.0,
            },
        ]
        mock_test.return_value = draft_with_results
        ctx = _make_ctx()
        result = await run_skill_test(
            ctx, name="fail", code="code", test_cases_json='[{"args": {}}]'
        )
        assert "Error: crashed" in result


class TestReviewSkillCode:
    @pytest.mark.asyncio
    async def test_invalid_json(self):
        ctx = _make_ctx()
        result = await review_skill_code(ctx, name="skill", code="pass", test_cases_json="bad json")
        assert "Invalid test_cases_json" in result

    @pytest.mark.asyncio
    async def test_not_array(self):
        ctx = _make_ctx()
        result = await review_skill_code(ctx, name="skill", code="pass", test_cases_json='{"a": 1}')
        assert "must be a JSON array" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_code_validation_failure(self, mock_draft):
        mock_draft.side_effect = ValueError("Code must contain a SKILL_META dict assignment")
        ctx = _make_ctx()
        result = await review_skill_code(ctx, name="skill", code="bad", test_cases_json="[]")
        assert "validation failed" in result.lower()

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.review_skill")
    @patch("pillywiggins.skills.builder.test_skill", new_callable=AsyncMock)
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_successful_review(self, mock_draft, mock_test, mock_review):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(name="hello", code="code", meta={}, status=DraftStatus.TESTED)
        mock_draft.return_value = draft
        mock_test.return_value = draft
        mock_review.return_value = "=== Skill Review: hello ===\nApproved!"
        ctx = _make_ctx()
        result = await review_skill_code(ctx, name="hello", code="code", test_cases_json="[]")
        mock_review.assert_called_once_with(draft)


class TestDeploySkillCode:
    @pytest.mark.asyncio
    async def test_invalid_json(self):
        ctx = _make_ctx(skill_registry=MagicMock(spec=SkillRegistry))
        result = await deploy_skill_code(
            ctx, name="skill", code="pass", test_cases_json="bad", approved=True
        )
        assert "Invalid test_cases_json" in result

    @pytest.mark.asyncio
    async def test_not_array(self):
        ctx = _make_ctx(skill_registry=MagicMock(spec=SkillRegistry))
        result = await deploy_skill_code(
            ctx, name="skill", code="pass", test_cases_json='{"a":1}', approved=True
        )
        assert "must be a JSON array" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_code_validation_failure(self, mock_draft):
        mock_draft.side_effect = ValueError("Code must contain a SKILL_META dict assignment")
        ctx = _make_ctx(skill_registry=MagicMock(spec=SkillRegistry))
        result = await deploy_skill_code(
            ctx, name="skill", code="bad", test_cases_json="[]", approved=True
        )
        assert "validation failed" in result.lower()

    @pytest.mark.asyncio
    @patch("pillywiggins.config.Settings")
    @patch("pillywiggins.skills.builder.deploy_skill")
    @patch("pillywiggins.skills.builder.test_skill", new_callable=AsyncMock)
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_successful_deploy(self, mock_draft, mock_test, mock_deploy, mock_settings_cls):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(name="hello", code="code", meta={}, status=DraftStatus.TESTED)
        mock_draft.return_value = draft
        mock_test.return_value = draft
        mock_deploy.return_value = "Skill 'hello' deployed successfully."
        mock_settings_cls.return_value = MagicMock(skills_dir="/tmp/skills")
        registry = MagicMock(spec=SkillRegistry)
        ctx = _make_ctx(skill_registry=registry)
        result = await deploy_skill_code(
            ctx, name="hello", code="code", test_cases_json="[]", approved=True
        )
        mock_deploy.assert_called_once()


class TestScheduleTask:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_no_scheduler(self):
        ctx = _make_ctx(scheduler=None)
        result = await schedule_task(ctx, name="test", action="heartbeat")
        assert result == "Scheduler not available"

    @pytest.mark.asyncio
    async def test_schedules_interval_job(self):
        scheduler = MagicMock()
        scheduler.add_job = AsyncMock(return_value={"success": True, "name": "test"})
        ctx = _make_ctx(scheduler=scheduler)
        result = await schedule_task(ctx, name="test_job", action="heartbeat", interval_seconds=300)
        scheduler.add_job.assert_awaited_once()
        assert "Scheduled task" in result

    @pytest.mark.asyncio
    async def test_schedules_cron_job(self):
        scheduler = MagicMock()
        scheduler.add_job = AsyncMock(return_value={"success": True, "name": "cron_test"})
        ctx = _make_ctx(scheduler=scheduler)
        result = await schedule_task(
            ctx, name="cron_test", action="heartbeat", cron_expr="0 * * * *"
        )
        assert "Scheduled task" in result

    @pytest.mark.asyncio
    async def test_invalid_args_json(self):
        scheduler = MagicMock()
        scheduler.add_job = AsyncMock(return_value={"success": True, "name": "test"})
        ctx = _make_ctx(scheduler=scheduler)
        result = await schedule_task(ctx, name="test", action="send_message", args_json="not json")
        assert "Invalid args_json" in result

    @pytest.mark.asyncio
    async def test_valid_args_json(self):
        scheduler = MagicMock()
        scheduler.add_job = AsyncMock(return_value={"success": True, "name": "test"})
        ctx = _make_ctx(scheduler=scheduler)
        result = await schedule_task(
            ctx, name="test", action="send_message", args_json='{"conversation_key": "123"}'
        )
        scheduler.add_job.assert_awaited_once()
        call_kwargs = scheduler.add_job.call_args[1]
        assert call_kwargs["args"] == {"conversation_key": "123"}

    @pytest.mark.asyncio
    async def test_failed_schedule(self):
        scheduler = MagicMock()
        scheduler.add_job = AsyncMock(return_value={"success": False, "error": "job exists"})
        ctx = _make_ctx(scheduler=scheduler)
        result = await schedule_task(ctx, name="dup", action="heartbeat", interval_seconds=60)
        assert "Failed to schedule" in result


class TestUnscheduleTask:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_no_scheduler(self):
        ctx = _make_ctx(scheduler=None)
        result = await unschedule_task(ctx, name="test")
        assert result == "Scheduler not available"

    @pytest.mark.asyncio
    async def test_successful_removal(self):
        scheduler = MagicMock()
        scheduler.remove_job = AsyncMock(return_value=True)
        ctx = _make_ctx(scheduler=scheduler)
        result = await unschedule_task(ctx, name="test_job")
        assert "Unscheduled task" in result

    @pytest.mark.asyncio
    async def test_removal_not_found(self):
        scheduler = MagicMock()
        scheduler.remove_job = AsyncMock(return_value=False)
        ctx = _make_ctx(scheduler=scheduler)
        result = await unschedule_task(ctx, name="nonexistent")
        assert "not found" in result


class TestPersonalityPromptNone:
    def test_none_personality_returns_default(self, monkeypatch):
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        agent = create_brain(
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
        )
        ctx = MagicMock(spec=RunContext)
        ctx.deps = AgentDeps(
            agent_id="test",
            channel="telegram",
            personality=None,
        )
        prompt_fn = agent._system_prompt_functions[0].function
        result = prompt_fn(ctx)
        assert "helpful AI assistant" in result
