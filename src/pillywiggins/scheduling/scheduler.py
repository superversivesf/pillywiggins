from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from pillywiggins.messaging.unified import ChannelType, UnifiedMessage

logger = logging.getLogger(__name__)

# Module-level registry so scheduled jobs can look up their agent handler
# without pickling it into RedisJobStore kwargs.
AGENT_HANDLERS: dict[str, Any] = {}

CRON_FIELDS = ["minute", "hour", "day", "month", "day_of_week"]


async def _builtin_heartbeat(**kwargs: Any) -> None:
    agent_id = kwargs.get("agent_id", "unknown")
    logger.info("heartbeat for %s", agent_id)


async def _builtin_memory_review(**kwargs: Any) -> None:
    agent_id = kwargs.get("agent_id", "unknown")
    args = kwargs.get("args", {})
    logger.info("memory review for %s", agent_id)
    handler = AGENT_HANDLERS.get(agent_id) or kwargs.get("_agent_handler")
    if handler is None:
        logger.warning("memory_review: no agent handler for %s", agent_id)
        return
    try:
        state_parts: list[str] = []

        # Query PrivateMemory stats if available
        pm = getattr(handler, "_private_memory", None)
        if pm is not None and getattr(pm, "_pool", None) is not None:
            try:
                async with pm._pool.acquire() as conn:
                    await pm._ensure_agent_id(conn)
                    count_row = await conn.fetchval(
                        f"SELECT COUNT(*) FROM {pm._table_name}"
                    )
                    oldest_row = await conn.fetchval(
                        f"SELECT MIN(created_at) FROM {pm._table_name}"
                    )
                mem_count = int(count_row) if count_row is not None else 0
                state_parts.append(f"count={mem_count}")
                if oldest_row is not None:
                    import datetime
                    now = datetime.datetime.now(datetime.UTC)
                    age_seconds = (now - oldest_row).total_seconds()
                    if age_seconds < 120:
                        state_parts.append(f"oldest_age={int(age_seconds)}s")
                    elif age_seconds < 7200:
                        state_parts.append(f"oldest_age={int(age_seconds // 60)}m")
                    else:
                        state_parts.append(f"oldest_age={int(age_seconds // 3600)}h")
                state_parts.append(f"table={pm._table_name}")
            except Exception:
                logger.debug("Could not query private memory stats for %s", agent_id, exc_info=True)
        else:
            state_parts.append("no_private_memory")

        conversation_key = args.get("conversation_key") if isinstance(args, dict) else None
        result = await handler.compact_history(conversation_key=conversation_key)

        # Prune old memories
        settings = handler._settings
        retention_days = getattr(settings, "memory_retention_days", 90)
        max_entries = getattr(settings, "memory_max_entries", 1000)
        pm = getattr(handler, "_private_memory", None)
        if pm is not None and getattr(pm, "_pool", None) is not None:
            try:
                await pm.prune_by_age(retention_days)
                await pm.prune_to_max(max_entries)
            except Exception:
                logger.debug("Pruning failed for %s", agent_id, exc_info=True)

        logger.info(
            "memory_review result for %s: %s (state: %s)",
            agent_id,
            result,
            ", ".join(state_parts),
        )
    except Exception:
        logger.exception("memory_review failed for %s", agent_id)


async def _builtin_skill_reload(**kwargs: Any) -> None:
    agent_id = kwargs.get("agent_id", "unknown")
    logger.info("skill reload for %s", agent_id)
    handler = AGENT_HANDLERS.get(agent_id) or kwargs.get("_agent_handler")
    if handler is None:
        logger.warning("skill_reload: no agent handler for %s", agent_id)
        return
    try:
        if handler._skill_registry is not None:
            loaded = handler._skill_registry.load_all()
            handler._refresh_brain_tools()
            count = len(loaded)
            logger.info(
                "skill_reload completed for %s: %d skills loaded",
                agent_id,
                count,
            )
        else:
            logger.warning("skill_reload: no skill_registry for %s", agent_id)
    except Exception:
        logger.exception("skill_reload failed for %s", agent_id)


