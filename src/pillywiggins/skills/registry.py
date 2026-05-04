import asyncio
import importlib.util
import inspect
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

VALID_PERMISSIONS = {"network", "subprocess", "file_write"}


class Skill:
    def __init__(self, name: str, description: str, run_func, meta: dict, permissions: dict, file_path: Optional[Path] = None):
        self.name = name
        self.description = description
        self.run_func = run_func
        self.meta = meta
        self.permissions = permissions
        self.file_path = file_path

    def __repr__(self):
        return f"Skill(name={self.name!r})"

    async def execute(self, *, agent_id: str = "unknown", channel: str = "unknown", **kwargs) -> Any:
        from pillywiggins.skills.logger import log_skill_execution
        try:
            result = await self.run_func(**kwargs)
        except Exception as exc:
            log_skill_execution(agent_id, channel, self.name, kwargs, result=None, exception=str(exc))
            raise
        log_skill_execution(agent_id, channel, self.name, kwargs, result=result)
        return result

    def as_tool(self) -> "Tool":
        """Return a PydanticAI Tool wrapping this skill.

        Introspects SKILL_META parameters to build an explicit function
        signature so PydanticAI can generate the correct JSON schema for
        the LLM.  The tool calls the skill's :meth:`run` function via
        :meth:`execute` and serialises the result to a string (or JSON
        when the raw result is not a string).
        """
        from pydantic_ai.tools import Tool
        import inspect

        params = self.meta.get("parameters", {})

        # Build explicit signature from SKILL_META so PydanticAI knows the
        # expected arguments and their types.
        sig_params: list[inspect.Parameter] = []
        for pname, pdef in params.items():
            ptype = pdef.get("type", "string")
            if ptype == "integer":
                annotation = int
            elif ptype == "boolean":
                annotation = bool
            elif ptype in ("number", "float"):
                annotation = float
            else:
                annotation = str

            default = pdef.get("default", inspect.Parameter.empty)
            sig_params.append(
                inspect.Parameter(
                    pname,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=default,
                    annotation=annotation,
                )
            )

        async def _skill_wrapper(**kwargs) -> str:
            result = await self.execute(**kwargs)
            if isinstance(result, str):
                return result
            return json.dumps(result)

        # Attach explicit signature and annotations so PydanticAI generates
        # the JSON schema from SKILL_META rather than bare **kwargs.
        _skill_wrapper.__signature__ = inspect.Signature(
            sig_params, return_annotation=str
        )
        _skill_wrapper.__annotations__ = {
            p.name: p.annotation for p in sig_params
        }
        _skill_wrapper.__annotations__["return"] = str
        _skill_wrapper.__name__ = self.name

        # Build Google-style docstring for parameter descriptions.
        doc_lines = [self.description, ""]
        if params:
            doc_lines.append("Args:")
            for pname, pdef in params.items():
                pdesc = pdef.get("description", "")
                line = f"    {pname}"
                if pdesc:
                    line += f": {pdesc}"
                pdefault = pdef.get("default")
                if pdefault is not None:
                    line += f" (default: {pdefault})"
                doc_lines.append(line)
        _skill_wrapper.__doc__ = "\n".join(doc_lines)

        return Tool(
            _skill_wrapper,
            name=self.name,
            description=self.description,
        )


