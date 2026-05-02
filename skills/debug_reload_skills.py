"""Force a skill registry reload and report changes."""

SKILL_META = {
    "name": "debug_reload_skills",
    "description": "Call skill_registry.load_all() and compare before/after lists. Report new, removed, and changed skills.",
    "tags": ["debug", "diagnostic", "skills", "registry"],
    "permissions": {
        "network": False,
        "subprocess": False,
        "file_write": False,
    },
}


async def run(**kwargs) -> dict:
    from pathlib import Path

    from pillywiggins.config import Settings
    from pillywiggins.skills.registry import SkillRegistry

    settings = Settings()
    deps = kwargs.get("deps")

    if deps is not None and getattr(deps, "skill_registry", None) is not None:
        registry = deps.skill_registry
    else:
        skills_dir = Path(settings.skills_dir) if settings.skills_dir else None
        registry = SkillRegistry(skills_dir=skills_dir)
        registry.load_all()

    before = {s.name: s.description for s in registry.list_skills()}

    after_skills = registry.load_all()
    after = {s.name: s.description for s in after_skills}

    before_keys = set(before.keys())
    after_keys = set(after.keys())

    new_skills = sorted(after_keys - before_keys)
    removed_skills = sorted(before_keys - after_keys)
    changed_skills = sorted(
        k for k in (before_keys & after_keys) if before[k] != after[k]
    )

    status = registry.get_status() if hasattr(registry, "get_status") else {}

    return {
        "success": True,
        "before_count": len(before),
        "after_count": len(after),
        "new": new_skills,
        "removed": removed_skills,
        "changed": changed_skills,
        "load_errors": status.get("errors", []),
    }
