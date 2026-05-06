import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.messaging.unified import ChannelType, UnifiedMessage


@pytest.fixture
def nats_mocks(personality):
    handler_holder = []

    async def capture_handler(h):
        handler_holder.append(h)

    with (
        patch("pillywiggins.agents.base.create_brain", return_value=MagicMock()),
        patch("pillywiggins.agents.base.NatsBus") as mock_nats_cls,
        patch("pillywiggins.agents.base.AgentScheduler") as mock_sched_cls,
    ):
        mock_bus = AsyncMock()
        mock_bus.subscribe_broadcast = AsyncMock(side_effect=capture_handler)
        mock_bus.subscribe_direct = AsyncMock(side_effect=capture_handler)
        mock_nats_cls.return_value = mock_bus
        mock_sched_cls.return_value = MagicMock()
        agent = PillywigginAgent(
            agent_id="puck",
            personality=personality,
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
            nats_url="nats://localhost:4222",
        )
        yield agent, mock_bus, handler_holder


@pytest.mark.asyncio
async def test_start_subscribes_to_broadcast_and_direct(nats_mocks):
    agent, mock_bus, _ = nats_mocks
    await agent.start()
    mock_bus.subscribe_broadcast.assert_awaited_once()
    mock_bus.subscribe_direct.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_skips_subscriptions_when_no_nats_url(personality):
    with patch("pillywiggins.agents.base.create_brain", return_value=MagicMock()):
        agent = PillywigginAgent(
            agent_id="puck",
            personality=personality,
            model_name="qwen3.5:8b",
            provider="ollama",
            base_url="http://localhost:11434",
            api_key="",
        )
    await agent.start()
    assert agent._nats_bus is None


@pytest.mark.asyncio
async def test_nats_message_routes_to_process_message(nats_mocks):
    agent, _, handler_holder = nats_mocks
    with patch.object(agent, "handle_message", new=AsyncMock(return_value="ok")) as mock_handle:
        await agent.start()

        assert len(handler_holder) == 2
        handler = handler_holder[0]

        data = {
            "channel": "telegram",
            "channel_user_id": "123",
            "content": "Hello from NATS",
            "conversation_key": "456",
            "metadata": {"chat_id": "789"},
        }
        await handler("message", data)

        mock_handle.assert_awaited_once()
        msg = mock_handle.call_args[0][0]
        assert isinstance(msg, UnifiedMessage)
        assert msg.channel == ChannelType.TELEGRAM
        assert msg.content == "Hello from NATS"
        assert msg.conversation_key == "456"
        assert msg.metadata == {"chat_id": "789", "from_agent": "", "timestamp": ""}


@pytest.mark.asyncio
async def test_nats_message_defaults_to_telegram_channel(nats_mocks):
    agent, _, handler_holder = nats_mocks
    with patch.object(agent, "handle_message", new=AsyncMock(return_value="ok")) as mock_handle:
        await agent.start()

        handler = handler_holder[0]
        await handler(
            "message",
            {
                "content": "Hello",
                "conversation_key": "1",
                "channel_user_id": "u1",
            },
        )

        msg = mock_handle.call_args[0][0]
        assert msg.channel == ChannelType.TELEGRAM


@pytest.mark.asyncio
async def test_nats_insight_routes_to_council(nats_mocks):
    agent, _, handler_holder = nats_mocks
    mock_council = AsyncMock()
    agent._council_memory = mock_council
    await agent.start()

    handler = handler_holder[0]
    data = {"content": "New idea", "tags": ["idea"], "embedding": [0.1, 0.2]}
    await handler("insight", data, "mustardseed", "2025-01-01T00:00:00+00:00")

    mock_council.write_entry.assert_awaited_once_with(
        content="New idea",
        tags=["idea"],
        embedding=[0.1, 0.2],
        message_type="insight",
        confidence=1.0,
    )


@pytest.mark.asyncio
async def test_nats_insight_skipped_when_no_council(nats_mocks):
    agent, _, handler_holder = nats_mocks
    assert agent._council_memory is None
    await agent.start()

    handler = handler_holder[0]
    await handler("insight", {"content": "New idea", "tags": ["idea"], "embedding": [0.1]})

    # Should not raise


@pytest.mark.asyncio
async def test_nats_skill_published_routes_to_reload(nats_mocks):
    agent, _, handler_holder = nats_mocks
    mock_registry = MagicMock()
    agent._skill_registry = mock_registry
    await agent.start()

    handler = handler_holder[0]
    await handler("skill_published", {"skill": "web_search"})

    mock_registry.load_all.assert_called_once()


@pytest.mark.asyncio
async def test_nats_skill_deployed_routes_to_reload(nats_mocks):
    agent, _, handler_holder = nats_mocks
    mock_registry = MagicMock()
    agent._skill_registry = mock_registry
    await agent.start()

    handler = handler_holder[0]
    await handler("skill_deployed", {"skill_name": "web_search", "agent_id": "puck", "deployed_at": "2024-01-01T00:00:00+00:00"})

    mock_registry.load_all.assert_called_once()


@pytest.mark.asyncio
async def test_nats_skill_published_skipped_when_no_registry(nats_mocks):
    agent, _, handler_holder = nats_mocks
    assert agent._skill_registry is None
    await agent.start()

    handler = handler_holder[0]
    await handler("skill_published", {"skill": "web_search"})

    # Should not raise


@pytest.mark.asyncio
async def test_nats_skill_deployed_skipped_when_no_registry(nats_mocks):
    agent, _, handler_holder = nats_mocks
    assert agent._skill_registry is None
    await agent.start()

    handler = handler_holder[0]
    await handler("skill_deployed", {"skill_name": "web_search", "agent_id": "puck", "deployed_at": "2024-01-01T00:00:00+00:00"})

    # Should not raise


@pytest.mark.asyncio
async def test_nats_unknown_type_logs_warning(nats_mocks):
    agent, _, handler_holder = nats_mocks
    await agent.start()

    handler = handler_holder[0]
    with patch("pillywiggins.agents.base.logger.warning") as mock_warn:
        await handler("unknown_type", {"foo": "bar"})

    mock_warn.assert_called_once()
    assert "unknown NATS message type" in mock_warn.call_args[0][0]
    assert mock_warn.call_args[0][2] == "unknown_type"
