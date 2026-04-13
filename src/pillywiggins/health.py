import logging

logger = logging.getLogger(__name__)


async def check_health(settings) -> dict:
    checks = {}

    try:
        import asyncpg

        conn = await asyncpg.connect(settings.database_url)
        await conn.execute("SELECT 1")
        await conn.close()
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.close()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{settings.ollama_base_url}/api/tags") as resp:
                checks["ollama"] = "ok" if resp.status == 200 else f"error: status {resp.status}"
    except Exception as e:
        checks["ollama"] = f"error: {e}"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    logger.info("Health check: %s — %s", overall, checks)
    return {"status": overall, "checks": checks}