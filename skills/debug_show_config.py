"""Dump current agent configuration from Settings."""

SKILL_META = {
    "name": "debug_show_config",
    "description": "Read Settings() and return formatted agent configuration: agent_id, model, embedding, database, redis, nats, llm_base_url, timezone.",
    "tags": ["debug", "diagnostic", "config"],
    "permissions": {
        "network": False,
        "subprocess": False,
        "file_write": False,
    },
}


async def run(**kwargs) -> dict:
    from pillywiggins.config import Settings

    settings = Settings()

    return {
        "agent_id": settings.agent_id,
        "model_name": settings.model_name,
        "embedding_model": settings.embedding_model,
        "embedding_dimension": settings.embedding_dimension,
        "database_url": _mask_password(settings.database_url),
        "redis_url": _mask_password(settings.redis_url),
        "nats_url": settings.nats_url,
        "llm_base_url": settings.llm_base_url,
        "timezone": settings.timezone,
        "channel": settings.channel,
        "llm_provider": settings.llm_provider,
        "skills_dir": settings.skills_dir,
        "scheduler_enabled": settings.scheduler_enabled,
    }


def _mask_password(url: str) -> str:
    """Mask password in a URL for safe display."""
    if "@" not in url:
        return url
    try:
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(url)
        if parsed.password:
            user = parsed.username or ""
            netloc = f"{user}:***@{parsed.hostname or ''}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse(
                (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
            )
    except Exception:
        pass
    return url