async def _builtin_custom(**kwargs: Any) -> None:
    agent_id = kwargs.get("agent_id", "unknown")
    args = kwargs.get("args", {})
    logger.info("custom action for %s", agent_id)
    handler = AGENT_HANDLERS.get(agent_id) or kwargs.get("_agent_handler")
    if handler is None:
        logger.warning("custom: no agent handler for %s", agent_id)
        return
    try:
        if not isinstance(args, dict):
            logger.warning("custom: args is not a dict for %s", agent_id)
            return

        skill_name = args.get("skill") or args.get("action")
        if skill_name and handler._skill_registry is not None:
            skill = handler._skill_registry.get_skill(skill_name)
            if skill is not None:
                result = await skill.execute(agent_id=agent_id, channel="scheduler", **args)
                logger.info("custom skill %s executed for %s: %s", skill_name, agent_id, result)
                return
            logger.warning("custom: skill %s not found for %s", skill_name, agent_id)

        prompt = args.get("prompt")
        if prompt and hasattr(handler, "_brain"):
            from pillywiggins.agents.deps import AgentDeps

            result = await handler._brain.run(
                user_prompt=prompt,
                deps=AgentDeps(
                    agent_id=handler.agent_id,
                    channel="scheduler",
                    personality=handler.personality,
                    private_memory=handler._private_memory,
                    skill_registry=handler._skill_registry,
                    council_memory=handler._council_memory,
                    nats_bus=handler._nats_bus,
                    scheduler=handler._scheduler,
                    settings=handler._settings,
                    embedding_model=handler._settings.embedding_model,
                    llm_base_url=handler._settings.llm_base_url,
                    llm_api_key=handler._settings.llm_api_key,
                    llm_provider=handler._settings.llm_provider,
                    embedding_dimension=handler._settings.embedding_dimension,
                ),
            )
            output = getattr(result, "output", str(result))

            if isinstance(args, dict) and "conversation_key" in args:
                adapter = getattr(handler, "_adapter", None)
                if adapter is not None:
                    await adapter.send(args["conversation_key"], output)

            logger.info("custom prompt executed for %s: %s", agent_id, output)
            return

        logger.info("custom action for %s completed (no skill or prompt configured)", agent_id)
    except Exception:
        logger.exception("custom action failed for %s", agent_id)


def parse_cron(expr: str) -> dict[str, str]:
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (expected 5 fields): {expr!r}")
    return dict(zip(CRON_FIELDS, parts))


def _make_job_id(agent_id: str, name: str) -> str:
    return f"{agent_id}_{name}"


