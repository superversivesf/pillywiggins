import importlib
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from pillywiggins.health import check_health, create_health_app


def _make_mock_nats():
    mock_nc = AsyncMock()
    mock_nc.close = AsyncMock()
    mock_mod = MagicMock()
    mock_mod.connect = AsyncMock(return_value=mock_nc)
    return mock_mod


@pytest.fixture(autouse=True)
def _mock_nats_module():
    """Inject a mock ``nats`` module so that ``importlib.reload(health)``
    never triggers a real NATS connection attempt inside any test.
    """
    mock_mod = _make_mock_nats()
    real_nats = sys.modules.get("nats")
    sys.modules["nats"] = mock_mod
    yield
    if real_nats is not None:
        sys.modules["nats"] = real_nats
    elif "nats" in sys.modules:
        del sys.modules["nats"]


@pytest.fixture
def settings():
    s = MagicMock()
    s.database_url = "postgresql://test:test@localhost:5432/testdb"
    s.redis_url = "redis://localhost:6379/0"
    s.llm_base_url = "http://localhost:11434"
    s.nats_url = "nats://localhost:4222"
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


def _make_capturing_aiohttp_client():
    """Return an aiohttp mock that captures the GET URL in a non-async way."""
    captured_url = None

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    def capture_get(url):
        nonlocal captured_url
        captured_url = url
        return mock_resp

    mock_session = MagicMock()
    mock_session.get = capture_get
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_aiohttp = MagicMock()
    mock_aiohttp.ClientSession = MagicMock(return_value=mock_session)
    return mock_aiohttp, (lambda: captured_url)


def _make_mock_nats():
    mock_nc = AsyncMock()
    mock_nc.close = AsyncMock()
    mock_mod = MagicMock()
    mock_mod.connect = AsyncMock(return_value=mock_nc)
    return mock_mod


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


@pytest.mark.asyncio
async def test_start_health_server_returns_runner(settings):
    from pillywiggins.health import start_health_server

    with (
        patch("pillywiggins.health.web.AppRunner") as mock_runner_cls,
        patch("pillywiggins.health.web.TCPSite") as mock_site_cls,
    ):
        mock_runner = AsyncMock()
        mock_runner.setup = AsyncMock()
        mock_runner_cls.return_value = mock_runner
        mock_site = AsyncMock()
        mock_site.start = AsyncMock()
        mock_site_cls.return_value = mock_site

        runner = await start_health_server(settings, host="127.0.0.1", port=9999)

    assert runner is mock_runner
    mock_runner.setup.assert_called_once()
    mock_site.start.assert_called_once()


@pytest.mark.asyncio
async def test_check_health_llm_non_200_status(settings):
    mock_asyncpg = _make_mock_asyncpg()
    mock_redis = _make_mock_redis()
    mock_aiohttp = _make_mock_aiohttp_client(status=503)

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
    assert result["checks"]["redis"] == "ok"
    assert "error" in result["checks"]["llm"]
    assert "503" in result["checks"]["llm"]


@pytest.mark.asyncio
async def test_check_health_postgres_connect_fails(settings):
    mock_asyncpg = MagicMock()
    mock_asyncpg.connect = AsyncMock(side_effect=Exception("postgres refused"))
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

    assert result["status"] == "degraded"
    assert "error" in result["checks"]["postgres"]
    assert result["checks"]["redis"] == "ok"
    assert result["checks"]["llm"] == "ok"


@pytest.mark.asyncio
async def test_healthz_handler_returns_checks_dict(aiohttp_client, settings):
    with patch("pillywiggins.health.check_health", new_callable=AsyncMock) as mock_check:
        mock_check.return_value = {
            "status": "degraded",
            "checks": {
                "postgres": "error: timeout",
                "redis": "ok",
                "llm": "ok",
            },
        }
        app = create_health_app(settings)
        client = await aiohttp_client(app)
        resp = await client.get("/healthz")

        assert resp.status == 503
        body = await resp.json()
        assert "checks" in body
        assert body["checks"]["postgres"] == "error: timeout"


