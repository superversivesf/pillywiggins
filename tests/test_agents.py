from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.agents.personality import Personality
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart


@pytest.fixture
def personality():
    return Personality(
        name="puck",
        channel="telegram",
        description="A mischievous test fairy",
        system_prompt="You are Puck.",
        traits=["playful"],
        scheduling={"interval": 60},
    )


@pytest.fixture
def agent(personality):
    with patch("pillywiggins.agents.base.create_brain") as mock_brain:
        mock_brain.return_value = MagicMock()
        ag = PillywigginAgent(
            agent_id="puck",
            personality=personality,
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
        )
    return ag


def test_agent_initialization(agent):
    assert agent.agent_id == "puck"
    assert agent._model_name == "qwen3.5:8b"
    assert agent._provider == "ollama"
    assert agent._base_url == "http://localhost:11434"
    assert agent._api_key == ""
    assert agent._message_history == []


def test_model_name_property(agent):
    assert agent.model_name == "qwen3.5:8b"


def test_switch_model_creates_new_brain(agent):
    with patch("pillywiggins.agents.base.create_brain") as mock_brain:
        mock_brain.return_value = MagicMock()
        agent.switch_model("llama3:8b")

    assert agent._model_name == "llama3:8b"
    assert agent.model_name == "llama3:8b"
    mock_brain.assert_called_once_with(
        agent.personality.system_prompt,
        "llama3:8b",
        "ollama",
        "http://localhost:11434",
        "",
    )


def test_switch_model_updates_brain_reference(agent):
    new_brain = MagicMock()
    with patch("pillywiggins.agents.base.create_brain", return_value=new_brain):
        agent.switch_model("llama3:8b")

    assert agent._brain is new_brain


def test_clear_history_empties_message_history(agent):
    agent._message_history = [MagicMock(), MagicMock()]
    assert len(agent._message_history) == 2

    agent.clear_history()

    assert agent._message_history == []


@pytest.mark.asyncio
async def test_handle_message_uses_brain(personality):
    mock_result = MagicMock()
    mock_result.output = "Hello from Puck!"
    mock_result.all_messages = MagicMock(return_value=[MagicMock()])

    mock_brain_instance = MagicMock()
    mock_brain_instance.run = AsyncMock(return_value=mock_result)

    with patch("pillywiggins.agents.base.create_brain", return_value=mock_brain_instance):
        agent = PillywigginAgent(
            agent_id="puck",
            personality=personality,
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
        )

    from pillywiggins.messaging.unified import ChannelType, UnifiedMessage

    msg = UnifiedMessage(
        channel=ChannelType.TELEGRAM,
        channel_user_id="123",
        content="Hello!",
        conversation_key="456",
    )

    result = await agent.handle_message(msg)

    assert result == "Hello from Puck!"
    mock_brain_instance.run.assert_called_once()
    assert len(agent._message_history) == 1


@pytest.mark.asyncio
async def test_handle_message_saves_to_cache(personality):
    mock_result = MagicMock()
    mock_result.output = "Cached response"
    mock_result.all_messages = MagicMock(return_value=[MagicMock()])

    mock_brain_instance = MagicMock()
    mock_brain_instance.run = AsyncMock(return_value=mock_result)

    mock_cache = AsyncMock()

    with patch("pillywiggins.agents.base.create_brain", return_value=mock_brain_instance):
        agent = PillywigginAgent(
            agent_id="puck",
            personality=personality,
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
            cache=mock_cache,
        )

    from pillywiggins.messaging.unified import ChannelType, UnifiedMessage

    msg = UnifiedMessage(
        channel=ChannelType.TELEGRAM,
        channel_user_id="123",
        content="Hello!",
        conversation_key="456",
    )

    await agent.handle_message(msg)

    mock_cache.save.assert_called_once()
    assert mock_cache.save.call_args[0][0] == "puck"


@pytest.mark.asyncio
async def test_load_history_from_cache(personality):
    mock_cache = AsyncMock()
    mock_messages = [MagicMock(), MagicMock()]
    mock_cache.load = AsyncMock(return_value=mock_messages)

    with patch("pillywiggins.agents.base.create_brain", return_value=MagicMock()):
        agent = PillywigginAgent(
            agent_id="puck",
            personality=personality,
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
            cache=mock_cache,
        )

    await agent.load_history()

    assert len(agent._message_history) == 2
    mock_cache.load.assert_called_once_with("puck")


@pytest.mark.asyncio
async def test_load_history_no_cache(personality):
    with patch("pillywiggins.agents.base.create_brain", return_value=MagicMock()):
        agent = PillywigginAgent(
            agent_id="puck",
            personality=personality,
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
        )

    await agent.load_history()

    assert agent._message_history == []