class AgentScheduler:
    def __init__(
        self,
        redis_url: str,
        agent_id: str,
        schedules_dir: str = "/app/skills",
        channel: str = "",
        agent_handler: Any = None,
    ):
        self._redis_url = redis_url
        self._agent_id = agent_id
        self._schedules_dir = Path(schedules_dir)
        self._channel = channel
        self._agent_handler = agent_handler
        self._scheduler: AsyncIOScheduler | None = None
        self._action_handlers: dict[str, Callable[..., Coroutine]] = {}
        self._yaml_schedules: dict = {}
        self._json_path = self._schedules_dir / f"{agent_id}_schedules.json"
        self._register_builtin_handlers()

    def _register_builtin_handlers(self) -> None:
        self._action_handlers["heartbeat"] = _builtin_heartbeat
        self._action_handlers["memory_review"] = _builtin_memory_review
        self._action_handlers["skill_reload"] = _builtin_skill_reload
        self._action_handlers["custom"] = _builtin_custom

    def register_handler(self, action: str, handler: Callable[..., Coroutine]) -> None:
        self._action_handlers[action] = handler

    def register_agent_handler(self, agent_handler: Any) -> None:
        """Register the agent instance so builtins can look it up by agent_id."""
        if agent_handler is not None:
            AGENT_HANDLERS[self._agent_id] = agent_handler

    def _get_handler(self, action: str) -> Callable[..., Coroutine]:
        if action in self._action_handlers:
            return self._action_handlers[action]
        return self._action_handlers["custom"]

    def _create_scheduler(self) -> AsyncIOScheduler:
        # MemoryJobStore is the default. RedisJobStore has a known issue:
        # APScheduler job state can contain unpicklable objects (asyncio.Lock,
        # _thread.lock), causing `TypeError: cannot pickle '_thread.lock' object`
        # when RedisJobStore serializes with pickle.dumps(job.__getstate__()).
        #
        # RedisJobStore can be opted-in by setting self._use_redis_jobstore=True
        # and ensuring all job kwargs are pickle-safe. JSON file persistence
        # (_persist_json_job) already provides durability across restarts.
        return AsyncIOScheduler(jobstores={"default": MemoryJobStore()})

    async def start(self, yaml_schedules: dict | None = None) -> None:
        self._yaml_schedules = yaml_schedules or {}
        self._scheduler = self._create_scheduler()
        yaml_jobs = self._load_schedules(self._yaml_schedules)
        json_jobs = self._load_json_schedules()
        all_jobs = self._merge_jobs(yaml_jobs, json_jobs)
        added = 0
        for job in all_jobs:
            if self._add_job_to_scheduler(job):
                added += 1
        self._scheduler.start()
        logger.info("Scheduler started for %s with %d/%d jobs added", self._agent_id, added, len(all_jobs))

    async def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped for %s", self._agent_id)
            self._scheduler = None

    def _load_schedules(self, schedules: dict) -> list[dict]:
        jobs = []
        for name, config in schedules.items():
            if not isinstance(config, dict):
                continue
            job = {
                "name": name,
                "action": config.get("action", "custom"),
                "source": "yaml",
            }
            if "interval_seconds" in config:
                job["interval_seconds"] = config["interval_seconds"]
            # Support both "cron" and "cron_expr" for backwards compatibility
            cron_val = config.get("cron", config.get("cron_expr"))
            if cron_val:
                job["cron"] = cron_val
            if "args" in config:
                job["args"] = config["args"]
            jobs.append(job)
        return jobs

    def _load_json_schedules(self) -> list[dict]:
        if not self._json_path.exists():
            return []
        try:
            data = json.loads(self._json_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for job in data:
                    job["source"] = "json"
                return data
            return []
        except Exception:
            logger.warning(
                "Failed to load JSON schedules for %s from %s",
                self._agent_id,
                self._json_path,
                exc_info=True,
            )
            return []

    def _merge_jobs(self, yaml_jobs: list[dict], json_jobs: list[dict]) -> list[dict]:
        seen = {}
        for job in yaml_jobs:
            seen[job["name"]] = job
        for job in json_jobs:
            seen[job["name"]] = job
        return list(seen.values())

    def _synthetic_unified_message(self, job: dict) -> UnifiedMessage:
        """Create a synthetic UnifiedMessage for scheduled callbacks.

        Provides a minimal message context so handlers can expect
        a UnifiedMessage even when the trigger was cron/interval.
        """
        channel_str = self._channel or "telegram"
        try:
            channel = ChannelType(channel_str)
        except ValueError:
            channel = ChannelType.TELEGRAM
        conversation_key = ""
        args = job.get("args") or {}
        if isinstance(args, dict):
            conversation_key = args.get("conversation_key", "")
        return UnifiedMessage(
            channel=channel,
            channel_user_id="scheduler",
            content=f"Scheduled task '{job.get('name', 'unknown')}' triggered.",
            conversation_key=conversation_key,
            metadata={"trigger": "scheduled", "action": job.get("action", "custom")},
        )

    def _add_job_to_scheduler(self, job: dict) -> bool:
        """Add a single job to the running scheduler.

        Returns True on success, False on failure.  Wraps all add_job()
        calls in try/except so that a single bad job definition cannot
        crash the whole scheduler startup/reload.
        """
        if self._scheduler is None:
            return False
        name = job["name"]
        action = job.get("action", "custom")
        job_id = _make_job_id(self._agent_id, name)
        handler = self._get_handler(action)
        kwargs: dict[str, Any] = {"action": action, "agent_id": self._agent_id}
        # NOTE: we do NOT pass _agent_handler here — builtins look it up via
        # AGENT_HANDLERS[agent_id] to avoid pickling asyncio.Lock etc. into
        # RedisJobStore. See register_agent_handler().
        if "args" in job:
            kwargs["args"] = job["args"]

        # Wrap non-send_message scheduled callbacks with a synthetic message context
        if action != "send_message":
            synthetic_msg = self._synthetic_unified_message(job)
            kwargs["message"] = synthetic_msg
            kwargs["synthetic_unified_message"] = synthetic_msg

        trigger_kwargs: dict[str, Any] = {
            "id": job_id,
            "misfire_grace_time": 300,
            "kwargs": kwargs,
            "replace_existing": True,
        }

        try:
            if "interval_seconds" in job:
                self._scheduler.add_job(
                    handler,
                    "interval",
                    seconds=job["interval_seconds"],
                    **trigger_kwargs,
                )
            elif "cron" in job:
                cron_kwargs = parse_cron(job["cron"])
                self._scheduler.add_job(
                    handler,
                    "cron",
                    **cron_kwargs,
                    **trigger_kwargs,
                )
            else:
                logger.warning("Job %s has no interval or cron trigger, skipping", name)
                return False
            logger.debug("Added job %s (%s) to scheduler for %s", name, action, self._agent_id)
            return True
        except Exception:
            logger.exception(
                "Failed to add job %s (%s) to scheduler for %s",
                name,
                action,
                self._agent_id,
            )
            return False

    async def add_job(
        self,
        name: str,
        action: str,
        interval_seconds: int | None = None,
        cron_expr: str | None = None,
        args: dict | None = None,
    ) -> dict:
        if self._scheduler is None:
            return {"success": False, "name": name, "error": "scheduler not started"}

        job = {"name": name, "action": action}
        if interval_seconds is not None:
            job["interval_seconds"] = interval_seconds
        if cron_expr is not None:
            job["cron"] = cron_expr
        if args is not None:
            job["args"] = args

        try:
            added = self._add_job_to_scheduler(job)
            if not added:
                return {
                    "success": False,
                    "name": name,
                    "error": "Failed to add job to scheduler — check logs for details",
                }
            self._persist_json_job(job)
            logger.info("Added job %s for %s", name, self._agent_id)
            return {"success": True, "name": name}
        except Exception as exc:
            logger.exception("Failed to add job %s for %s", name, self._agent_id)
            return {
                "success": False,
                "name": name,
                "error": f"Unexpected error adding job: {exc}",
            }

    async def remove_job(self, name: str) -> bool:
        if self._scheduler is None:
            return False
        job_id = _make_job_id(self._agent_id, name)
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            logger.warning("Job %s not found in scheduler for removal", name)
        removed = self._remove_json_job(name)
        logger.info("Removed job %s for %s (json=%s)", name, self._agent_id, removed)
        return True

    async def list_jobs(self) -> list[dict]:
        if self._scheduler is None:
            return []
        jobs = self._scheduler.get_jobs()
        result = []
        for job in jobs:
            entry: dict[str, Any] = {
                "id": job.id,
                "name": job.id.removeprefix(f"{self._agent_id}_"),
                "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            }
            if job.kwargs:
                entry["action"] = job.kwargs.get("action")
                entry["args"] = job.kwargs.get("args")
            result.append(entry)
        return result

    async def reload(self, yaml_schedules: dict | None = None) -> None:
        if self._scheduler is None:
            return
        if yaml_schedules is not None:
            self._yaml_schedules = yaml_schedules
        self._scheduler.remove_all_jobs()
        yaml_jobs = self._load_schedules(self._yaml_schedules)
        json_jobs = self._load_json_schedules()
        all_jobs = self._merge_jobs(yaml_jobs, json_jobs)
        added = 0
        for job in all_jobs:
            if self._add_job_to_scheduler(job):
                added += 1
        logger.info("Reloaded scheduler for %s with %d/%d jobs added", self._agent_id, added, len(all_jobs))

    def _persist_json_job(self, job: dict) -> None:
        existing = self._load_json_schedules_raw()
        existing_by_name = {j["name"]: j for j in existing}
        job_copy = {k: v for k, v in job.items() if k != "source"}
        existing_by_name[job["name"]] = job_copy
        self._write_json_file(list(existing_by_name.values()))

    def _remove_json_job(self, name: str) -> bool:
        existing = self._load_json_schedules_raw()
        filtered = [j for j in existing if j.get("name") != name]
        if len(filtered) == len(existing):
            return False
        self._write_json_file(filtered)
        return True

    def _load_json_schedules_raw(self) -> list[dict]:
        if not self._json_path.exists():
            return []
        try:
            data = json.loads(self._json_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    def _write_json_file(self, jobs: list[dict]) -> None:
        self._schedules_dir.mkdir(parents=True, exist_ok=True)
        self._json_path.write_text(
            json.dumps(jobs, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
