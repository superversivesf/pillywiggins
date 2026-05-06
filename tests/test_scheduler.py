import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.agents.base import _ACTIVE_AGENTS
from pillywiggins.scheduling.scheduler import (
    AgentScheduler,
    _builtin_custom,
    _builtin_memory_review,
    _builtin_skill_reload,
    parse_cron,
)


def _patched_scheduler(tmp_path, agent_id="testagent"):
    return AgentScheduler("redis://localhost:6379", agent_id, schedules_dir=str(tmp_path))


def _make_memory_scheduler():
    from apscheduler.jobstores.memory import MemoryJobStore
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    return AsyncIOScheduler(jobstores={"default": MemoryJobStore()})


async def _make_scheduler(tmp_path, agent_id="testagent", yaml_schedules=None):
    s = _patched_scheduler(tmp_path, agent_id)
    s._scheduler = _make_memory_scheduler()
    yaml_jobs = s._load_schedules(yaml_schedules or {})
    json_jobs = s._load_json_schedules()
    all_jobs = s._merge_jobs(yaml_jobs, json_jobs)
    for job in all_jobs:
        s._add_job_to_scheduler(job)
    s._scheduler.start()
    return s


def _make_mock_agent():
    agent = MagicMock()
    agent.compact_history = AsyncMock(return_value="compacted")
    agent._skill_registry = MagicMock()
    agent._skill_registry.load_all = MagicMock()
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


class TestStartWithYamlSchedules:
    async def test_jobs_created_from_yaml(self, tmp_path):
        s = await _make_scheduler(
            tmp_path,
            yaml_schedules={
                "heartbeat": {"action": "heartbeat", "interval_seconds": 60},
                "daily_review": {"action": "memory_review", "cron": "0 9 * * *"},
            },
        )
        try:
            jobs = await s.list_jobs()
            names = {j["name"] for j in jobs}
            assert "heartbeat" in names
            assert "daily_review" in names
        finally:
            await s.stop()


class TestAddJobInterval:
    async def test_add_job_with_interval_seconds(self, tmp_path):
        s = await _make_scheduler(tmp_path)
        try:
            result = await s.add_job("ping", "heartbeat", interval_seconds=30)
            assert result["success"] is True
            jobs = await s.list_jobs()
            names = [j["name"] for j in jobs]
            assert "ping" in names
        finally:
            await s.stop()

    async def test_add_job_interval_has_next_run_time(self, tmp_path):
        s = await _make_scheduler(tmp_path)
        try:
            await s.add_job("timed", "heartbeat", interval_seconds=10)
            jobs = await s.list_jobs()
            timed = next(j for j in jobs if j["name"] == "timed")
            assert timed["next_run_time"] is not None
        finally:
            await s.stop()


class TestAddJobCron:
    async def test_add_job_with_cron_expr(self, tmp_path):
        s = await _make_scheduler(tmp_path)
        try:
            result = await s.add_job("nightly", "memory_review", cron_expr="0 2 * * *")
            assert result["success"] is True
            jobs = await s.list_jobs()
            names = [j["name"] for j in jobs]
            assert "nightly" in names
        finally:
            await s.stop()

    async def test_add_job_cron_has_action(self, tmp_path):
        s = await _make_scheduler(tmp_path)
        try:
            await s.add_job("nightly", "memory_review", cron_expr="0 2 * * *")
            jobs = await s.list_jobs()
            nightly = next(j for j in jobs if j["name"] == "nightly")
            assert nightly["action"] == "memory_review"
        finally:
            await s.stop()


class TestRemoveJob:
    async def test_remove_job(self, tmp_path):
        s = await _make_scheduler(tmp_path)
        try:
            await s.add_job("gone", "heartbeat", interval_seconds=60)
            removed = await s.remove_job("gone")
            assert removed is True
            jobs = await s.list_jobs()
            names = [j["name"] for j in jobs]
            assert "gone" not in names
        finally:
            await s.stop()

    async def test_remove_job_nonexistent_returns_true(self, tmp_path):
        s = await _make_scheduler(tmp_path)
        try:
            removed = await s.remove_job("no_such_job")
            assert removed is True
        finally:
            await s.stop()


