"""Tests for PillywigginAgent start/shutdown failure paths and internal handlers."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.agents.base import (
    PillywigginAgent,
    _builtin_send_message_handler,
    _builtin_heartbeat_handler,
    _ACTIVE_AGENTS,
)
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

    assert agent._council_memory is None
    assert "puck" in _ACTIVE_AGENTS


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

    assert agent._nats_bus is None


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
    assert agent._council_memory is None


@pytest.mark.asyncio
async def test_shutdown_nats_close_failure_does_not_crash(agent):
    """If nats_bus.close() raises, shutdown should complete."""
    bad_bus = AsyncMock()
    bad_bus.close = AsyncMock(side_effect=RuntimeError("nats gone"))
    agent._nats_bus = bad_bus
    await agent.shutdown()
    assert agent._nats_bus is None


@pytest.mark.asyncio
async def test_shutdown_scheduler_stop_failure_does_not_crash(agent):
    """If scheduler.stop() raises, shutdown should complete."""
    bad_sched = AsyncMock()
    bad_sched.stop = AsyncMock(side_effect=RuntimeError("sched gone"))
    agent._scheduler = bad_sched
    await agent.shutdown()
    assert agent._scheduler is None


@pytest.mark.asyncio
async def test_shutdown_removes_from_active_agents(agent):
    """shutdown() should remove the agent from _ACTIVE_AGENTS."""
    _ACTIVE_AGENTS["puck"] = agent
    await agent.shutdown()
    assert "puck" not in _ACTIVE_AGENTS


# ---------------------------------------------------------------------------
# _builtin_send_message_handler failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_handler_agent_not_found():
    """If agent is not in _ACTIVE_AGENTS, should log warning and return."""
    _ACTIVE_AGENTS.clear()
    with patch("pillywiggins.agents.base.logger.warning") as mock_warn:
        await _builtin_send_message_handler(agent_id="ghost")
    mock_warn.assert_called_once()
    assert "not found" in mock_warn.call_args[0][0]


@pytest.mark.asyncio
async def test_send_message_handler_missing_conversation_key(agent, personality):
    """If conversation_key is missing, should log warning and return."""
    _ACTIVE_AGENTS["puck"] = agent
    with patch("pillywiggins.agents.base.logger.warning") as mock_warn:
        await _builtin_send_message_handler(agent_id="puck", args={})
    mock_warn.assert_called_once()
    assert "missing conversation_key" in mock_warn.call_args[0][0]


@pytest.mark.asyncio
async def test_send_message_handler_no_adapter(agent, personality):
    """If adapter is None, should log warning and return."""
    _ACTIVE_AGENTS["puck"] = agent
    agent._adapter = None
    with patch("pillywiggins.agents.base.logger.warning") as mock_warn:
        await _builtin_send_message_handler(
            agent_id="puck", args={"conversation_key": "123", "chat_id": "123"}
        )
    mock_warn.assert_called_once()
    assert "no adapter" in mock_warn.call_args[0][0]


@pytest.mark.asyncio
async def test_send_message_handler_brain_error(agent, personality):
    """If brain.run() raises, should log exception."""
    _ACTIVE_AGENTS["puck"] = agent
    mock_adapter = MagicMock()
    mock_adapter.send = AsyncMock()
    agent._adapter = mock_adapter
    agent._brain.run = AsyncMock(side_effect=RuntimeError("brain boom"))

    with patch("pillywiggins.agents.base.logger.exception") as mock_exc:
        await _builtin_send_message_handler(
            agent_id="puck", args={"conversation_key": "123", "chat_id": "123", "prompt": "hi"}
        )
    mock_exc.assert_called_once()
    assert "send_message failed" in mock_exc.call_args[0][0]


# ---------------------------------------------------------------------------
# _builtin_heartbeat_handler failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_handler_agent_not_found():
    """If agent is not in _ACTIVE_AGENTS, should log and return."""
    _ACTIVE_AGENTS.clear()
    with patch("pillywiggins.agents.base.logger.info") as mock_info:
        await _builtin_heartbeat_handler(agent_id="ghost")
    mock_info.assert_called_once()
    assert "no NATS bus" in mock_info.call_args[0][0]


@pytest.mark.asyncio
async def test_heartbeat_handler_nats_bus_none(agent, personality):
    """If agent has no NATS bus, should log and return."""
    _ACTIVE_AGENTS["puck"] = agent
    agent._nats_bus = None
    with patch("pillywiggins.agents.base.logger.info") as mock_info:
        await _builtin_heartbeat_handler(agent_id="puck")
    mock_info.assert_called_once()
    assert "no NATS bus" in mock_info.call_args[0][0]


@pytest.mark.asyncio
async def test_heartbeat_handler_publish_failure(agent, personality):
    """If heartbeat publish raises, should log warning."""
    _ACTIVE_AGENTS["puck"] = agent
    mock_bus = AsyncMock()
    mock_bus.publish_broadcast = AsyncMock(side_effect=ConnectionError("nats broken"))
    agent._nats_bus = mock_bus
    with patch("pillywiggins.agents.base.logger.warning") as mock_warn:
        await _builtin_heartbeat_handler(agent_id="puck")
    mock_warn.assert_called_once()
    assert "Failed to broadcast heartbeat" in mock_warn.call_args[0][0]
