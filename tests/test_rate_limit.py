"""Tests for agent rate limiting."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.agents.base import PillywigginAgent


@pytest.fixture
def agent():
    with patch("pillywiggins.agents.base.create_brain") as mock_brain:
        mock_brain.return_value = MagicMock()
        ag = PillywigginAgent(
            agent_id="puck",
            personality=MagicMock(),
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
        )
    return ag


def test_rate_limit_defaults(agent):
    assert agent._llm_rate_limit == 10
    assert agent._llm_rate_window == 60.0
    assert agent._llm_call_timestamps == []


@pytest.mark.asyncio
async def test_handle_message_under_limit(agent):
    """Messages under the limit are processed normally."""
    mock_brain = MagicMock()
    mock_result = MagicMock()
    mock_result.output = "hello"
    mock_result.all_messages.return_value = []
    mock_brain.run = AsyncMock(return_value=mock_result)
    agent._brain = mock_brain

    from pillywiggins.messaging.unified import UnifiedMessage, ChannelType

    msg = UnifiedMessage(
        channel=ChannelType.TELEGRAM,
        channel_user_id="123",
        content="hi",
        conversation_key="456",
    )
    result = await agent.handle_message(msg)
    assert result == "hello"
    assert len(agent._llm_call_timestamps) == 1


@pytest.mark.asyncio
async def test_handle_message_at_limit(agent):
    """At limit, returns rate limit message."""
    import time

    # Fill timestamps to exactly the limit
    now = time.monotonic()
    agent._llm_call_timestamps = [now] * agent._llm_rate_limit

    from pillywiggins.messaging.unified import UnifiedMessage, ChannelType

    msg = UnifiedMessage(
        channel=ChannelType.TELEGRAM,
        channel_user_id="123",
        content="hi",
        conversation_key="456",
    )
    result = await agent.handle_message(msg)
    assert "processing a lot of messages" in result


@pytest.mark.asyncio
async def test_rate_limit_resets_after_window(agent):
    """After the window expires, calls are allowed again."""
    import time

    # Fill with old timestamps
    now = time.monotonic()
    agent._llm_call_timestamps = [now - 120] * agent._llm_rate_limit

    mock_brain = MagicMock()
    mock_result = MagicMock()
    mock_result.output = "hello"
    mock_result.all_messages.return_value = []
    mock_brain.run = AsyncMock(return_value=mock_result)
    agent._brain = mock_brain

    from pillywiggins.messaging.unified import UnifiedMessage, ChannelType

    msg = UnifiedMessage(
        channel=ChannelType.TELEGRAM,
        channel_user_id="123",
        content="hi",
        conversation_key="456",
    )
    result = await agent.handle_message(msg)
    assert result == "hello"


def test_check_rate_limit_returns_none_when_under(agent):
    """_check_rate_limit returns None when under limit."""
    assert agent._check_rate_limit() is None
    assert len(agent._llm_call_timestamps) == 1


def test_check_rate_limit_returns_message_when_over(agent):
    """_check_rate_limit returns error message when over limit."""
    import time

    now = time.monotonic()
    agent._llm_call_timestamps = [now] * agent._llm_rate_limit
    result = agent._check_rate_limit()
    assert result is not None
    assert "processing a lot of messages" in result