@pytest.mark.asyncio
async def test_create_health_app_stores_settings(settings):
    app = create_health_app(settings)
    from pillywiggins.health import SETTINGS_KEY

    assert app[SETTINGS_KEY] is settings


# ---- Tests for LLM URL bug and NATS check ----


@pytest.mark.asyncio
async def test_check_health_llm_url_strips_v1_suffix(settings):
    """When llm_base_url ends with /v1, the health check must strip it before /api/tags."""
    settings.llm_base_url = "http://localhost:11434/v1"

    mock_asyncpg = _make_mock_asyncpg()
    mock_redis = _make_mock_redis()
    mock_aiohttp, get_captured_url = _make_capturing_aiohttp_client()

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

    assert result["checks"]["llm"] == "ok"
    assert get_captured_url() == "http://localhost:11434/api/tags", (
        f"Expected Ollama API URL without /v1 suffix, got: {get_captured_url()}"
    )


@pytest.mark.asyncio
async def test_check_health_llm_url_without_v1_suffix(settings):
    """When llm_base_url has no /v1 suffix, the health check should use it directly."""
    settings.llm_base_url = "http://localhost:11434"

    mock_asyncpg = _make_mock_asyncpg()
    mock_redis = _make_mock_redis()
    mock_aiohttp, get_captured_url = _make_capturing_aiohttp_client()

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

    assert result["checks"]["llm"] == "ok"
    assert get_captured_url() == "http://localhost:11434/api/tags", (
        f"Expected Ollama API URL, got: {get_captured_url()}"
    )


@pytest.mark.asyncio
async def test_check_health_includes_nats(settings):
    """NATS connectivity must be checked and reported in health checks."""
    mock_asyncpg = _make_mock_asyncpg()
    mock_redis = _make_mock_redis()
    mock_aiohttp = _make_mock_aiohttp_client(status=200)

    mock_nats = MagicMock()
    mock_nc = AsyncMock()
    mock_nc.close = AsyncMock()
    mock_nats.connect = AsyncMock(return_value=mock_nc)

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
        sys.modules["nats"] = mock_nats

        from pillywiggins import health

        importlib.reload(health)
        result = await health.check_health(settings)
    finally:
        for key in ("asyncpg", "redis", "redis.asyncio", "aioredis", "aiohttp", "nats"):
            if key in sys.modules:
                del sys.modules[key]
        for key, val in saved.items():
            sys.modules[key] = val
        if real_aiohttp:
            sys.modules["aiohttp"] = real_aiohttp
        from pillywiggins import health

        importlib.reload(health)

    assert "nats" in result["checks"], (
        f"NATS check missing from health checks: {result['checks'].keys()}"
    )
    assert result["checks"]["nats"] == "ok"
    mock_nats.connect.assert_awaited_once_with(settings.nats_url)
    mock_nc.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_health_nats_failure_is_degraded(settings):
    """When NATS is unreachable, health status should be degraded."""
    mock_asyncpg = _make_mock_asyncpg()
    mock_redis = _make_mock_redis()
    mock_aiohttp = _make_mock_aiohttp_client(status=200)

    mock_nats = MagicMock()
    mock_nats.connect = AsyncMock(side_effect=Exception("nats connection refused"))

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
        sys.modules["nats"] = mock_nats

        from pillywiggins import health

        importlib.reload(health)
        result = await health.check_health(settings)
    finally:
        for key in ("asyncpg", "redis", "redis.asyncio", "aioredis", "aiohttp", "nats"):
            if key in sys.modules:
                del sys.modules[key]
        for key, val in saved.items():
            sys.modules[key] = val
        if real_aiohttp:
            sys.modules["aiohttp"] = real_aiohttp
        from pillywiggins import health

        importlib.reload(health)

    assert result["status"] == "degraded"
    assert "nats" in result["checks"]
    assert "error" in result["checks"]["nats"]
    assert "nats connection refused" in result["checks"]["nats"]
