from pathlib import Path

import pytest
import yaml


@pytest.fixture
def compose_path():
    return Path(__file__).resolve().parent.parent / "docker-compose.yaml.example"


@pytest.fixture
def compose_data(compose_path):
    assert compose_path.exists(), "docker-compose.yaml.example should exist"
    data = yaml.safe_load(compose_path.read_text())
    assert isinstance(data, dict), "docker-compose.yaml.example should parse as a dict"
    assert "services" in data, "docker-compose.yaml.example should have a 'services' key"
    return data


@pytest.fixture
def services(compose_data):
    return compose_data["services"]


def test_compose_file_exists(compose_path):
    assert compose_path.exists(), "docker-compose.yaml.example should exist"


def test_compose_yaml_parses(compose_data):
    assert isinstance(compose_data, dict)
    assert "services" in compose_data


def test_compose_has_no_preconfigured_agents(services):
    # After the empty-default refactor, no agents are pre-configured.
    # Users opt-in via `pillywiggins onboard`.
    preconfigured = [name for name in services if name not in {
        "postgres", "redis", "nats", "searxng", "ollama"
    }]
    assert not preconfigured, (
        f"docker-compose.yaml.example should not define pre-configured agent services, "
        f"found: {preconfigured}"
    )


def test_env_example_has_discord_token_placeholder():
    env_path = Path(__file__).resolve().parent.parent / "env.example"
    assert env_path.exists(), "env.example should exist"
    for line in env_path.read_text().splitlines():
        if line.startswith("PUCK_DISCORD_TOKEN="):
            value = line.split("=", 1)[1]
            assert "token" in value.lower(), "PUCK_DISCORD_TOKEN should be a placeholder"
            return
    pytest.fail("PUCK_DISCORD_TOKEN not found in env.example")


# --- Healthcheck & Restart Policy Tests ---


def test_all_services_have_restart_unless_stopped(services):
    missing = [
        name for name, svc in services.items()
        if svc.get("restart") != "unless-stopped"
    ]
    assert not missing, (
        f"Services missing restart: unless-stopped: {missing}"
    )


def test_all_services_have_healthcheck(services):
    missing = [
        name for name, svc in services.items()
        if "healthcheck" not in svc
    ]
    assert not missing, (
        f"Services missing healthcheck block: {missing}"
    )


def test_all_healthchecks_have_required_fields(services):
    required = {"test", "interval", "timeout", "retries"}
    for name, svc in services.items():
        hc = svc.get("healthcheck", {})
        present = set(hc.keys())
        assert required.issubset(present), (
            f"Service '{name}' healthcheck missing required fields: {required - present}"
        )


def test_postgres_healthcheck_uses_pg_isready(services):
    hc = services["postgres"].get("healthcheck", {})
    test_cmd = hc.get("test", [])
    cmd_str = " ".join(str(x) for x in test_cmd)
    assert "pg_isready" in cmd_str, (
        f"postgres healthcheck should use pg_isready, got: {cmd_str}"
    )


def test_redis_healthcheck_uses_ping(services):
    hc = services["redis"].get("healthcheck", {})
    test_cmd = hc.get("test", [])
    cmd_str = " ".join(str(x) for x in test_cmd)
    assert "redis-cli" in cmd_str and "ping" in cmd_str.lower(), (
        f"redis healthcheck should use redis-cli ping, got: {cmd_str}"
    )


def test_nats_healthcheck_exists_and_sensible(services):
    hc = services["nats"].get("healthcheck", {})
    test_cmd = hc.get("test", [])
    assert len(test_cmd) > 0, "nats healthcheck test should not be empty"


def test_no_agent_services_healthchecks_expected(services):
    # With empty-default agents, there are no pre-configured agent services.
    # When users add agents via `pillywiggins onboard`, healthchecks will be
    # generated for those specific services.
    infra_services = {"postgres", "redis", "nats", "searxng", "ollama"}
    agent_services = [name for name in services if name not in infra_services]
    assert not agent_services, (
        f"No pre-configured agent services should exist, found: {agent_services}"
    )
