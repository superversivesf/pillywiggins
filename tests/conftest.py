from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.agents.personality import Personality
from pillywiggins.config import Settings


# ---------------------------------------------------------------------------
# Pytest collection hook: auto-mark unmarked tests as unit
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(config, items):
    for item in items:
        # Exclude functions imported from src/ that pytest mis-collects as tests
        if item.nodeid.endswith("::test_skill_code"):
            item.add_marker(pytest.mark.skip(reason="Not a test, function from src/pillywiggins/agents/tools.py"))
            continue
        if not any(marker in item.keywords for marker in ("integration", "smoke")):
            item.add_marker(pytest.mark.unit)


# ---------------------------------------------------------------------------
# Docker availability fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def docker_available():
    import subprocess

    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=5)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("Docker not available", allow_module_level=True)


@pytest.fixture(scope="session")
def infra_services_running(docker_available):
    import subprocess

    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--services", "--filter", "status=running"],
            capture_output=True, text=True, check=False, timeout=10
        )
        running = set(result.stdout.strip().splitlines())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        running = set()

    required = {"postgres", "redis", "nats"}
    missing = required - running
    if missing:
        pytest.skip(f"Required services not running: {missing}")
    return running


# ---------------------------------------------------------------------------
# Default test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def personality():
    return Personality(
        name="puck",
        channel="telegram",
        description="A mischievous test fairy",
        system_prompt="You are Puck, a mischievous fairy.",
        traits=["playful", "trickster"],
        schedules=[{"interval": 60}],
    )


@pytest.fixture
def personality_file(personality, tmp_path):
    import yaml

    data = {
        "name": personality.name,
        "channel": personality.channel,
        "description": personality.description,
        "system_prompt": personality.system_prompt,
        "traits": personality.traits,
        "schedules": personality.schedules,
    }
    path = tmp_path / "personality.yaml"
    path.write_text(yaml.dump(data))
    return path


@pytest.fixture
def settings(tmp_path):
    return Settings(
        agent_id="puck",
        channel="telegram",
        personality_file=str(tmp_path / "telegram.yaml"),
        database_url="postgresql://pillywiggins:testpass@localhost:5432/pillywiggins_test",
        pg_password="testpass",
        redis_url="redis://localhost:6379/0",
        nats_url="nats://localhost:4222",
        llm_provider="ollama",
        llm_base_url="http://localhost:11434",
        llm_api_key="",
        model_name="qwen3.5:8b",
        embedding_model="nomic-embed-text",
        telegram_bot_token="",
    )


@pytest.fixture
def mock_agent(personality):
    agent = MagicMock(spec=PillywigginAgent)
    agent.agent_id = "puck"
    agent.personality = personality
    agent.model_name = "qwen3.5:8b"
    agent.provider = "ollama"
    agent.has_council_memory = False
    agent.has_nats_bus = False
    agent.skill_registry = None
    agent._lock = AsyncMock()
    agent._brain = MagicMock()
    agent.switch_model = MagicMock()
    agent.clear_history = AsyncMock()
    agent.handle_message = AsyncMock(return_value="response")
    return agent


@pytest.fixture
async def aiohttp_client():
    clients = []

    async def create_client(app: web.Application) -> TestClient:
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        clients.append(client)
        return client

    yield create_client

    for client in clients:
        await client.close()


# ---------------------------------------------------------------------------
# Autouse: provide valid DATABASE_URL / PG_PASSWORD for all tests.
# Security tests (e.g. test_config_security.py) use monkeypatch.delenv()
# to clear these and test the empty/'changeme' rejection paths.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_db_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://pillywiggins:testpass@postgres:5432/pillywiggins_test")
    monkeypatch.setenv("PG_PASSWORD", "testpass")
