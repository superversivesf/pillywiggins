"""NATS connectivity configuration tests.

These tests verify that the Docker Compose configuration, config settings,
and onboard wizard correctly set up NATS connectivity for agent containers.

They do NOT require an actual Docker daemon or NATS server — they test
the static configuration and code paths.
"""

import yaml
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pillywiggins.config import Settings
from pillywiggins.messaging.nats_bus import NatsBus, NatsConnectError, COUNCIL_STREAM


def test_council_stream_is_pillywiggins():
    assert COUNCIL_STREAM == "pillywiggins"


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestNatsConfig:
    def test_default_nats_url(self, monkeypatch):
        """Default NATS URL should point to the Docker Compose service hostname."""
        monkeypatch.delenv("NATS_URL", raising=False)
        s = Settings()
        assert s.nats_url == "nats://nats:4222"

    def test_nats_url_from_env(self, monkeypatch):
        """NATS_URL should be overridable via environment variable."""
        monkeypatch.setenv("NATS_URL", "nats://custom-nats:4222")
        s = Settings()
        assert s.nats_url == "nats://custom-nats:4222"

    def test_default_nats_connect_timeout(self, monkeypatch):
        monkeypatch.delenv("NATS_CONNECT_TIMEOUT", raising=False)
        s = Settings()
        assert s.nats_connect_timeout == 5.0

    def test_nats_connect_timeout_from_env(self, monkeypatch):
        monkeypatch.setenv("NATS_CONNECT_TIMEOUT", "10.0")
        s = Settings()
        assert s.nats_connect_timeout == 10.0

    def test_default_nats_reconnect_attempts(self, monkeypatch):
        monkeypatch.delenv("NATS_RECONNECT_ATTEMPTS", raising=False)
        s = Settings()
        assert s.nats_reconnect_attempts == 5

    def test_nats_reconnect_attempts_from_env(self, monkeypatch):
        monkeypatch.setenv("NATS_RECONNECT_ATTEMPTS", "10")
        s = Settings()
        assert s.nats_reconnect_attempts == 10


# ---------------------------------------------------------------------------
# Docker Compose networking tests
# ---------------------------------------------------------------------------