class SkillRegistry:
    def __init__(
        self,
        skills_dir: Optional[Path] = None,
        agent_id: Optional[str] = None,
        nats_bus=None,
    ):
        self._skills_dir = skills_dir or DEFAULT_SKILLS_DIR
        self._skills: dict[str, Skill] = {}
        self.load_errors: list[str] = []
        self._watch_task: Optional[asyncio.Task] = None
        self._watcher_running = False
        self._last_snapshot: dict[str, float] = {}
        self._agent_id = agent_id
        self._nats_bus = nats_bus

    def _snapshot_skills(self) -> dict[str, float]:
        """Return a snapshot of skill files and their mtimes."""
        snap: dict[str, float] = {}
        if not self._skills_dir.exists():
            return snap
        for skill_file in self._skills_dir.glob("*.py"):
            if skill_file.name.startswith("_"):
                continue
            try:
                snap[skill_file.name] = skill_file.stat().st_mtime
            except OSError:
                pass
        return snap

    def watch_for_changes(self, interval: float = 10.0) -> None:
        """Start an asyncio polling task that reloads skills when files change.

        This is the high-level entrypoint intended for agent startup.
        It delegates to :meth:`start_watching` with a 10-second default.
        """
        self.start_watching(interval=interval)

    def start_watching(self, interval: float = 5.0) -> None:
        """Start an asyncio polling task that reloads skills when files change."""
        if self._watcher_running:
            logger.warning("Skill filesystem watcher is already running")
            return
        self._watcher_running = True
        self._last_snapshot = self._snapshot_skills()
        self._watch_task = asyncio.create_task(self._watch_loop(interval))
        logger.info("Started skill filesystem watcher (interval=%ss)", interval)

    async def _watch_loop(self, interval: float) -> None:
        while self._watcher_running:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            if not self._watcher_running:
                break
            current = self._snapshot_skills()
            if current != self._last_snapshot:
                logger.info("Skills directory changed, reloading...")
                self.load_all()
                self._sync_registry_json()
                self._last_snapshot = current
                await self._notify_reload()

    def stop_watching(self) -> None:
        """Stop the filesystem watcher task."""
        if not self._watcher_running:
            return
        self._watcher_running = False
        if self._watch_task is not None:
            self._watch_task.cancel()
            self._watch_task = None
        logger.info("Stopped skill filesystem watcher")

    async def _notify_reload(self) -> None:
        """Notify other agents via NATS that skills have changed."""
        if self._nats_bus is None:
            return
        try:
            await self._nats_bus.publish_broadcast(
                "skill_published",
                {
                    "agent_id": self._agent_id or "unknown",
                    "action": "reload",
                },
            )
            logger.info(
                "Broadcasted skill reload notification from %s",
                self._agent_id or "unknown",
            )
        except Exception:
            logger.warning("Failed to broadcast skill reload notification", exc_info=True)

    def broadcast_reload(self) -> None:
        """Synchronous facade to broadcast a reload notification.

        Schedules :meth:`_notify_reload` on the running event loop if one is present.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("No running event loop; cannot broadcast skill reload")
            return
        loop.create_task(self._notify_reload())

    def load_all(self) -> list[Skill]:
        self._skills.clear()
        self.load_errors.clear()
        if not self._skills_dir.exists():
            logger.info("Skills directory %s does not exist", self._skills_dir)
            return []

        registry_path = self._skills_dir / "registry.json"
        registry: dict = {"skills": []}
        if registry_path.exists():
            try:
                registry = json.loads(registry_path.read_text())
                if not isinstance(registry, dict):
                    logger.warning("registry.json root is not a dict, resetting")
                    registry = {"skills": []}
            except Exception as exc:
                logger.warning("Failed to read registry.json: %s", exc)
                registry = {"skills": []}

        reg_entries = registry.get("skills", [])
        if not isinstance(reg_entries, list):
            reg_entries = []
            registry["skills"] = reg_entries

        reg_files = {e.get("file") for e in reg_entries if e.get("file")}

        # Scan disk for .py files not tracked in registry.json
        disk_files = {p.name for p in self._skills_dir.glob("*.py") if not p.name.startswith("_")}
        missing_from_reg = disk_files - reg_files

        if missing_from_reg:
            logger.warning(
                "registry.json out of sync with disk (missing entries: %s). Adding them.",
                sorted(missing_from_reg),
            )
            for fname in sorted(missing_from_reg):
                fpath = self._skills_dir / fname
                try:
                    skill = self._load_skill_file(fpath)
                    if skill is not None:
                        reg_entries.append({
                            "name": skill.name,
                            "description": skill.description,
                            "file": fname,
                        })
                    else:
                        logger.warning("Could not load skill %s to add to registry", fname)
                except Exception as exc:
                    err_msg = f"Failed to auto-register skill {fname}: {exc}"
                    logger.warning(err_msg, exc_info=True)
                    self.load_errors.append(err_msg)
            self._write_registry_json(registry)
            # Update reg_entries after rewrite
            reg_entries = registry.get("skills", [])

        # Load skills from registry entries (source of truth)
        for entry in reg_entries:
            fname = entry.get("file")
            if not fname:
                continue
            fpath = self._skills_dir / fname
            if not fpath.exists():
                err_msg = f"Skill file listed in registry.json but missing on disk: {fname}"
                logger.error(err_msg)
                self.load_errors.append(err_msg)
                continue
            try:
                skill = self._load_skill_file(fpath)
                if skill is not None:
                    self._skills[skill.name] = skill
                    logger.info("Loaded skill: %s", skill.name)
            except Exception as exc:
                err_msg = f"Failed to load skill from {fpath}: {exc}"
                logger.error(err_msg, exc_info=True)
                self.load_errors.append(err_msg)

        return list(self._skills.values())

    def _write_registry_json(self, registry: dict) -> None:
        """Atomically write the registry dict to registry.json."""
        registry_path = self._skills_dir / "registry.json"
        tmp_path = self._skills_dir / "registry.json.tmp"
        tmp_path.write_text(json.dumps(registry, indent=2))
        os.replace(str(tmp_path), str(registry_path))

    def _sync_registry_json(self) -> None:
        """Rebuild registry.json from the in-memory skills dict.

        This makes the filesystem the primary source of truth and
        keeps registry.json consistent for any external consumers.
        """
        registry = {
            "skills": [
                {
                    "name": name,
                    "description": skill.description,
                    "file": f"{name}.py",
                }
                for name, skill in sorted(self._skills.items())
            ]
        }
        self._write_registry_json(registry)

    def _load_skill_file(self, path: Path) -> Optional[Skill]:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        meta = getattr(module, "SKILL_META", None)
        if meta is None:
            logger.warning("Skill %s has no SKILL_META", path)
            return None

        run_func = getattr(module, "run", None)
        if run_func is None:
            logger.warning("Skill %s has no run() function", path)
            return None

        if not inspect.iscoroutinefunction(run_func):
            logger.error("Skill %s run() is not a coroutine function", path)
            return None

        name = meta.get("name", path.stem)
        description = meta.get("description", "")
        permissions = self._parse_permissions(meta)

        return Skill(name=name, description=description, run_func=run_func, meta=meta, permissions=permissions, file_path=path)

    def _parse_permissions(self, meta: dict) -> dict[str, bool]:
        legacy_network = meta.get("network_access", False)
        declared = meta.get("permissions", {})
        permissions = {p: declared.get(p, False) for p in VALID_PERMISSIONS}
        if legacy_network and not permissions.get("network"):
            permissions["network"] = True
        return permissions

    def list_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def get_skill(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def register_skill(self, name: str, code: str, meta: dict) -> Skill:
        skill_path = self._skills_dir / f"{name}.py"
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(code)

        registry_path = self._skills_dir / "registry.json"
        registry: dict = {"skills": []}
        if registry_path.exists():
            try:
                registry = json.loads(registry_path.read_text())
                if not isinstance(registry, dict):
                    registry = {"skills": []}
            except Exception:
                registry = {"skills": []}
        existing = registry.get("skills", [])
        if not isinstance(existing, list):
            existing = []
            registry["skills"] = existing
        if name not in [s["name"] for s in existing]:
            existing.append({"name": name, "description": meta.get("description", ""), "file": f"{name}.py"})
        registry["skills"] = existing

        self._write_registry_json(registry)

        skill = self._load_skill_file(skill_path)
        if skill is not None:
            self._skills[skill.name] = skill
        return skill

    def has_skill(self, name: str) -> bool:
        return name in self._skills

    def get_status(self) -> dict[str, Any]:
        return {
            "loaded": len(self._skills),
            "errors": list(self.load_errors),
        }
