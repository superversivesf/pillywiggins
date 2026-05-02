"""List all registered skills via the registry."""

SKILL_META = {
    "name": "debug_list_skills",
    "description": "List all registered skills. Returns name, description, tags, and permissions for each.",
    "tags": ["debug", "diagnostic", "skills", "registry"],
    "permissions": {
        "network": False,
        "subprocess": False,
        "file_write": False,
    },
}


async def run(**kwargs) -> dict:
    deps = kwargs.get("deps")
    if deps is not None and getattr(deps, "skill_registry", None) is not None:
        registry = deps.skill_registry
    else:
        from pathlib import Path
        from pillywiggins.skills.registry import SkillRegistry
        from pillywiggins.config import Settings

        settings = Settings()
        skills_dir = Path(settings.skills_dir) if settings.skills_dir else None
        registry = SkillRegistry(skills_dir=skills_dir)
        registry.load_all()

    skills = registry.list_skills()
    results = []
    for skill in skills:
        meta = getattr(skill, "meta", {}) or {}
        results.append(
            {
                "name": skill.name,
                "description": skill.description,
                "tags": meta.get("tags", []),
                "permissions": skill.permissions,
            }
        )

    status = registry.get_status() if hasattr(registry, "get_status") else {}

    return {
        "count": len(results),
        "skills": results,
        "load_errors": status.get("errors", []),
        "loaded": status.get("loaded", len(results)),
    }