class TestDockerComposeNetworking:
    """Verify the docker-compose.yaml.example has correct network setup."""

    @pytest.fixture
    def compose_dir(self):
        return Path(__file__).resolve().parent.parent

    @pytest.fixture
    def compose_example(self, compose_dir):
        path = compose_dir / "docker-compose.yaml.example"
        if not path.exists():
            pytest.skip("docker-compose.yaml.example not found")
        return yaml.safe_load(path.read_text())

    def test_compose_has_networks_section(self, compose_example):
        """The compose file must define an explicit network."""
        assert "networks" in compose_example, (
            "docker-compose.yaml.example missing top-level 'networks' key. "
            "All services must be on the same explicit network for hostname resolution."
        )

    def test_network_has_pillywiggins(self, compose_example):
        """The compose file must define a 'pillywiggins' network."""
        assert "pillywiggins" in compose_example["networks"], (
            "docker-compose.yaml.example missing 'pillywiggins' network definition. "
            "Services need this to resolve each other by hostname."
        )

    def test_pillywiggins_network_is_bridge(self, compose_example):
        """The pillywiggins network should use bridge driver."""
        net = compose_example["networks"]["pillywiggins"]
        assert net.get("driver") == "bridge", (
            f"pillywiggins network should use bridge driver, got: {net}"
        )

    def test_nats_service_on_pillywiggins_network(self, compose_example):
        """The NATS service must be on the pillywiggins network."""
        nats_svc = compose_example["services"].get("nats")
        assert nats_svc is not None, "Missing 'nats' service"
        assert "networks" in nats_svc, (
            "NATS service missing 'networks' key — must join pillywiggins network"
        )
        assert "pillywiggins" in nats_svc["networks"], (
            "NATS service not on 'pillywiggins' network"
        )

    def test_agent_services_on_pillywiggins_network(self, compose_example):
        """All agent services must be on the pillywiggins network."""
        agent_services = []
        for name, svc in compose_example["services"].items():
            # Agent services are those with `build: .` (not images like postgres, redis, etc.)
            if svc.get("build") == ".":
                agent_services.append(name)

        for name in agent_services:
            svc = compose_example["services"][name]
            assert "networks" in svc, (
                f"Agent service '{name}' missing 'networks' key — must join pillywiggins network"
            )
            assert "pillywiggins" in svc["networks"], (
                f"Agent service '{name}' not on 'pillywiggins' network"
            )

    def test_agent_services_have_nats_url(self, compose_example):
        """All agent services must set NATS_URL in their environment."""
        agent_services = []
        for name, svc in compose_example["services"].items():
            if svc.get("build") == ".":
                agent_services.append(name)

        for name in agent_services:
            svc = compose_example["services"][name]
            env = svc.get("environment", {})
            assert "NATS_URL" in env, (
                f"Agent service '{name}' missing NATS_URL environment variable. "
                f"This is required for agents to connect to NATS by hostname."
            )
            # NATS_URL should point to the nats service hostname
            nats_url = env["NATS_URL"]
            assert "nats" in nats_url, (
                f"Agent service '{name}' has NATS_URL={nats_url} which doesn't reference the 'nats' hostname"
            )

    def test_nats_service_has_healthcheck(self, compose_example):
        """NATS service must have a healthcheck for depends_on condition."""
        nats_svc = compose_example["services"].get("nats")
        assert nats_svc is not None
        assert "healthcheck" in nats_svc, (
            "NATS service missing healthcheck — agents use 'condition: service_healthy'"
        )

    def test_agent_services_depend_on_healthy_nats(self, compose_example):
        """All agent services must depend on nats with service_healthy condition."""
        agent_services = []
        for name, svc in compose_example["services"].items():
            if svc.get("build") == ".":
                agent_services.append(name)

        for name in agent_services:
            svc = compose_example["services"][name]
            depends = svc.get("depends_on", {})
            assert "nats" in depends, (
                f"Agent service '{name}' missing 'nats' in depends_on"
            )
            nats_dep = depends["nats"]
            assert isinstance(nats_dep, dict), (
                f"Agent service '{name}' nats dependency should be dict with condition, got: {nats_dep}"
            )
            assert nats_dep.get("condition") == "service_healthy", (
                f"Agent service '{name}' depends_on nats should have condition: service_healthy, "
                f"got: {nats_dep}"
            )

    def test_infra_services_on_pillywiggins_network(self, compose_example):
        """All infrastructure services (postgres, redis, nats, searxng) must be on the network."""
        infra_services = ["postgres", "redis", "nats", "searxng"]
        for name in infra_services:
            svc = compose_example["services"].get(name)
            if svc is None:
                continue
            assert "networks" in svc, (
                f"Infrastructure service '{name}' missing 'networks' key"
            )
            assert "pillywiggins" in svc["networks"], (
                f"Infrastructure service '{name}' not on 'pillywiggins' network"
            )


# ---------------------------------------------------------------------------
# Onboard wizard network generation tests
# ---------------------------------------------------------------------------


