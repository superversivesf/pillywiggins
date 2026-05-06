"""Tests for PillywigginAgent start/shutdown failure paths and internal handlers."""
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
            database_url="postgresql://test:5432/db",
            nats_url="nats://localhost:4222",
        )
    return ag


# ---------------------------------------------------------------------------
# start() failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_council_memory_failure_does_not_crash(agent, personality):
    """If CouncilMemory.connect() raises, start() should continue."""
    with patch("pillywiggins.agents.base.CouncilMemory") as mock_cls:
        mock_mem = AsyncMock()
        mock_mem.connect = AsyncMock(side_effect=ConnectionError("db down"))
        mock_cls.return_value = mock_mem

        # Mock scheduler so we don't need redis
        with patch("pillywiggins.agents.base.AgentScheduler") as mock_sched:
            mock_sched.return_value.start = AsyncMock()
            await agent.start()

    assert not agent.has_council_memory


@pytest.mark.asyncio
async def test_start_nats_failure_does_not_crash(agent, personality):
    """If NATS connect fails, start() should continue."""
    with patch("pillywiggins.agents.base.CouncilMemory") as mock_cls:
        mock_mem = AsyncMock()
        mock_cls.return_value = mock_mem
        with patch("pillywiggins.agents.base.NatsBus") as mock_nats:
            mock_bus = AsyncMock()
            mock_bus.connect_or_log = AsyncMock(return_value=False)
            mock_nats.return_value = mock_bus
            with patch("pillywiggins.agents.base.AgentScheduler") as mock_sched:
                mock_sched.return_value.start = AsyncMock()
                await agent.start()

    assert not agent.has_nats_bus


@pytest.mark.asyncio
async def test_start_scheduler_failure_does_not_crash(agent, personality):
    """If scheduler start() raises, agent should still be usable."""
    with patch("pillywiggins.agents.base.CouncilMemory") as mock_cls:
        mock_mem = AsyncMock()
        mock_cls.return_value = mock_mem
        with patch("pillywiggins.agents.base.AgentScheduler") as mock_sched:
            mock_sched.return_value.start = AsyncMock(side_effect=RuntimeError("redis down"))
            await agent.start()

    assert agent._scheduler is None


# ---------------------------------------------------------------------------
# shutdown() failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_council_close_failure_does_not_crash(agent):
    """If council_memory.close() raises, shutdown should complete."""
    bad_mem = AsyncMock()
    bad_mem.close = AsyncMock(side_effect=ConnectionError("db gone"))
    agent._council_memory = bad_mem
    await agent.shutdown()
    assert not agent.has_council_memory


@pytest.mark.asyncio
async def test_shutdown_nats_close_failure_does_not_crash(agent):
    """If nats_bus.close() raises, shutdown should complete."""
    bad_bus = AsyncMock()
    bad_bus.close = AsyncMock(side_effect=RuntimeError("nats gone"))
    agent._nats_bus = bad_bus
    await agent.shutdown()
    assert not agent.has_nats_bus


@pytest.mark.asyncio
async def test_shutdown_scheduler_stop_failure_does_not_crash(agent):
    """If scheduler.stop() raises, shutdown should complete."""
    bad_sched = AsyncMock()
    bad_sched.stop = AsyncMock(side_effect=RuntimeError("sched gone"))
    agent._scheduler = bad_sched
    await agent.shutdown()
    assert agent._scheduler is None


# ---------------------------------------------------------------------------
# _builtin_send_message_handler failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_handler_missing_conversation_key(agent, personality):
    """If conversation_key is missing, should log warning and return."""
    with patch("pillywiggins.agents.base.logger.warning") as mock_warn:
        await agent._builtin_send_message_handler(args={})
    mock_warn.assert_called_once()
    assert "missing conversation_key" in mock_warn.call_args[0][0]


@pytest.mark.asyncio
async def test_send_message_handler_no_adapter(agent, personality):
    """If adapter is None, should log warning and return."""
    agent._adapter = None
    with patch("pillywiggins.agents.base.logger.warning") as mock_warn:
        await agent._builtin_send_message_handler(args={"conversation_key": "123", "chat_id": "123"})
    mock_warn.assert_called_once()
    assert "no adapter" in mock_warn.call_args[0][0]


@pytest.mark.asyncio
async def test_send_message_handler_brain_error(agent, personality):
    """If brain.run() raises, should log exception."""
    mock_adapter = MagicMock()
    mock_adapter.send = AsyncMock()
    agent._adapter = mock_adapter
    agent._brain.run = AsyncMock(side_effect=RuntimeError("brain boom"))

    with patch("pillywiggins.agents.base.logger.exception") as mock_exc:
        await agent._builtin_send_message_handler(
            args={"conversation_key": "123", "chat_id": "123", "prompt": "hi"}
        )
    mock_exc.assert_called_once()
    assert "send_message failed" in mock_exc.call_args[0][0]


# ---------------------------------------------------------------------------
# _builtin_heartbeat_handler failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_handler_nats_bus_none(agent, personality):
    """If agent has no NATS bus, should log and return."""
    agent._nats_bus = None
    with patch("pillywiggins.agents.base.logger.info") as mock_info:
        await agent._builtin_heartbeat_handler()
    mock_info.assert_called_once()
    assert "no NATS bus" in mock_info.call_args[0][0]


@pytest.mark.asyncio
async def test_heartbeat_handler_publish_failure(agent, personality):
    """If heartbeat publish raises, should log warning."""
    mock_bus = AsyncMock()
    mock_bus.publish_broadcast = AsyncMock(side_effect=ConnectionError("nats broken"))
    agent._nats_bus = mock_bus
    with patch("pillywiggins.agents.base.logger.warning") as mock_warn:
        await agent._builtin_heartbeat_handler()
    mock_warn.assert_called_once()
    assert "Failed to broadcast heartbeat" in mock_warn.call_args[0][0]