class TestListJobs:
    async def test_list_jobs_returns_name_action_next_run(self, tmp_path):
        s = await _make_scheduler(tmp_path)
        try:
            await s.add_job("job1", "heartbeat", interval_seconds=60)
            await s.add_job("job2", "skill_reload", cron_expr="0 * * * *")
            jobs = await s.list_jobs()
            entry = next(j for j in jobs if j["name"] == "job1")
            assert entry["name"] == "job1"
            assert entry["action"] == "heartbeat"
            assert entry["next_run_time"] is not None
        finally:
            await s.stop()

    async def test_list_jobs_empty_when_no_jobs(self, tmp_path):
        s = await _make_scheduler(tmp_path)
        try:
            jobs = await s.list_jobs()
            assert jobs == []
        finally:
            await s.stop()


class TestJsonPersistence:
    async def test_add_job_persists_to_json(self, tmp_path):
        s = await _make_scheduler(tmp_path)
        try:
            await s.add_job("persisted", "heartbeat", interval_seconds=120)
            json_path = tmp_path / "testagent_schedules.json"
            assert json_path.exists()
            data = json.loads(json_path.read_text(encoding="utf-8"))
            names = [j["name"] for j in data]
            assert "persisted" in names
        finally:
            await s.stop()

    async def test_json_file_content_valid(self, tmp_path):
        s = await _make_scheduler(tmp_path)
        try:
            await s.add_job("myjob", "custom", interval_seconds=300, args={"key": "val"})
            json_path = tmp_path / "testagent_schedules.json"
            data = json.loads(json_path.read_text(encoding="utf-8"))
            job = next(j for j in data if j["name"] == "myjob")
            assert job["action"] == "custom"
            assert job["interval_seconds"] == 300
            assert job["args"] == {"key": "val"}
        finally:
            await s.stop()


class TestReload:
    async def test_reload_clears_and_readds(self, tmp_path):
        s = await _make_scheduler(tmp_path)
        try:
            await s.add_job("old", "heartbeat", interval_seconds=60)
            await s.reload()
            jobs = await s.list_jobs()
            names = [j["name"] for j in jobs]
            assert "old" in names
        finally:
            await s.stop()

    async def test_reload_with_new_yaml(self, tmp_path):
        s = await _make_scheduler(
            tmp_path,
            yaml_schedules={"first": {"action": "heartbeat", "interval_seconds": 60}},
        )
        try:
            await s.reload(
                yaml_schedules={
                    "first": {"action": "heartbeat", "interval_seconds": 60},
                    "second": {"action": "memory_review", "cron": "0 3 * * *"},
                }
            )
            jobs = await s.list_jobs()
            names = {j["name"] for j in jobs}
            assert "first" in names
            assert "second" in names
        finally:
            await s.stop()


class TestParseCron:
    def test_parse_cron_full_expr(self):
        result = parse_cron("0 * * * *")
        assert result == {"minute": "0", "hour": "*", "day": "*", "month": "*", "day_of_week": "*"}

    def test_parse_cron_all_fields(self):
        result = parse_cron("30 9 1 6 5")
        assert result == {"minute": "30", "hour": "9", "day": "1", "month": "6", "day_of_week": "5"}

    def test_parse_cron_invalid(self):
        with pytest.raises(ValueError, match="Invalid cron expression"):
            parse_cron("too few fields")


class TestRedisFallback:
    async def test_falls_back_to_memory_job_store(self, tmp_path):
        with patch("pillywiggins.scheduling.scheduler.RedisJobStore") as mock_store_cls:
            mock_store = mock_store_cls.return_value
            mock_store.redis.ping.side_effect = Exception("connection refused")
            s = AgentScheduler("redis://localhost:6379", "fb", schedules_dir=str(tmp_path))
            await s.start()
        try:
            jobs = await s.list_jobs()
            assert isinstance(jobs, list)
        finally:
            await s.stop()