class TestOnboardNetworkGeneration:
    """Verify that add_agent_to_docker_compose generates correct networking."""

    def test_add_agent_includes_nats_url(self, tmp_path):
        from pillywiggins.onboard import add_agent_to_docker_compose

        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))

        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )

        data = yaml.safe_load(compose_path.read_text())
        svc_env = data["services"]["puck"]["environment"]
        assert "NATS_URL" in svc_env, "add_agent_to_docker_compose must set NATS_URL"
        assert svc_env["NATS_URL"] == "nats://nats:4222"

    def test_add_agent_includes_networks(self, tmp_path):
        from pillywiggins.onboard import add_agent_to_docker_compose

        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))

        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )

        data = yaml.safe_load(compose_path.read_text())
        svc = data["services"]["puck"]
        assert "networks" in svc, "add_agent_to_docker_compose must set networks"
        assert "pillywiggins" in svc["networks"], (
            "Agent service must be on 'pillywiggins' network"
        )

    def test_add_agent_creates_networks_top_level_key(self, tmp_path):
        from pillywiggins.onboard import add_agent_to_docker_compose

        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))

        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )

        data = yaml.safe_load(compose_path.read_text())
        assert "networks" in data, "docker-compose.yaml must have top-level 'networks' key"
        assert "pillywiggins" in data["networks"], (
            "docker-compose.yaml must define 'pillywiggins' network"
        )
        assert data["networks"]["pillywiggins"]["driver"] == "bridge"

    def test_add_agent_depends_on_nats_healthy(self, tmp_path):
        from pillywiggins.onboard import add_agent_to_docker_compose

        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))

        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )

        data = yaml.safe_load(compose_path.read_text())
        svc = data["services"]["puck"]
        assert "nats" in svc["depends_on"], (
            "Agent service must depend on NATS"
        )
        nats_dep = svc["depends_on"]["nats"]
        assert nats_dep.get("condition") == "service_healthy", (
            f"Agent depends_on nats should be service_healthy, got: {nats_dep}"
        )

    def test_add_agent_to_existing_compose_preserves_networks(self, tmp_path):
        """If compose already has a pillywiggins network, adding an agent should keep it."""
        from pillywiggins.onboard import add_agent_to_docker_compose

        compose_path = tmp_path / "docker-compose.yaml"
        existing = {
            "services": {
                "postgres": {
                    "image": "pgvector/pgvector:pg16",
                    "networks": ["pillywiggins"],
                },
            },
            "networks": {
                "pillywiggins": {"driver": "bridge"},
            },
            "volumes": {},
        }
        compose_path.write_text(yaml.dump(existing))

        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )

        data = yaml.safe_load(compose_path.read_text())
        assert "pillywiggins" in data["networks"]
        assert data["networks"]["pillywiggins"]["driver"] == "bridge"
        assert "puck" in data["services"]


# ---------------------------------------------------------------------------
# NatsBus retry + config integration tests
# ---------------------------------------------------------------------------


class TestNatsBusConfigIntegration:
    """Test that NatsBus uses config settings correctly."""

    def test_bus_uses_settings_timeout(self, monkeypatch):
        monkeypatch.setenv("NATS_CONNECT_TIMEOUT", "15.0")
        monkeypatch.setenv("NATS_RECONNECT_ATTEMPTS", "10")
        s = Settings()
        bus = NatsBus(
            nats_url=s.nats_url,
            agent_id="puck",
            connect_timeout=s.nats_connect_timeout,
            reconnect_attempts=s.nats_reconnect_attempts,
        )
        assert bus._connect_timeout == 15.0
        assert bus._reconnect_attempts == 10

    def test_bus_default_url_matches_config(self, monkeypatch):
        """The default NATS URL in NatsBus and Settings should be consistent."""
        monkeypatch.delenv("NATS_URL", raising=False)
        s = Settings()
        # If no url is passed, the bus uses whatever the caller provides.
        # The convention is that the caller passes settings.nats_url.
        bus = NatsBus(nats_url=s.nats_url, agent_id="puck")
        assert bus._nats_url == "nats://nats:4222"

    @pytest.mark.asyncio
    async def test_connect_passes_timeout_to_nats_lib(self):
        """NatsBus.connect() should pass connect_timeout to nats.connect()."""
        bus = NatsBus(
            nats_url="nats://nats:4222",
            agent_id="puck",
            connect_timeout=8.0,
        )
        nc, js = MagicMock(), MagicMock()
        nc.jetstream.return_value = js
        js.add_stream = AsyncMock()

        with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc) as mock_connect:
            await bus.connect()

        mock_connect.assert_called_once()
        call_kwargs = mock_connect.call_args.kwargs
        assert call_kwargs["connect_timeout"] == 8.0


