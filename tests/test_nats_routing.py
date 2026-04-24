import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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
    with patch("pillywiggins.agents.base.create_brain", return_value=MagicMock()):
        ag = PillywigginAgent(
            agent_id="puck",
            personality=personality,
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
        )
    return ag


@pytest.mark.asyncio
async def test_insight_routes_to_council_memory(agent):
    mock_council = AsyncMock()
    agent._council_memory = mock_council

    await agent._on_nats_message(
        "insight",
        {
            "content": "Teams should document their schemas",
            "tags": ["idea"],
            "embedding": [0.1, 0.2, 0.3],
        },
    )

    mock_council.write_entry.assert_awaited_once_with(
        content="Teams should document their schemas",
        tags=["idea"],
        embedding=[0.1, 0.2, 0.3],
        message_type="insight",
        confidence=1.0,
    )


@pytest.mark.asyncio
async def test_insight_routing_defaults(agent):
    mock_council = AsyncMock()
    agent._council_memory = mock_council

    await agent._on_nats_message("insight", {})

    mock_council.write_entry.assert_awaited_once_with(
        content="",
        tags=[],
        embedding=[],
        message_type="insight",
        confidence=1.0,
    )


@pytest.mark.asyncio
async def test_insight_skipped_when_no_council_memory(agent):
    assert agent._council_memory is None

    # Should not raise even though _council_memory is None
    await agent._on_nats_message(
        "insight",
        {"content": "something", "tags": [], "embedding": []},
    )


@pytest.mark.asyncio
async def test_skill_deployed_routes_to_skill_registry(agent):
    mock_registry = MagicMock()
    agent._skill_registry = mock_registry

    await agent._on_nats_message("skill_deployed", {"skill": "web_search"})

    mock_registry.load_all.assert_called_once()


@pytest.mark.asyncio
async def test_skill_deployed_skipped_when_no_registry(agent):
    assert agent._skill_registry is None

    # Should not raise even though _skill_registry is None
    await agent._on_nats_message("skill_deployed", {"skill": "web_search"})


@pytest.mark.asyncio
async def test_message_routes_to_process_message(agent):
    with patch.object(agent, "handle_message", new=AsyncMock(return_value="ok")) as mock_handle:
        await agent._on_nats_message(
            "message",
            {
                "channel": "telegram",
                "channel_user_id": "123",
                "content": "Hello from NATS",
                "conversation_key": "456",
                "metadata": {"chat_id": "789"},
            },
        )

    mock_handle.assert_awaited_once()
    msg = mock_handle.call_args[0][0]
    assert msg.content == "Hello from NATS"
    assert msg.conversation_key == "456"


@pytest.mark.asyncio
async def test_unknown_message_type_logs_warning(agent):
    with patch("pillywiggins.agents.base.logger.warning") as mock_warn:
        await agent._on_nats_message("unknown_type", {"foo": "bar"})

    mock_warn.assert_called_once()
    assert "Unknown NATS message type" in mock_warn.call_args[0][0]
    assert mock_warn.call_args[0][1] == "unknown_type"
