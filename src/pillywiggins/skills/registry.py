import importlib.util
import json
import logging
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

    async def execute(self, **kwargs) -> Any:
        return await self.run_func(**kwargs)


class SkillRegistry:
    def __init__(self, skills_dir: Optional[Path] = None):
        self._skills_dir = skills_dir or DEFAULT_SKILLS_DIR
        self._skills: dict[str, Skill] = {}

    def load_all(self) -> list[Skill]:
        self._skills.clear()
        if not self._skills_dir.exists():
            logger.info("Skills directory %s does not exist", self._skills_dir)
            return []

        for skill_file in sorted(self._skills_dir.glob("*.py")):
            if skill_file.name.startswith("_"):
                continue
            try:
                skill = self._load_skill_file(skill_file)
                if skill is not None:
                    self._skills[skill.name] = skill
                    logger.info("Loaded skill: %s", skill.name)
            except Exception:
                logger.exception("Failed to load skill from %s", skill_file)

        # Ensure registry.json reflects the filesystem truth
        self._sync_registry_json()

        return list(self._skills.values())

    def _sync_registry_json(self) -> None:
        """Rebuild registry.json from the in-memory skills dict.

        This makes the filesystem the primary source of truth and
        keeps registry.json consistent for any external consumers."""
        registry_path = self._skills_dir / "registry.json"
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
        registry_path.write_text(json.dumps(registry, indent=2))

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
        registry = {}
        if registry_path.exists():
            registry = json.loads(registry_path.read_text())
        existing = registry.get("skills", [])
        if name not in [s["name"] for s in existing]:
            existing.append({"name": name, "description": meta.get("description", ""), "file": f"{name}.py"})
        registry["skills"] = existing
        registry_path.write_text(json.dumps(registry, indent=2))

        skill = self._load_skill_file(skill_path)
        if skill is not None:
            self._skills[skill.name] = skill
        return skill

    def has_skill(self, name: str) -> bool:
        return name in self._skills