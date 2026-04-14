import importlib
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from pillywiggins.health import check_health, create_health_app


@pytest.fixture
def settings():
    s = MagicMock()
    s.database_url = "postgresql://test:test@localhost:5432/testdb"
    s.redis_url = "redis://localhost:6379/0"
    s.llm_base_url = "http://localhost:11434"
    return s


def _make_mock_asyncpg():
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=None)
    mock_conn.close = AsyncMock()
    mock_mod = MagicMock()
    mock_mod.connect = AsyncMock(return_value=mock_conn)
    return mock_mod


def _make_mock_redis():
    mock_r = AsyncMock()
    mock_r.ping = AsyncMock(return_value=True)
    mock_r.close = AsyncMock()
    mock_mod = MagicMock()
    mock_mod.from_url = MagicMock(return_value=mock_r)
    return mock_mod


def _make_mock_aiohttp_client(status=200):
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_aiohttp = MagicMock()
    mock_aiohttp.ClientSession = MagicMock(return_value=mock_session)
    return mock_aiohttp


@pytest.mark.asyncio
async def test_healthz_returns_json_when_ok(aiohttp_client, settings):
    with patch("pillywiggins.health.check_health", new_callable=AsyncMock) as mock_check:
        mock_check.return_value = {
            "status": "ok",
            "checks": {"postgres": "ok", "redis": "ok", "llm": "ok"},
        }
        app = create_health_app(settings)
        client = await aiohttp_client(app)
        resp = await client.get("/healthz")

        assert resp.status == 200
        body = await resp.json()
        assert body["status"] == "ok"
        assert body["checks"]["postgres"] == "ok"
        assert body["checks"]["redis"] == "ok"
        assert body["checks"]["llm"] == "ok"


@pytest.mark.asyncio
async def test_healthz_returns_503_when_degraded(aiohttp_client, settings):
    with patch("pillywiggins.health.check_health", new_callable=AsyncMock) as mock_check:
        mock_check.return_value = {
            "status": "degraded",
            "checks": {
                "postgres": "ok",
                "redis": "ok",
                "llm": "error: connection refused",
            },
        }
        app = create_health_app(settings)
        client = await aiohttp_client(app)
        resp = await client.get("/healthz")

        assert resp.status == 503
        body = await resp.json()
        assert body["status"] == "degraded"


@pytest.mark.asyncio
async def test_check_health_all_services_ok(settings):
    mock_asyncpg = _make_mock_asyncpg()
    mock_redis = _make_mock_redis()
    mock_aiohttp = _make_mock_aiohttp_client(status=200)

    saved = {}
    for key in ("asyncpg", "redis", "redis.asyncio", "aioredis"):
        if key in sys.modules:
            saved[key] = sys.modules.pop(key)

    try:
        sys.modules["asyncpg"] = mock_asyncpg
        redis_mod = ModuleType("redis")
        sys.modules["redis"] = redis_mod
        sys.modules["redis.asyncio"] = mock_redis
        sys.modules["aioredis"] = mock_redis

        real_aiohttp = sys.modules.get("aiohttp")
        sys.modules["aiohttp"] = mock_aiohttp

        from pillywiggins import health
        importlib.reload(health)
        result = await health.check_health(settings)
    finally:
        for key in ("asyncpg", "redis", "redis.asyncio", "aioredis", "aiohttp"):
            if key in sys.modules:
                del sys.modules[key]
        for key, val in saved.items():
            sys.modules[key] = val
        if real_aiohttp:
            sys.modules["aiohttp"] = real_aiohttp
        from pillywiggins import health
        importlib.reload(health)

    assert result["status"] == "ok"
    assert result["checks"]["postgres"] == "ok"
    assert result["checks"]["redis"] == "ok"
    assert result["checks"]["llm"] == "ok"


@pytest.mark.asyncio
async def test_check_health_all_services_down(settings):
    mock_asyncpg = MagicMock()
    mock_asyncpg.connect = AsyncMock(side_effect=Exception("connection refused"))
    mock_redis = MagicMock()
    mock_redis.from_url = MagicMock(side_effect=Exception("connection refused"))
    mock_aiohttp = MagicMock()
    mock_aiohttp.ClientSession = MagicMock(side_effect=Exception("connection refused"))

    saved = {}
    for key in ("asyncpg", "redis", "redis.asyncio", "aioredis"):
        if key in sys.modules:
            saved[key] = sys.modules.pop(key)

    try:
        sys.modules["asyncpg"] = mock_asyncpg
        redis_mod = ModuleType("redis")
        sys.modules["redis"] = redis_mod
        sys.modules["redis.asyncio"] = mock_redis
        sys.modules["aioredis"] = mock_redis

        real_aiohttp = sys.modules.get("aiohttp")
        sys.modules["aiohttp"] = mock_aiohttp

        from pillywiggins import health
        importlib.reload(health)
        result = await health.check_health(settings)
    finally:
        for key in ("asyncpg", "redis", "redis.asyncio", "aioredis", "aiohttp"):
            if key in sys.modules:
                del sys.modules[key]
        for key, val in saved.items():
            sys.modules[key] = val
        if real_aiohttp:
            sys.modules["aiohttp"] = real_aiohttp
        from pillywiggins import health
        importlib.reload(health)

    assert result["status"] == "degraded"
    assert "error" in result["checks"]["postgres"]
    assert "error" in result["checks"]["redis"]
    assert "error" in result["checks"]["llm"]


@pytest.mark.asyncio
async def test_check_health_partial_degradation(settings):
    mock_asyncpg = _make_mock_asyncpg()
    mock_redis = MagicMock()
    mock_redis.from_url = MagicMock(side_effect=Exception("redis down"))
    mock_aiohttp = _make_mock_aiohttp_client(status=200)

    saved = {}
    for key in ("asyncpg", "redis", "redis.asyncio", "aioredis"):
        if key in sys.modules:
            saved[key] = sys.modules.pop(key)

    try:
        sys.modules["asyncpg"] = mock_asyncpg
        redis_mod = ModuleType("redis")
        sys.modules["redis"] = redis_mod
        sys.modules["redis.asyncio"] = mock_redis
        sys.modules["aioredis"] = mock_redis

        real_aiohttp = sys.modules.get("aiohttp")
        sys.modules["aiohttp"] = mock_aiohttp

        from pillywiggins import health
        importlib.reload(health)
        result = await health.check_health(settings)
    finally:
        for key in ("asyncpg", "redis", "redis.asyncio", "aioredis", "aiohttp"):
            if key in sys.modules:
                del sys.modules[key]
        for key, val in saved.items():
            sys.modules[key] = val
        if real_aiohttp:
            sys.modules["aiohttp"] = real_aiohttp
        from pillywiggins import health
        importlib.reload(health)

    assert result["status"] == "degraded"
    assert result["checks"]["postgres"] == "ok"
    assert "error" in result["checks"]["redis"]
    assert result["checks"]["llm"] == "ok"


@pytest.mark.asyncio
async def test_create_health_app_registers_route(settings):
    app = create_health_app(settings)
    routes = [r.resource.canonical for r in app.router.routes()]
    assert "/healthz" in routes