# ---------------------------------------------------------------------------
# Health check NATS integration tests
# ---------------------------------------------------------------------------


class TestHealthCheckNatsIntegration:
    """Test that the health check properly validates NATS + JetStream.

    These tests patch at the library level since health.py uses
    local imports inside check_health().
    """

    def _make_settings(self, nats_url="nats://nats:4222"):
        settings = MagicMock()
        settings.database_url = "postgresql://test:test@localhost:5432/testdb"
        settings.redis_url = "redis://localhost:6379/0"
        settings.llm_base_url = "http://localhost:11434/v1"
        settings.llm_api_key = "test"
        settings.llm_provider = "ollama"
        settings.embedding_model = "nomic-embed-text"
        settings.embedding_dimension = 768
        settings.nats_url = nats_url
        return settings

    @pytest.mark.asyncio
    async def test_nats_health_uses_nats_url_from_settings(self):
        settings = self._make_settings(nats_url="nats://custom-nats-host:4222")

        mock_js = MagicMock()
        mock_js.account_info = AsyncMock(return_value={"type": "account_info"})
        mock_nc = MagicMock()
        mock_nc.close = AsyncMock()
        mock_nc.jetstream = MagicMock(return_value=mock_js)

        with (
            patch("nats.connect", new_callable=AsyncMock, return_value=mock_nc) as mock_connect,
            patch("asyncpg.connect", new_callable=AsyncMock) as mock_pg,
            patch("redis.asyncio.from_url") as mock_redis_from_url,
            patch("aiohttp.ClientSession"),
            patch("pillywiggins.memory.embeddings.check_embedding_health", new_callable=AsyncMock, return_value={"healthy": True, "model": "test", "dimension": 768, "dimension_match": True, "expected_dimension": 768}),
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(return_value=None)
            mock_conn.close = AsyncMock()
            mock_pg.return_value = mock_conn

            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_redis.close = AsyncMock()
            mock_redis_from_url.return_value = mock_redis

            from pillywiggins.health import check_health
            result = await check_health(settings)

        mock_connect.assert_awaited_once_with("nats://custom-nats-host:4222")

    @pytest.mark.asyncio
    async def test_nats_health_calls_jetstream_account_info(self):
        settings = self._make_settings(nats_url="nats://nats:4222")

        mock_js = MagicMock()
        mock_js.account_info = AsyncMock(return_value={"type": "account_info"})
        mock_nc = MagicMock()
        mock_nc.close = AsyncMock()
        mock_nc.jetstream = MagicMock(return_value=mock_js)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("nats.connect", new_callable=AsyncMock, return_value=mock_nc),
            patch("asyncpg.connect", new_callable=AsyncMock) as mock_pg,
            patch("redis.asyncio.from_url") as mock_redis_from_url,
            patch("aiohttp.ClientSession", return_value=mock_session),
            patch("pillywiggins.memory.embeddings.check_embedding_health", new_callable=AsyncMock, return_value={"healthy": True, "model": "test", "dimension": 768, "dimension_match": True, "expected_dimension": 768}),
        ):
            mock_pg_conn = AsyncMock()
            mock_pg_conn.execute = AsyncMock(return_value=None)
            mock_pg_conn.close = AsyncMock()
            mock_pg.return_value = mock_pg_conn

            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_redis.close = AsyncMock()
            mock_redis_from_url.return_value = mock_redis

            from pillywiggins.health import check_health
            result = await check_health(settings)

        mock_js.account_info.assert_awaited_once()
        assert result["checks"]["nats"] == "ok"


# ---------------------------------------------------------------------------
# NatsConnectError export test
# ---------------------------------------------------------------------------


class TestNatsConnectErrorExport:
    def test_nats_connect_error_importable_from_messaging(self):
        from pillywiggins.messaging import NatsConnectError
        assert NatsConnectError is not None

    def test_nats_connect_error_importable_from_nats_bus(self):
        from pillywiggins.messaging.nats_bus import NatsConnectError
        assert NatsConnectError is not None