class TestBuiltInHandlers:
    async def test_register_custom_handler(self, tmp_path):
        called = []

        async def my_handler(**kwargs):
            called.append(kwargs)

        s = _patched_scheduler(tmp_path, "handler_test")
        s.register_handler("my_action", my_handler)
        s._scheduler = _make_memory_scheduler()
        s._scheduler.start()
        try:
            handler = s._get_handler("my_action")
            assert handler is my_handler
        finally:
            await s.stop()

    async def test_builtin_handlers_exist(self, tmp_path):
        s = _patched_scheduler(tmp_path, "bh")
        assert "heartbeat" in s._action_handlers
        assert "memory_review" in s._action_handlers
        assert "skill_reload" in s._action_handlers
        assert "custom" in s._action_handlers


class TestBuiltinMemoryReview:
    async def test_calls_compact_history(self, tmp_path):
        agent = _make_mock_agent()
        with patch.dict(_ACTIVE_AGENTS, {"testagent": agent}, clear=False):
            await _builtin_memory_review(agent_id="testagent", args={"conversation_key": "ck1"})
        agent.compact_history.assert_awaited_once_with(conversation_key="ck1")

    async def test_calls_compact_history_no_conversation_key(self, tmp_path):
        agent = _make_mock_agent()
        with patch.dict(_ACTIVE_AGENTS, {"testagent": agent}, clear=False):
            await _builtin_memory_review(agent_id="testagent", args={})
        agent.compact_history.assert_awaited_once_with(conversation_key=None)

    async def test_noop_when_agent_missing(self, caplog):
        with caplog.at_level("WARNING"):
            await _builtin_memory_review(agent_id="noagent", args={})
        assert "not found" in caplog.text

    async def test_logs_exception_on_error(self, caplog):
        agent = _make_mock_agent()
        agent.compact_history.side_effect = RuntimeError("boom")
        with patch.dict(_ACTIVE_AGENTS, {"testagent": agent}, clear=False):
            with caplog.at_level("ERROR"):
                await _builtin_memory_review(agent_id="testagent", args={})
        assert "boom" in caplog.text


class TestBuiltinSkillReload:
    async def test_calls_load_all_and_refresh(self, tmp_path):
        agent = _make_mock_agent()
        with patch.dict(_ACTIVE_AGENTS, {"testagent": agent}, clear=False):
            await _builtin_skill_reload(agent_id="testagent")
        agent._skill_registry.load_all.assert_called_once()
        agent._refresh_brain_tools.assert_called_once()

    async def test_noop_when_no_skill_registry(self, caplog):
        agent = _make_mock_agent()
        agent._skill_registry = None
        with patch.dict(_ACTIVE_AGENTS, {"testagent": agent}, clear=False):
            with caplog.at_level("WARNING"):
                await _builtin_skill_reload(agent_id="testagent")
        assert "no skill_registry" in caplog.text

    async def test_noop_when_agent_missing(self, caplog):
        with caplog.at_level("WARNING"):
            await _builtin_skill_reload(agent_id="noagent")
        assert "not found" in caplog.text

    async def test_logs_exception_on_error(self, caplog):
        agent = _make_mock_agent()
        agent._skill_registry.load_all.side_effect = RuntimeError("boom")
        with patch.dict(_ACTIVE_AGENTS, {"testagent": agent}, clear=False):
            with caplog.at_level("ERROR"):
                await _builtin_skill_reload(agent_id="testagent")
        assert "boom" in caplog.text


