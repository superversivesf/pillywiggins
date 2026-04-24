import logging

from aiohttp import web

logger = logging.getLogger(__name__)


SETTINGS_KEY = web.AppKey("settings", object)


def _normalize_ollama_url(base_url: str) -> str:
    """Strip OpenAI-compatible /v1 suffix so Ollama native endpoints work."""
    stripped = base_url.rstrip("/")
    if stripped.endswith("/v1"):
        stripped = stripped[:-3]
    return stripped.rstrip("/")


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

        ollama_url = _normalize_ollama_url(settings.llm_base_url)
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ollama_url}/api/tags") as resp:
                checks["llm"] = "ok" if resp.status == 200 else f"error: status {resp.status}"
    except Exception as e:
        checks["llm"] = f"error: {e}"

    try:
        import nats

        nc = await nats.connect(settings.nats_url)
        await nc.close()
        checks["nats"] = "ok"
    except Exception as e:
        checks["nats"] = f"error: {e}"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    logger.info("Health check: %s — %s", overall, checks)
    return {"status": overall, "checks": checks}


async def _healthz_handler(request):
    settings = request.app[SETTINGS_KEY]
    result = await check_health(settings)
    if result["status"] == "ok":
        return web.json_response(result, status=200)
    return web.json_response(result, status=503)


def create_health_app(settings):
    app = web.Application()
    app[SETTINGS_KEY] = settings
    app.router.add_get("/healthz", _healthz_handler)
    return app


async def start_health_server(settings, host="0.0.0.0", port=8080):
    app = create_health_app(settings)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Healthz server listening on %s:%s", host, port)
    return runner
