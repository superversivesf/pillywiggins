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


def test_compose_has_puck_discord_service(services):
    assert "puck-discord" in services, (
        "docker-compose.yaml.example should define a puck-discord service"
    )


def test_puck_discord_service_structure(services):
    svc = services["puck-discord"]
    assert svc.get("build") == ".", "puck-discord should build from root"
    assert svc.get("command") == "python -m pillywiggins --agent-id puck-discord", (
        "puck-discord command mismatch"
    )
    assert svc.get("env_file") == ".env", "puck-discord should use .env"
    env = svc.get("environment", {})
    assert env.get("AGENT_ID") == "puck-discord", "puck-discord AGENT_ID mismatch"
    volumes = svc.get("volumes", [])
    assert any("personalities" in str(v) for v in volumes), (
        "puck-discord should mount personalities"
    )
    assert any("skills" in str(v) for v in volumes), "puck-discord should mount skills"
    depends_on = svc.get("depends_on", {})
    assert "postgres" in depends_on, "puck-discord should depend_on postgres"
    assert "redis" in depends_on, "puck-discord should depend_on redis"
    assert "nats" in depends_on, "puck-discord should depend_on nats"


def test_env_example_has_discord_token():
    env_path = Path(__file__).resolve().parent.parent / "env.example"
    assert env_path.exists(), "env.example should exist"
    for line in env_path.read_text().splitlines():
        if line.startswith("PUCK_DISCORD_TOKEN="):
            value = line.split("=", 1)[1]
            assert value != "", "PUCK_DISCORD_TOKEN should not be empty"
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


def test_agent_services_healthcheck_exists(services):
    for name in ["puck", "puck-discord"]:
        assert name in services, f"{name} service should exist"
        hc = services[name].get("healthcheck", {})
        test_cmd = hc.get("test", [])
        assert len(test_cmd) > 0, (
            f"{name} healthcheck test should not be empty"
        )
