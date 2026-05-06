"""Tests for brain schedule and messaging tools: schedule_task, unschedule_task,
list_scheduled_tasks, get_current_time, get_conversation_info, send_message_to_agent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext

from pillywiggins.agents.brain import (
    schedule_task,
    unschedule_task,
    list_scheduled_tasks,
    get_current_time,
    get_conversation_info,
    send_message_to_agent,
)
from pillywiggins.agents.deps import AgentDeps
from pillywiggins.agents.personality import Personality
from tests.helpers import make_ctx

_make_ctx = make_ctx


class TestScheduleTask:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_no_scheduler(self):
        ctx = _make_ctx(scheduler=None)
        result = await schedule_task(ctx, name="test", action="heartbeat")
        assert result == "Scheduler is not available."

    @pytest.mark.asyncio
    async def test_schedules_interval_job(self):
        scheduler = MagicMock()
        scheduler.add_job = AsyncMock(return_value={"success": True, "name": "test"})
        ctx = _make_ctx(scheduler=scheduler)
        result = await schedule_task(ctx, name="test_job", action="heartbeat", interval_seconds=300)
        scheduler.add_job.assert_awaited_once()
        assert "Scheduled task" in result

    @pytest.mark.asyncio
    async def test_schedules_cron_job(self):
        scheduler = MagicMock()
        scheduler.add_job = AsyncMock(return_value={"success": True, "name": "cron_test"})
        ctx = _make_ctx(scheduler=scheduler)
        result = await schedule_task(
            ctx, name="cron_test", action="heartbeat", cron_expr="0 * * * *"
        )
        assert "Scheduled task" in result

    @pytest.mark.asyncio
    async def test_invalid_args_json(self):
        scheduler = MagicMock()
        scheduler.add_job = AsyncMock(return_value={"success": True, "name": "test"})
        ctx = _make_ctx(scheduler=scheduler)
        result = await schedule_task(ctx, name="test", action="send_message", args_json="not json")
        assert "invalid args_json" in result

    @pytest.mark.asyncio
    async def test_valid_args_json(self):
        scheduler = MagicMock()
        scheduler.add_job = AsyncMock(return_value={"success": True, "name": "test"})
        ctx = _make_ctx(scheduler=scheduler)
        result = await schedule_task(
            ctx, name="test", action="send_message", args_json='{"conversation_key": "123"}'
        )
        scheduler.add_job.assert_awaited_once()
        call_kwargs = scheduler.add_job.call_args[1]
        assert call_kwargs["args"] == {"conversation_key": "123"}

    @pytest.mark.asyncio
    async def test_failed_schedule(self):
        scheduler = MagicMock()
        scheduler.add_job = AsyncMock(return_value={"success": False, "error": "job exists"})
        ctx = _make_ctx(scheduler=scheduler)
        result = await schedule_task(ctx, name="dup", action="heartbeat", interval_seconds=60)
        assert "Failed to schedule" in result


class TestUnscheduleTask:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_no_scheduler(self):
        ctx = _make_ctx(scheduler=None)
        result = await unschedule_task(ctx, name="test")
        assert result == "Scheduler is not available."

    @pytest.mark.asyncio
    async def test_successful_removal(self):
        scheduler = MagicMock()
        scheduler.remove_job = AsyncMock(return_value=True)
        ctx = _make_ctx(scheduler=scheduler)
        result = await unschedule_task(ctx, name="test_job")
        assert "Unscheduled task" in result

    @pytest.mark.asyncio
    async def test_removal_not_found(self):
        scheduler = MagicMock()
        scheduler.remove_job = AsyncMock(return_value=False)
        ctx = _make_ctx(scheduler=scheduler)
        result = await unschedule_task(ctx, name="nonexistent")
        assert "not found" in result


class TestListScheduledTasks:
    @pytest.mark.asyncio
    async def test_returns_unavailable_when_no_scheduler(self):
        ctx = _make_ctx(scheduler=None)
        result = await list_scheduled_tasks(ctx)
        assert result == "Scheduler is not available."

    @pytest.mark.asyncio
    async def test_returns_no_tasks_when_empty(self):
        scheduler = MagicMock()
        scheduler.list_jobs = AsyncMock(return_value=[])
        ctx = _make_ctx(scheduler=scheduler)
        result = await list_scheduled_tasks(ctx)
        assert result == "No scheduled tasks"

    @pytest.mark.asyncio
    async def test_lists_single_task_without_args(self):
        scheduler = MagicMock()
        scheduler.list_jobs = AsyncMock(
            return_value=[
                {
                    "id": "job1",
                    "name": "heartbeat",
                    "next_run_time": "2026-04-21 10:05:00",
                    "action": "heartbeat",
                    "args": None,
                }
            ]
        )
        ctx = _make_ctx(scheduler=scheduler)
        result = await list_scheduled_tasks(ctx)
        assert "Scheduled tasks (1)" in result
        assert "heartbeat" in result
        assert "action: heartbeat" in result
        assert "next: 2026-04-21 10:05:00" in result

    @pytest.mark.asyncio
    async def test_lists_multiple_tasks_with_args(self):
        scheduler = MagicMock()
        scheduler.list_jobs = AsyncMock(
            return_value=[
                {
                    "id": "job1",
                    "name": "hourly_greeting",
                    "next_run_time": "2026-04-21 10:00:00",
                    "action": "send_message",
                    "args": {"conversation_key": "123", "prompt": "Say hi"},
                },
                {
                    "id": "job2",
                    "name": "heartbeat",
                    "next_run_time": "2026-04-21 10:05:00",
                    "action": "heartbeat",
                    "args": None,
                },
                {
                    "id": "job3",
                    "name": "review",
                    "next_run_time": "2026-04-21 12:00:00",
                    "action": "memory_review",
                    "args": None,
                },
            ]
        )
        ctx = _make_ctx(scheduler=scheduler)
        result = await list_scheduled_tasks(ctx)
        assert "Scheduled tasks (3)" in result
        assert "hourly_greeting" in result
        assert "send_message" in result
        assert "heartbeat" in result
        assert "memory_review" in result
        assert "conversation_key" in result

    @pytest.mark.asyncio
    async def test_task_with_empty_args_not_shown(self):
        scheduler = MagicMock()
        scheduler.list_jobs = AsyncMock(
            return_value=[
                {
                    "id": "job1",
                    "name": "review",
                    "next_run_time": "2026-04-21 12:00:00",
                    "action": "memory_review",
                    "args": {},
                }
            ]
        )
        ctx = _make_ctx(scheduler=scheduler)
        result = await list_scheduled_tasks(ctx)
        assert "review" in result
        assert "action: memory_review" in result
        assert "args" not in result

    @pytest.mark.asyncio
    async def test_task_with_missing_keys_uses_defaults(self):
        scheduler = MagicMock()
        scheduler.list_jobs = AsyncMock(return_value=[{"id": "job1"}])
        ctx = _make_ctx(scheduler=scheduler)
        result = await list_scheduled_tasks(ctx)
        assert "unnamed" in result
        assert "action: unknown" in result
        assert "next: N/A" in result


class TestGetCurrentTime:
    @pytest.mark.asyncio
    async def test_returns_utc_time_with_no_personality(self):
        ctx = _make_ctx(personality=None)
        result = await get_current_time(ctx)
        assert "UTC" in result

    @pytest.mark.asyncio
    async def test_returns_timezone_with_personality(self):
        personality = Personality(
            name="Puck",
            channel="telegram",
            description="A fairy",
            system_prompt="You are Puck.",
            timezone="America/Los_Angeles",
        )
        ctx = _make_ctx(personality=personality)
        result = await get_current_time(ctx)
        assert "America/Los_Angeles" in result

    @pytest.mark.asyncio
    async def test_falls_back_to_utc_on_invalid_timezone(self):
        personality = Personality(
            name="BadTz",
            channel="telegram",
            description="test",
            system_prompt="test",
            timezone="Invalid/Timezone",
        )
        ctx = _make_ctx(personality=personality)
        result = await get_current_time(ctx)
        assert "UTC" in result

    @pytest.mark.asyncio
    async def test_utc_personality_returns_utc(self):
        personality = Personality(
            name="UTCBot",
            channel="discord",
            description="test",
            system_prompt="test",
            timezone="UTC",
        )
        ctx = _make_ctx(personality=personality)
        result = await get_current_time(ctx)
        assert "UTC" in result


class TestGetConversationInfo:
    @pytest.mark.asyncio
    async def test_default_conversation_info_returns_zero(self):
        ctx = _make_ctx()
        result = await get_conversation_info(ctx)
        assert "0 messages" in result
        assert "0 tokens" in result

    @pytest.mark.asyncio
    async def test_custom_conversation_info_with_messages(self):
        ctx = _make_ctx()
        ctx.deps = AgentDeps(
            agent_id="puck",
            channel="telegram",
            conversation_info=lambda: {"message_count": 5, "estimated_tokens": 120},
        )
        result = await get_conversation_info(ctx)
        assert "5 messages" in result
        assert "120 tokens" in result

    @pytest.mark.asyncio
    async def test_conversation_info_with_zero_messages(self):
        ctx = _make_ctx()
        ctx.deps = AgentDeps(
            agent_id="puck",
            channel="telegram",
            conversation_info=lambda: {"message_count": 0, "estimated_tokens": 0},
        )
        result = await get_conversation_info(ctx)
        assert "0 messages" in result

    @pytest.mark.asyncio
    async def test_conversation_info_missing_keys_defaults_to_zero(self):
        ctx = _make_ctx()
        ctx.deps = AgentDeps(
            agent_id="puck",
            channel="telegram",
            conversation_info=lambda: {},
        )
        result = await get_conversation_info(ctx)
        assert "0 messages" in result
        assert "0 tokens" in result


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
        ctx = _make_ctx(agent_id="puck", channel="discord", nats_bus=nats)
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
        assert "routing_info" in data
        assert data["routing_info"]["original_channel"] == "discord"
        assert data["routing_info"]["original_channel_user_id"] == ""
        assert result == "Sent message to oberon"

    @pytest.mark.asyncio
    async def test_publishes_with_full_routing_context(self):
        nats = MagicMock()
        nats.publish_direct = AsyncMock()
        ctx = MagicMock(spec=RunContext)
        ctx.deps = AgentDeps(
            agent_id="puck",
            channel="discord",
            channel_user_id="123456",
            conversation_key="67890",
            metadata={"chat_id": "67890"},
            nats_bus=nats,
        )
        result = await send_message_to_agent(ctx, target_agent_id="titania", message="hello")
        data = nats.publish_direct.call_args[1]["data"]
        assert data["channel"] == "discord"
        assert data["channel_user_id"] == "123456"
        assert data["conversation_key"] == "67890"
        assert data["metadata"] == {"chat_id": "67890"}
        assert data["routing_info"]["original_channel"] == "discord"
        assert data["routing_info"]["original_channel_user_id"] == "123456"
        assert data["routing_info"]["original_conversation_key"] == "67890"
        assert data["routing_info"]["original_metadata"] == {"chat_id": "67890"}
        assert result == "Sent message to titania"


class TestSanitizerIntegrationSchedule:
    @pytest.mark.asyncio
    async def test_send_message_to_agent_sanitized(self):
        nats = MagicMock()
        nats.publish_direct = AsyncMock()
        ctx = _make_ctx(nats_bus=nats)
        result = await send_message_to_agent(ctx, target_agent_id="puck", message="hello")
        assert "Sent message to puck" in result