import pytest
from unittest.mock import AsyncMock, MagicMock

from pillywiggins.agents.brain import (
    create_brain,
    send_message_to_agent,
)
from pillywiggins.agents.deps import AgentDeps
from pydantic_ai import RunContext


def _make_ctx(agent_id="puck", channel="telegram", nats_bus=None):
    ctx = MagicMock(spec=RunContext)
    ctx.deps = AgentDeps(
        agent_id=agent_id,
        channel=channel,
        nats_bus=nats_bus,
    )
    return ctx


class TestSendMessageToAgent:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_nats_bus_none(self):
        ctx = _make_ctx(nats_bus=None)
        result = await send_message_to_agent(ctx, target_agent_id="oberon", message="hello")
        assert result == "NATS bus is not available."

    @pytest.mark.asyncio
    async def test_publishes_correct_message(self):
        nats = MagicMock()
        nats.publish_direct = AsyncMock()
        ctx = _make_ctx(agent_id="puck", nats_bus=nats)
        result = await send_message_to_agent(ctx, target_agent_id="oberon", message="hello there")
        nats.publish_direct.assert_awaited_once()
        call_kwargs = nats.publish_direct.call_args[1]
        assert call_kwargs["target_agent_id"] == "oberon"
        assert call_kwargs["message_type"] == "message"
        data = call_kwargs["data"]
        assert data["content"] == "hello there"
        assert data["channel_user_id"] == "puck"
        assert data["metadata"] == {"from": "puck"}
        assert data["conversation_key"] == ""
        assert result == "Sent message to oberon"


def test_create_brain_registers_send_message_to_agent(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    agent = create_brain(
        model_name="qwen3.5:8b",
        provider="ollama",
        base_url="http://localhost:11434",
        api_key="",
    )
    tool_names = list(agent._function_toolset.tools.keys())
    assert "send_message_to_agent" in tool_names
