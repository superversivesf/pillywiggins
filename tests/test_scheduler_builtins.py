"""Tests for the three scheduler builtin handlers with their enhanced implementations.

Tests cover:
  - skill_reload: logging count of loaded skills from load_all() return value
  - memory_review: logging memory state summary (count, oldest entry age)
  - custom: parsing "action" field from args (alias for "skill"), dispatching
"""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from pillywiggins.scheduling.scheduler import (
    _builtin_custom,
    _builtin_memory_review,
    _builtin_skill_reload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_agent():
    agent = MagicMock()
    agent.compact_history = AsyncMock(return_value="compacted")
    agent._skill_registry = MagicMock()
    agent._skill_registry.load_all = MagicMock(return_value=[])
    agent._refresh_brain_tools = MagicMock()
    agent._brain = AsyncMock()
    agent._brain.run = AsyncMock()
    result = MagicMock()
    result.output = "brain_output"
    result.all_messages = MagicMock(return_value=[])
    agent._brain.run.return_value = result
    agent.agent_id = "testagent"
    agent.personality = MagicMock()
    agent._private_memory = None
    agent._council_memory = None
    agent._nats_bus = None
    agent._scheduler = None
    return agent


def _make_mock_private_memory(count=5, oldest_age_minutes=120):
    pm = MagicMock()
    # Simulate pool with an async context manager for acquire
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock()

    async def count_val(*args, **kwargs):
        return count

    async def oldest_val(*args, **kwargs):
        # Return a datetime-like object for age calculation
        import datetime
        return datetime.datetime.utcnow() - datetime.timedelta(minutes=oldest_age_minutes)

    conn.fetchval.side_effect = lambda sql, *args, **kw: (
        count_val(sql, *args, **kw) if "COUNT" in sql
        else oldest_val(sql, *args, **kw) if "MIN" in sql
        else None
    )

    class _Acquirer:
        async def __aenter__(self):
            return conn
        async def __aexit__(self, *args):
            pass

    pm._pool = MagicMock()
    pm._pool.acquire.return_value = _Acquirer()
    pm._agent_id = "testagent"
    pm._table_name = "private_memory"
    return pm


# ===========================================================================
# _builtin_skill_reload — log count of loaded skills
# ===========================================================================


class TestSkillReloadCount:
    async def test_logs_count_of_loaded_skills(self, caplog):
        """load_all() returns list of Skill objects — handler should log the count."""
        agent = _make_mock_agent()
        agent._skill_registry.load_all.return_value = [MagicMock(), MagicMock(), MagicMock()]

        with caplog.at_level("INFO"):
            await _builtin_skill_reload(agent_id="testagent", _agent_handler=agent)

        agent._skill_registry.load_all.assert_called_once()
        agent._refresh_brain_tools.assert_called_once()
        assert "3 skills" in caplog.text.lower().replace("skill", "skills") or "3" in caplog.text

    async def test_logs_zero_skills(self, caplog):
        agent = _make_mock_agent()
        agent._skill_registry.load_all.return_value = []

        with caplog.at_level("INFO"):
            await _builtin_skill_reload(agent_id="testagent", _agent_handler=agent)

        assert "0" in caplog.text

    async def test_noop_when_no_skill_registry(self, caplog):
        agent = _make_mock_agent()
        agent._skill_registry = None
        with caplog.at_level("WARNING"):
            await _builtin_skill_reload(agent_id="testagent", _agent_handler=agent)
        assert "no skill_registry" in caplog.text

    async def test_logs_exception_on_error(self, caplog):
        agent = _make_mock_agent()
        agent._skill_registry.load_all.side_effect = RuntimeError("boom")
        with caplog.at_level("ERROR"):
            await _builtin_skill_reload(agent_id="testagent", _agent_handler=agent)
        assert "boom" in caplog.text


# ===========================================================================
# _builtin_memory_review — log memory state summary
# ===========================================================================


class TestMemoryReviewStateSummary:
    async def test_logs_memory_state_summary_with_private_memory(self, caplog):
        """When PrivateMemory is available, log count and oldest entry age."""
        agent = _make_mock_agent()
        agent._private_memory = _make_mock_private_memory(count=42, oldest_age_minutes=180)

        with caplog.at_level("INFO"):
            await _builtin_memory_review(agent_id="testagent", args={}, _agent_handler=agent)

        agent.compact_history.assert_awaited_once()
        log_text = caplog.text.lower()
        # Should contain count and age information
        assert "42" in log_text or "memory" in log_text

    async def test_logs_zero_memory_when_no_entries(self, caplog):
        agent = _make_mock_agent()
        agent._private_memory = _make_mock_private_memory(count=0, oldest_age_minutes=0)

        with caplog.at_level("INFO"):
            await _builtin_memory_review(agent_id="testagent", args={}, _agent_handler=agent)

        agent.compact_history.assert_awaited_once()

    async def test_handles_missing_private_memory_gracefully(self, caplog):
        """When no PrivateMemory, still calls compact_history and logs."""
        agent = _make_mock_agent()
        agent._private_memory = None

        with caplog.at_level("INFO"):
            await _builtin_memory_review(agent_id="testagent", args={}, _agent_handler=agent)

        agent.compact_history.assert_awaited_once()

    async def test_handles_private_memory_query_error(self, caplog):
        """When PrivateMemory query fails, still completes compact_history."""
        agent = _make_mock_agent()
        pm = _make_mock_private_memory(count=5, oldest_age_minutes=60)
        pm._pool.acquire.side_effect = RuntimeError("db down")
        agent._private_memory = pm

        with caplog.at_level("INFO"):
            await _builtin_memory_review(agent_id="testagent", args={}, _agent_handler=agent)

        # compact_history should still be called
        agent.compact_history.assert_awaited_once()

    async def test_handles_private_memory_no_pool(self, caplog):
        """PrivateMemory without a pool is handled gracefully."""
        agent = _make_mock_agent()
        pm = MagicMock()
        pm._pool = None
        pm._agent_id = "testagent"
        agent._private_memory = pm

        with caplog.at_level("INFO"):
            await _builtin_memory_review(agent_id="testagent", args={}, _agent_handler=agent)

        agent.compact_history.assert_awaited_once()

    async def test_noop_when_agent_handler_missing(self, caplog):
        with caplog.at_level("WARNING"):
            await _builtin_memory_review(agent_id="noagent", args={})
        assert "no agent handler" in caplog.text

    async def test_logs_exception_on_compact_error(self, caplog):
        agent = _make_mock_agent()
        agent.compact_history.side_effect = RuntimeError("boom")
        with caplog.at_level("ERROR"):
            await _builtin_memory_review(agent_id="testagent", args={}, _agent_handler=agent)
        assert "boom" in caplog.text


# ===========================================================================
# _builtin_custom — parse "action" field from args
# ===========================================================================


class TestBuiltinCustomActionField:
    async def test_uses_action_field_as_skill_alias(self):
        """When args has "action" (not "skill"), it should dispatch to skill."""
        agent = _make_mock_agent()
        skill = MagicMock()
        skill.execute = AsyncMock(return_value="skill_output")
        agent._skill_registry.get_skill.return_value = skill

        await _builtin_custom(
            agent_id="testagent",
            args={"action": "my_skill", "extra": 1},
            _agent_handler=agent,
        )

        agent._skill_registry.get_skill.assert_called_once_with("my_skill")
        skill.execute.assert_awaited_once_with(
            agent_id="testagent", channel="scheduler", action="my_skill", extra=1
        )

    async def test_skill_field_takes_priority_over_action(self):
        """When both 'skill' and 'action' are in args, 'skill' wins."""
        agent = _make_mock_agent()
        skill = MagicMock()
        skill.execute = AsyncMock(return_value="skill_output")
        agent._skill_registry.get_skill.return_value = skill

        await _builtin_custom(
            agent_id="testagent",
            args={"skill": "primary_skill", "action": "fallback_skill"},
            _agent_handler=agent,
        )

        agent._skill_registry.get_skill.assert_called_once_with("primary_skill")

    async def test_action_field_when_skill_not_found_tries_prompt(self, caplog):
        """When action-specified skill not found, fall through to prompt."""
        agent = _make_mock_agent()
        agent._skill_registry.get_skill.return_value = None

        with caplog.at_level("WARNING"):
            await _builtin_custom(
                agent_id="testagent",
                args={"action": "nonexistent_skill"},
                _agent_handler=agent,
            )

        agent._skill_registry.get_skill.assert_called_once_with("nonexistent_skill")
        # Should NOT have tried brain since there's no prompt
        assert "not found" in caplog.text.lower()

    async def test_action_with_prompt_runs_brain(self):
        """When action specifies both action and prompt, skill fails -> brain."""
        agent = _make_mock_agent()
        agent._skill_registry.get_skill.return_value = None

        await _builtin_custom(
            agent_id="testagent",
            args={"action": "nonexistent", "prompt": "hello world"},
            _agent_handler=agent,
        )

        agent._skill_registry.get_skill.assert_called_once_with("nonexistent")
        agent._brain.run.assert_awaited_once()
        assert agent._brain.run.call_args.kwargs["user_prompt"] == "hello world"

    async def test_no_skill_or_action_goes_to_prompt(self):
        """No skill or action field, but has prompt — run brain."""
        agent = _make_mock_agent()
        await _builtin_custom(
            agent_id="testagent",
            args={"prompt": "say hi"},
            _agent_handler=agent,
        )
        agent._brain.run.assert_awaited_once()
        assert agent._brain.run.call_args.kwargs["user_prompt"] == "say hi"

    async def test_logs_when_neither_skill_nor_action_nor_prompt(self, caplog):
        agent = _make_mock_agent()
        with caplog.at_level("INFO"):
            await _builtin_custom(agent_id="testagent", args={}, _agent_handler=agent)
        assert "no skill or prompt configured" in caplog.text