@pytest.mark.asyncio
async def test_handle_message_without_cache_does_not_error(personality):
    mock_result = MagicMock()
    mock_result.output = "No cache"
    mock_result.all_messages = MagicMock(return_value=[MagicMock()])

    mock_brain_instance = MagicMock()
    mock_brain_instance.run = AsyncMock(return_value=mock_result)

    with patch("pillywiggins.agents.base.create_brain", return_value=mock_brain_instance):
        agent = PillywigginAgent(
            agent_id="puck",
            personality=personality,
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
        )

    from pillywiggins.messaging.unified import ChannelType, UnifiedMessage

    msg = UnifiedMessage(
        channel=ChannelType.TELEGRAM,
        channel_user_id="123",
        content="Hello!",
        conversation_key="456",
    )

    result = await agent.handle_message(msg)

    assert result == "No cache"


def test_get_status_returns_fields(agent):
    agent._message_history = [MagicMock(), MagicMock(), MagicMock()]
    status = agent.get_status()
    assert "model_name" in status
    assert "message_count" in status
    assert "estimated_tokens" in status
    assert "agent_id" in status
    assert "channel" in status
    assert status["model_name"] == "qwen3.5:8b"
    assert status["message_count"] == 3
    assert status["agent_id"] == "puck"
    assert status["channel"] == "telegram"


@pytest.mark.asyncio
async def test_compact_history_summarizes_old_messages(personality):
    mock_result = MagicMock()
    mock_result.output = "This is a summary."
    mock_response = ModelResponse(parts=[TextPart(content="This is a summary.")])
    mock_result.all_messages = MagicMock(return_value=[
        ModelRequest(parts=[UserPromptPart(content="Summarize this conversation so far in 2-3 concise sentences.")]),
        mock_response,
    ])

    mock_brain_instance = MagicMock()
    mock_brain_instance.run = AsyncMock(return_value=mock_result)

    with patch("pillywiggins.agents.base.create_brain", return_value=mock_brain_instance):
        agent = PillywigginAgent(
            agent_id="puck",
            personality=personality,
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
            compact_keep_messages=2,
        )

    old_msg1 = ModelRequest(parts=[UserPromptPart(content="hello")])
    old_msg2 = ModelResponse(parts=[TextPart(content="hi")])
    kept_msg1 = ModelRequest(parts=[UserPromptPart(content="recent question")])
    kept_msg2 = ModelResponse(parts=[TextPart(content="recent answer")])
    agent._message_history = [old_msg1, old_msg2, kept_msg1, kept_msg2]

    result = await agent.compact_history()

    assert "Compacted 2 messages into summary" in result
    assert "Keeping 2 recent" in result
    assert len(agent._message_history) == 4
    assert isinstance(agent._message_history[0], ModelRequest)
    assert isinstance(agent._message_history[1], ModelResponse)


@pytest.mark.asyncio
async def test_compact_history_noop_when_few_messages(personality):
    with patch("pillywiggins.agents.base.create_brain", return_value=MagicMock()):
        agent = PillywigginAgent(
            agent_id="puck",
            personality=personality,
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
            compact_keep_messages=6,
        )

    agent._message_history = [MagicMock(), MagicMock()]
    result = await agent.compact_history()

    assert result == "Nothing to compact — only 2 messages."
    assert len(agent._message_history) == 2


@pytest.mark.asyncio
async def test_compact_history_truncates_long_messages(personality):
    mock_result = MagicMock()
    mock_result.output = "Summary."
    mock_response = ModelResponse(parts=[TextPart(content="Summary.")])
    mock_result.all_messages = MagicMock(return_value=[
        ModelRequest(parts=[UserPromptPart(content="Summarize this conversation so far in 2-3 concise sentences.")]),
        mock_response,
    ])

    mock_brain_instance = MagicMock()
    mock_brain_instance.run = AsyncMock(return_value=mock_result)

    with patch("pillywiggins.agents.base.create_brain", return_value=mock_brain_instance):
        agent = PillywigginAgent(
            agent_id="puck",
            personality=personality,
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
            compact_keep_messages=1,
            compact_truncate_message_chars=10,
        )

    long_text = "A" * 100
    old_msg = ModelRequest(parts=[UserPromptPart(content="old")])
    old_response = ModelResponse(parts=[TextPart(content="old reply")])
    kept_msg = ModelResponse(parts=[TextPart(content=long_text)])
    agent._message_history = [old_msg, old_response, kept_msg]

    result = await agent.compact_history()

    assert "Compacted" in result
    truncated_text = agent._message_history[-1].parts[0].content
    assert truncated_text.endswith("...[truncated]")
    assert len(truncated_text) == 10 + len("...[truncated]")