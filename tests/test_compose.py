from pathlib import Path

import pytest
import yaml


@pytest.fixture
def compose_path():
    return Path(__file__).resolve().parent.parent / "docker-compose.yaml.example"


def test_compose_file_exists(compose_path):
    assert compose_path.exists(), "docker-compose.yaml.example should exist"


def test_compose_yaml_parses(compose_path):
    data = yaml.safe_load(compose_path.read_text())
    assert isinstance(data, dict), "docker-compose.yaml.example should parse as a dict"
    assert "services" in data, "docker-compose.yaml.example should have a 'services' key"


def test_compose_has_puck_discord_service(compose_path):
    data = yaml.safe_load(compose_path.read_text())
    services = data["services"]
    assert "puck-discord" in services, (
        "docker-compose.yaml.example should define a puck-discord service"
    )


def test_puck_discord_service_structure(compose_path):
    data = yaml.safe_load(compose_path.read_text())
    svc = data["services"]["puck-discord"]
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
