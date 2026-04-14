from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.agents.personality import Personality


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