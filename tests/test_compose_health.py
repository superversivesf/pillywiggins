"""
Docker Compose service health verification integration test.

Proves the compose stack works end-to-end by:
1. Validating docker-compose.yaml syntax.
2. Starting infrastructure services (postgres, redis, nats).
3. Polling until all services report *Health=healthy*.
4. Verifying inter-container TCP connectivity.
5. Cleaning up unconditionally.

This test is **slow** (30-90s) and is tagged so CI can skip it.
"""

import os
import shutil
import subprocess
import tempfile

import pytest
import yaml

from tests.integration.conftest import (
    INFRA_SERVICES,
    _docker_compose_cmd,
    _merged_compose_with_alt_ports,
    _project_dir,
    _wait_for_healthy,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.usefixtures("docker_available"),
]

PROJECT_NAME = "pillywiggins-health"
COMPOSE_FILE = "docker-compose.yaml"


def _ensure_compose_file(project_dir: str) -> str:
    compose_path = os.path.join(project_dir, COMPOSE_FILE)
    if not os.path.exists(compose_path):
        example_path = compose_path + ".example"
        if os.path.exists(example_path):
            shutil.copyfile(example_path, compose_path)
        else:
            pytest.skip(f"{COMPOSE_FILE} not found and no example available")
    return compose_path


def _add_healthchecks(merged_path: str) -> None:
    """Add missing healthchecks for redis and nats to the merged compose file.

    Some compose templates omit healthchecks for these services; without them
    ``docker compose ps`` will never report ``healthy``, causing the shared
    ``_wait_for_healthy`` helper to time out.
    """
    with open(merged_path) as f:
        data = yaml.safe_load(f)

    services = data.setdefault("services", {})

    if "redis" in services and not services["redis"].get("healthcheck"):
        services["redis"]["healthcheck"] = {
            "test": ["CMD-SHELL", "redis-cli ping | grep -q PONG || exit 1"],
            "interval": "5s",
            "timeout": "5s",
            "retries": 5,
            "start_period": "3s",
        }

    if "nats" in services and not services["nats"].get("healthcheck"):
        services["nats"]["command"] = "nats-server -js -m 8222"
        services["nats"]["healthcheck"] = {
            "test": [
                "CMD-SHELL",
                "wget --spider -q http://localhost:8222/healthz || exit 1",
            ],
            "interval": "5s",
            "timeout": "5s",
            "retries": 5,
            "start_period": "3s",
        }

    with open(merged_path, "w") as f:
        yaml.dump(data, f)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_infra():
    """
    Bring up infrastructure services and tear them down after the module.

    Yields a dict with ``services``, ``dc`` (compose CLI base list) and
    ``project_dir``.
    """
    project_dir = _project_dir()
    compose_path = _ensure_compose_file(project_dir)

    with tempfile.TemporaryDirectory() as tmpdir:
        merged_path = _merged_compose_with_alt_ports(compose_path, tmpdir)
        _add_healthchecks(merged_path)

        base = _docker_compose_cmd()
        dc = base + [
            "-f",
            merged_path,
            "--project-directory",
            project_dir,
            "-p",
            PROJECT_NAME,
        ]

        # --- 1. Syntax validation ---
        config = subprocess.run(dc + ["config"], capture_output=True, text=True)
        if config.returncode != 0:
            pytest.fail(f"docker compose config failed:\n{config.stderr}")
        parsed = yaml.safe_load(config.stdout)
        for svc in INFRA_SERVICES:
            if svc not in parsed.get("services", {}):
                pytest.fail(f"Service '{svc}' missing from parsed compose config")

        # Ensure clean slate before starting
        subprocess.run(dc + ["down", "--volumes", "--remove-orphans"], capture_output=True)

        # --- 2. Start infrastructure ---
        up = subprocess.run(
            dc + ["up", "-d"] + INFRA_SERVICES,
            capture_output=True,
            text=True,
        )
        if up.returncode != 0:
            subprocess.run(dc + ["down", "--volumes", "--remove-orphans"], capture_output=True)
            pytest.fail(f"docker compose up failed:\n{up.stderr}")

        # --- 3. Wait for healthy ---
        try:
            for svc in INFRA_SERVICES:
                _wait_for_healthy(dc, svc)

            yield {
                "services": INFRA_SERVICES,
                "dc": dc,
                "project_dir": project_dir,
            }
        finally:
            # --- 5. Cleanup ---
            subprocess.run(dc + ["down", "--volumes", "--remove-orphans"], capture_output=True)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_compose_health(compose_infra):
    """
    End-to-end Docker Compose health verification.

    By the time this test runs the fixture has already validated syntax,
    started the infrastructure, and waited for every service to become
    healthy.  We only need to verify inter-container networking.
    """
    # --- 4. Verify inter-container networking ---
    # The compose file explicitly names the network "pillywiggins" (not
    # "default"), so the Docker network becomes "<project>_pillywiggins".
    network_name = f"{PROJECT_NAME}_pillywiggins"
    probe = (
        "nc -z -w5 postgres 5432 && "
        "nc -z -w5 redis 6379 && "
        "nc -z -w5 nats 4222"
    )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            network_name,
            "busybox:stable",
            "sh",
            "-c",
            probe,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Inter-container networking probe failed:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )