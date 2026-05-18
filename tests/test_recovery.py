"""Tests for infrastructure failure recovery scenarios.

Covers: PostgreSQL (private memory) failures, Redis (conversation cache) failures,
NATS bus failures, Ollama inference failures, and multi-infrastructure failures.

Tests verify graceful degradation: agents should return error strings or
continue operating when infrastructure is unreachable.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic_ai import RunContext

from pillywiggins.agents.deps import AgentDeps
from pillywiggins.agents.tools import (
    save_to_private_memory,
    recall_private_memory,
    share_to_council,
)
from pillywiggins.messaging.unified import UnifiedMessage, ChannelType
from tests.helpers import make_ctx


# ---------------------------------------------------------------------------
# TestPrivateMemoryRecovery — PostgreSQL (pgvector) failure paths
# ---------------------------------------------------------------------------


class TestPrivateMemoryRecovery:
    """Tests for private memory tools when PostgreSQL is unreachable.

    NOTE: The current tool implementations do not catch exceptions from
    private_memory.save() or private_memory.search(). These tests document
    that gap by asserting the exception propagates. If graceful error
    handling is added to the tools, update these tests accordingly.
    """

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    async def test_save_propagates_error_on_connection_loss(self, mock_embed):
        """PrivateMemory.save() raises ConnectionError → exception propagates."""
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_pm = AsyncMock()
        mock_pm.save.side_effect = ConnectionError("database down")
        ctx = make_ctx(
            private_memory=mock_pm,
            llm_base_url="http://localhost:11434",
            embedding_model="nomic-embed-text",
            llm_provider="ollama",
        )
        with pytest.raises(ConnectionError, match="database down"):
            await save_to_private_memory(ctx, "test memory")
        mock_pm.save.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    async def test_recall_propagates_error_on_connection_loss(self, mock_embed):
        """PrivateMemory.search() raises ConnectionError → exception propagates."""
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_pm = AsyncMock()
        mock_pm.search.side_effect = ConnectionError("database down")
        ctx = make_ctx(
            private_memory=mock_pm,
            llm_base_url="http://localhost:11434",
            embedding_model="nomic-embed-text",
            llm_provider="ollama",
        )
        with pytest.raises(ConnectionError, match="database down"):
            await recall_private_memory(ctx, "query")
        mock_pm.search.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    async def test_save_returns_error_when_save_returns_falsy(self, mock_embed):
        """PrivateMemory.save() returns False → tool returns error string."""
        mock_embed.return_value = [0.1, 0.2, 0.3]
        mock_pm = AsyncMock()
        mock_pm.save.return_value = False
        ctx = make_ctx(
            private_memory=mock_pm,
            llm_base_url="http://localhost:11434",
            embedding_model="nomic-embed-text",
            llm_provider="ollama",
        )
        result = await save_to_private_memory(ctx, "test memory")
        assert isinstance(result, str)
        assert "failed" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# TestNatsBusRecovery — NATS failure paths
# ---------------------------------------------------------------------------


class TestNatsBusRecovery:
    """Tests for council sharing when NATS is unreachable.

    share_to_council already catches NATS publish failures silently,
    so the function continues to return a success string even when
    NATS is down.
    """

    @pytest.mark.asyncio
    @patch("pillywiggins.memory.embeddings.embed")
    async def test_share_to_council_continues_on_nats_publish_failure(self, mock_embed):
        """share_to_council returns success when NATS publish fails."""
        mock_embed.return_value = [0.1, 0.2, 0.3]

        mock_nats = AsyncMock()
        mock_nats.publish_broadcast.side_effect = ConnectionError("nats down")

        mock_council = MagicMock()
        mock_council.write_entry = AsyncMock(return_value={"success": True})

        ctx = make_ctx(
            nats_bus=mock_nats,
            council_memory=mock_council,
            llm_base_url="http://localhost:11434",
            embedding_model="nomic-embed-text",
            llm_provider="ollama",
        )
        result = await share_to_council(ctx, "test share")
        # Should still return success — NATS failure is silently ignored
        assert isinstance(result, str)
        assert "Shared to council" in result

    @pytest.mark.asyncio
    async def test_share_to_council_returns_unavailable_when_council_none(self):
        """share_to_council returns error string when council_memory is None."""
        ctx = make_ctx(council_memory=None)
        result = await share_to_council(ctx, "test")
        assert isinstance(result, str)
        assert result == "Council memory is not available."


# ---------------------------------------------------------------------------
# TestConversationCacheRecovery — Redis failure paths
# ---------------------------------------------------------------------------


class TestConversationCacheRecovery:
    """Tests for agent operation when ConversationCache (Redis) is unreachable.

    ConversationCache.save() and .load() already handle their own connection
    failures internally (return None, log warnings). These tests verify the
    agent can still process messages when cache operations fail.
    """

    @pytest.mark.asyncio
    async def test_agent_handles_message_with_cache_load_failure(
        self, personality, settings
    ):
        """Agent processes message even when ConversationCache.load() returns None."""
        with patch("pillywiggins.agents.base.create_brain") as mock_create_brain:
            mock_brain = MagicMock()
            mock_brain.run = AsyncMock(
                return_value=_make_run_result("Hello!")
            )
            mock_create_brain.return_value = mock_brain

            with patch("pillywiggins.agents.base.ConversationCache") as mock_cache_cls:
                mock_cache = AsyncMock()
                mock_cache.load.return_value = None  # Simulates Redis being down
                mock_cache_cls.return_value = mock_cache

                with patch("pillywiggins.agents.base.NatsBus") as mock_nats:
                    mock_bus = AsyncMock()
                    mock_bus.connect_or_log = AsyncMock(return_value=False)
                    mock_nats.return_value = mock_bus

                    with patch("pillywiggins.agents.base.CouncilMemory") as mock_cm:
                        mock_cm.return_value = MagicMock()

                        with patch("pillywiggins.agents.base.AgentScheduler") as mock_sched:
                            mock_sched.return_value.start = AsyncMock()

                            from pillywiggins.agents.base import PillywigginAgent

                            agent = PillywigginAgent(
                                agent_id="test-agent",
                                personality=personality,
                                model_name="qwen3.5:8b",
                                provider="ollama",
                                base_url="http://localhost:11434",
                                api_key="",
                                database_url=settings.database_url,
                                nats_url=settings.nats_url,
                            )
                            # Replace brain with our controlled mock
                            agent._brain = mock_brain
                            agent._store = None  # Don't try to persist to DB

                            await agent.start()

                            msg = UnifiedMessage(
                                channel=ChannelType.TELEGRAM,
                                content="Hello",
                                conversation_key="test",
                                channel_user_id="user1",
                            )
                            response = await agent.handle_message(msg)
                            assert response is not None
                            assert isinstance(response, str)

    @pytest.mark.asyncio
    async def test_agent_handles_message_with_cache_save_failure(
        self, personality, settings
    ):
        """Agent processes message even when ConversationCache.save() raises."""
        with patch("pillywiggins.agents.base.create_brain") as mock_create_brain:
            mock_brain = MagicMock()
            mock_brain.run = AsyncMock(
                return_value=_make_run_result("Hello!")
            )
            mock_create_brain.return_value = mock_brain

            with patch("pillywiggins.agents.base.ConversationCache") as mock_cache_cls:
                mock_cache = AsyncMock()
                mock_cache.load.return_value = None
                mock_cache.save = AsyncMock(
                    side_effect=ConnectionError("redis down")
                )
                mock_cache_cls.return_value = mock_cache

                with patch("pillywiggins.agents.base.NatsBus") as mock_nats:
                    mock_bus = AsyncMock()
                    mock_bus.connect_or_log = AsyncMock(return_value=False)
                    mock_nats.return_value = mock_bus

                    with patch("pillywiggins.agents.base.CouncilMemory") as mock_cm:
                        mock_cm.return_value = MagicMock()

                        with patch("pillywiggins.agents.base.AgentScheduler") as mock_sched:
                            mock_sched.return_value.start = AsyncMock()

                            from pillywiggins.agents.base import PillywigginAgent

                            agent = PillywigginAgent(
                                agent_id="test-agent",
                                personality=personality,
                                model_name="qwen3.5:8b",
                                provider="ollama",
                                base_url="http://localhost:11434",
                                api_key="",
                                database_url=settings.database_url,
                                nats_url=settings.nats_url,
                            )
                            agent._brain = mock_brain
                            agent._store = None

                            await agent.start()

                            msg = UnifiedMessage(
                                channel=ChannelType.TELEGRAM,
                                content="Hello",
                                conversation_key="test",
                                channel_user_id="user1",
                            )
                            response = await agent.handle_message(msg)
                            assert response is not None
                            assert isinstance(response, str)


# ---------------------------------------------------------------------------
# TestInferenceRecovery — Ollama (brain) failure paths
# ---------------------------------------------------------------------------


class TestInferenceRecovery:
    """Tests for agent operation when inference (brain.run) fails."""

    @pytest.mark.asyncio
    async def test_agent_raises_on_brain_timeout(self, personality):
        """Agent.handle_message raises TimeoutError when brain inference times out."""
        with patch("pillywiggins.agents.base.create_brain") as mock_create_brain:
            mock_brain = MagicMock()
            mock_brain.run = AsyncMock(
                side_effect=TimeoutError("inference timeout")
            )
            mock_create_brain.return_value = mock_brain

            with patch("pillywiggins.agents.base.NatsBus") as mock_nats:
                mock_bus = AsyncMock()
                mock_bus.connect_or_log = AsyncMock(return_value=False)
                mock_nats.return_value = mock_bus

                with patch("pillywiggins.agents.base.CouncilMemory") as mock_cm:
                    mock_cm.return_value = MagicMock()

                    with patch("pillywiggins.agents.base.AgentScheduler") as mock_sched:
                        mock_sched.return_value.start = AsyncMock()

                        from pillywiggins.agents.base import PillywigginAgent

                        agent = PillywigginAgent(
                            agent_id="test-agent",
                            personality=personality,
                            model_name="qwen3.5:8b",
                            provider="ollama",
                            base_url="http://localhost:11434",
                            api_key="",
                        )
                        agent._brain = mock_brain
                        agent._store = None

                        msg = UnifiedMessage(
                            channel=ChannelType.TELEGRAM,
                            content="Hello",
                            conversation_key="test",
                            channel_user_id="user1",
                        )
                        with pytest.raises(TimeoutError, match="inference timeout"):
                            await agent.handle_message(msg)

    @pytest.mark.asyncio
    async def test_agent_raises_on_brain_runtime_error(self, personality):
        """Agent.handle_message raises RuntimeError if brain crashes."""
        with patch("pillywiggins.agents.base.create_brain") as mock_create_brain:
            mock_brain = MagicMock()
            mock_brain.run = AsyncMock(
                side_effect=RuntimeError("brain crash")
            )
            mock_create_brain.return_value = mock_brain

            with patch("pillywiggins.agents.base.NatsBus") as mock_nats:
                mock_bus = AsyncMock()
                mock_bus.connect_or_log = AsyncMock(return_value=False)
                mock_nats.return_value = mock_bus

                with patch("pillywiggins.agents.base.CouncilMemory") as mock_cm:
                    mock_cm.return_value = MagicMock()

                    with patch("pillywiggins.agents.base.AgentScheduler") as mock_sched:
                        mock_sched.return_value.start = AsyncMock()

                        from pillywiggins.agents.base import PillywigginAgent

                        agent = PillywigginAgent(
                            agent_id="test-agent",
                            personality=personality,
                            model_name="qwen3.5:8b",
                            provider="ollama",
                            base_url="http://localhost:11434",
                            api_key="",
                        )
                        agent._brain = mock_brain
                        agent._store = None

                        msg = UnifiedMessage(
                            channel=ChannelType.TELEGRAM,
                            content="Hello",
                            conversation_key="test",
                            channel_user_id="user1",
                        )
                        with pytest.raises(RuntimeError, match="brain crash"):
                            await agent.handle_message(msg)


# ---------------------------------------------------------------------------
# TestMultiFailureRecovery — all infrastructure down simultaneously
# ---------------------------------------------------------------------------


class TestMultiFailureRecovery:
    """Tests for agent operation when ALL infrastructure is unreachable.

    The agent should still handle messages if the brain itself works,
    returning responses even when cache, NATS, and council memory
    are all failing.
    """

    @pytest.mark.asyncio
    async def test_agent_survives_all_infra_down(self, personality):
        """Agent handles message when Redis, NATS, and CouncilMemory are all down."""
        with patch("pillywiggins.agents.base.create_brain") as mock_create_brain:
            mock_brain = MagicMock()
            mock_brain.run = AsyncMock(
                return_value=_make_run_result("Still alive!")
            )
            mock_create_brain.return_value = mock_brain

            with patch("pillywiggins.agents.base.ConversationCache") as mock_cache_cls:
                mock_cache = AsyncMock()
                mock_cache.load.return_value = None
                mock_cache.save = AsyncMock(
                    side_effect=ConnectionError("redis down")
                )
                mock_cache_cls.return_value = mock_cache

                with patch("pillywiggins.agents.base.NatsBus") as mock_nats:
                    mock_bus = AsyncMock()
                    mock_bus.connect_or_log = AsyncMock(return_value=False)
                    mock_bus.publish_broadcast = AsyncMock(
                        side_effect=ConnectionError("nats down")
                    )
                    mock_nats.return_value = mock_bus

                    with patch("pillywiggins.agents.base.CouncilMemory") as mock_cm:
                        mock_council = MagicMock()
                        mock_council.connect = AsyncMock(
                            side_effect=ConnectionError("db down")
                        )
                        mock_cm.return_value = mock_council

                        with patch("pillywiggins.agents.base.AgentScheduler") as mock_sched:
                            mock_scheduler = AsyncMock()
                            mock_scheduler.start.side_effect = (
                                RuntimeError("redis down")
                            )
                            mock_sched.return_value = mock_scheduler

                            from pillywiggins.agents.base import PillywigginAgent

                            agent = PillywigginAgent(
                                agent_id="test-agent",
                                personality=personality,
                                model_name="qwen3.5:8b",
                                provider="ollama",
                                base_url="http://localhost:11434",
                                api_key="",
                            )
                            agent._brain = mock_brain
                            agent._store = None

                            await agent.start()

                            msg = UnifiedMessage(
                                channel=ChannelType.TELEGRAM,
                                content="Hello?",
                                conversation_key="test",
                                channel_user_id="user1",
                            )
                            response = await agent.handle_message(msg)
                            assert response is not None
                            assert isinstance(response, str)
                            assert response == "Still alive!"


# ---------------------------------------------------------------------------
# TestStartupRecovery — infrastructure failures during agent.start()
# ---------------------------------------------------------------------------


class TestStartupRecovery:
    """Tests that agent.start() gracefully handles infrastructure failures.

    The agent should continue to start even when individual services
    (CouncilMemory, NATS, scheduler) fail to connect.
    """

    @pytest.mark.asyncio
    async def test_start_continues_after_council_memory_failure(self, personality):
        """start() continues when CouncilMemory.connect() raises."""
        with patch("pillywiggins.agents.base.create_brain") as mock_create_brain:
            mock_create_brain.return_value = MagicMock()

            with patch("pillywiggins.agents.base.CouncilMemory") as mock_cm:
                mock_cm.return_value.connect = AsyncMock(
                    side_effect=ConnectionError("db down")
                )

                with patch("pillywiggins.agents.base.NatsBus") as mock_nats:
                    mock_bus = AsyncMock()
                    mock_bus.connect_or_log = AsyncMock(return_value=False)
                    mock_nats.return_value = mock_bus

                    with patch("pillywiggins.agents.base.AgentScheduler") as mock_sched:
                        mock_sched.return_value.start = AsyncMock()

                        from pillywiggins.agents.base import PillywigginAgent

                        agent = PillywigginAgent(
                            agent_id="test-agent",
                            personality=personality,
                            model_name="qwen3.5:8b",
                            provider="ollama",
                            base_url="http://localhost:11434",
                            api_key="",
                        )
                        await agent.start()
                        # Council memory should remain None after failed connect
                        assert agent._council_memory is None

    @pytest.mark.asyncio
    async def test_start_continues_after_nats_failure(self, personality):
        """start() continues when NATS connect_or_log returns False."""
        with patch("pillywiggins.agents.base.create_brain") as mock_create_brain:
            mock_create_brain.return_value = MagicMock()

            with patch("pillywiggins.agents.base.CouncilMemory") as mock_cm:
                mock_cm.return_value = MagicMock()

                with patch("pillywiggins.agents.base.NatsBus") as mock_nats:
                    mock_bus = AsyncMock()
                    mock_bus.connect_or_log = AsyncMock(return_value=False)
                    mock_nats.return_value = mock_bus

                    with patch("pillywiggins.agents.base.AgentScheduler") as mock_sched:
                        mock_sched.return_value.start = AsyncMock()

                        from pillywiggins.agents.base import PillywigginAgent

                        agent = PillywigginAgent(
                            agent_id="test-agent",
                            personality=personality,
                            model_name="qwen3.5:8b",
                            provider="ollama",
                            base_url="http://localhost:11434",
                            api_key="",
                        )
                        await agent.start()
                        # NATS bus should remain None after failed connect
                        assert agent._nats_bus is None

    @pytest.mark.asyncio
    async def test_start_continues_after_scheduler_failure(self, personality):
        """start() continues when scheduler.start() raises."""
        with patch("pillywiggins.agents.base.create_brain") as mock_create_brain:
            mock_create_brain.return_value = MagicMock()

            with patch("pillywiggins.agents.base.CouncilMemory") as mock_cm:
                mock_cm.return_value = MagicMock()

                with patch("pillywiggins.agents.base.NatsBus") as mock_nats:
                    mock_bus = AsyncMock()
                    mock_bus.connect_or_log = AsyncMock(return_value=False)
                    mock_nats.return_value = mock_bus

                    with patch("pillywiggins.agents.base.AgentScheduler") as mock_sched:
                        mock_sched.return_value.start = AsyncMock(
                            side_effect=RuntimeError("redis down")
                        )

                        from pillywiggins.agents.base import PillywigginAgent

                        agent = PillywigginAgent(
                            agent_id="test-agent",
                            personality=personality,
                            model_name="qwen3.5:8b",
                            provider="ollama",
                            base_url="http://localhost:11434",
                            api_key="",
                        )
                        await agent.start()
                        # Scheduler should be None after failed start
                        assert agent._scheduler is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_result(output: str) -> MagicMock:
    """Create a mock brain.run() return value with .output and .all_messages()."""
    result = MagicMock()
    result.output = output
    result.all_messages.return_value = []
    return result