class TestBuiltinCustom:
    async def test_executes_skill_when_args_has_skill(self):
        agent = _make_mock_agent()
        skill = MagicMock()
        skill.execute = AsyncMock(return_value="skill_output")
        agent._skill_registry.get_skill.return_value = skill
        with patch.dict(_ACTIVE_AGENTS, {"testagent": agent}, clear=False):
            await _builtin_custom(agent_id="testagent", args={"skill": "my_skill", "extra": 1})
        agent._skill_registry.get_skill.assert_called_once_with("my_skill")
        skill.execute.assert_awaited_once_with(agent_id="testagent", channel="scheduler", skill="my_skill", extra=1)

    async def test_runs_brain_when_args_has_prompt(self):
        agent = _make_mock_agent()
        with patch.dict(_ACTIVE_AGENTS, {"testagent": agent}, clear=False):
            await _builtin_custom(agent_id="testagent", args={"prompt": "hello"})
        agent._brain.run.assert_awaited_once()
        call_args = agent._brain.run.call_args
        assert call_args.kwargs["user_prompt"] == "hello"

    async def test_logs_when_no_skill_or_prompt(self, caplog):
        agent = _make_mock_agent()
        with patch.dict(_ACTIVE_AGENTS, {"testagent": agent}, clear=False):
            with caplog.at_level("INFO"):
                await _builtin_custom(agent_id="testagent", args={})
        assert "no skill or prompt configured" in caplog.text

    async def test_noop_when_agent_missing(self, caplog):
        with caplog.at_level("WARNING"):
            await _builtin_custom(agent_id="noagent", args={})
        assert "not found" in caplog.text

    async def test_noop_when_args_not_dict(self, caplog):
        agent = _make_mock_agent()
        with patch.dict(_ACTIVE_AGENTS, {"testagent": agent}, clear=False):
            with caplog.at_level("WARNING"):
                await _builtin_custom(agent_id="testagent", args=None)
        assert "args is not a dict" in caplog.text

    async def test_logs_exception_on_error(self, caplog):
        agent = _make_mock_agent()
        agent._skill_registry.get_skill.side_effect = RuntimeError("boom")
        with patch.dict(_ACTIVE_AGENTS, {"testagent": agent}, clear=False):
            with caplog.at_level("ERROR"):
                await _builtin_custom(agent_id="testagent", args={"skill": "my_skill"})
        assert "boom" in caplog.text


class TestMergeYamlAndJson:
    async def test_yaml_and_json_jobs_both_appear(self, tmp_path):
        json_path = tmp_path / "merge_test_schedules.json"
        json_path.write_text(
            json.dumps([{"name": "from_json", "action": "heartbeat", "interval_seconds": 45}]) + "\n",
            encoding="utf-8",
        )
        yaml_schedules = {"from_yaml": {"action": "skill_reload", "cron": "0 * * * *"}}
        s = await _make_scheduler(tmp_path, "merge_test", yaml_schedules=yaml_schedules)
        try:
            jobs = await s.list_jobs()
            names = {j["name"] for j in jobs}
            assert "from_yaml" in names
            assert "from_json" in names
        finally:
            await s.stop()

    async def test_json_overrides_yaml_same_name(self, tmp_path):
        json_path = tmp_path / "override_test_schedules.json"
        json_path.write_text(
            json.dumps([{"name": "shared", "action": "heartbeat", "interval_seconds": 99}]) + "\n",
            encoding="utf-8",
        )
        yaml_schedules = {"shared": {"action": "skill_reload", "cron": "0 * * * *"}}
        s = await _make_scheduler(tmp_path, "override_test", yaml_schedules=yaml_schedules)
        try:
            jobs = await s.list_jobs()
            shared = next(j for j in jobs if j["name"] == "shared")
            assert shared["action"] == "heartbeat"
        finally:
            await s.stop()


class TestStop:
    async def test_scheduler_shuts_down_cleanly(self, tmp_path):
        s = await _make_scheduler(
            tmp_path,
            yaml_schedules={"hb": {"action": "heartbeat", "interval_seconds": 60}},
        )
        await s.stop()
        assert s._scheduler is None

    async def test_list_jobs_after_stop_returns_empty(self, tmp_path):
        s = await _make_scheduler(
            tmp_path,
            yaml_schedules={"hb": {"action": "heartbeat", "interval_seconds": 60}},
        )
        await s.stop()
        jobs = await s.list_jobs()
        assert jobs == []

    async def test_stop_idempotent(self, tmp_path):
        s = await _make_scheduler(tmp_path)
        await s.stop()
        await s.stop()