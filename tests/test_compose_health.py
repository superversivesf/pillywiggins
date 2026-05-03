"""
Docker Compose service health verification integration test.

Proves the compose stack works end-to-end by:
1. Validating docker-compose.yaml syntax.
2. Starting infrastructure services (postgres, redis, nats).
3. Polling until all services report *Health=healthy*.
4. Verifying inter-container TCP connectivity.
5. Cleaning up unconditionally.

This test is **slow** (30–90s) and is tagged so CI can skip it.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time

import pytest
import yaml

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]

PROJECT_NAME = "pillywiggins-health"
COMPOSE_FILE = "docker-compose.yaml"
INFRA_SERVICES = ["postgres", "redis", "nats"]
HEALTH_TIMEOUT = 60
POLL_INTERVAL = 2
# Alternative host ports so we don't collide with local infra or other tests.
ALT_PORTS = {
    "postgres": ["15432:5432"],
    "redis": ["16379:6379"],
    "nats": ["14222:4222", "18222:8222"],
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def docker_available():
    """Skip the entire module if Docker is not running."""
    try:
        subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except Exception as exc:
        pytest.skip(f"Docker not available: {exc}")


def _project_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_compose_file(project_dir: str) -> str:
    compose_path = os.path.join(project_dir, COMPOSE_FILE)
    if not os.path.exists(compose_path):
        example_path = compose_path + ".example"
        if os.path.exists(example_path):
            shutil.copyfile(example_path, compose_path)
        else:
            pytest.skip(f"{COMPOSE_FILE} not found and no example available")
    return compose_path


def _parse_ps_json(stdout: str):
    """Handle both JSON-array and newline-delimited JSON from ``docker compose ps``."""
    stdout = stdout.strip()
    if not stdout:
        return []
    try:
        data = json.loads(stdout)
        if isinstance(data, list):
            return data
        return [data]
    except json.JSONDecodeError:
        return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def _merged_compose_file(compose_path: str, tmpdir: str) -> str:
    """Return a merged compose file with alt host ports and missing healthchecks."""
    with open(compose_path) as f:
        data = yaml.safe_load(f)

    services = data.setdefault("services", {})
    for svc, port_mappings in ALT_PORTS.items():
        if svc in services:
            services[svc]["ports"] = port_mappings

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

    merged_path = os.path.join(tmpdir, "docker-compose.merged.yaml")
    with open(merged_path, "w") as f:
        yaml.dump(data, f)
    return merged_path


@pytest.fixture(scope="module")
def compose_infra(docker_available):
    """
    Bring up infrastructure services and tear them down after the module.

    Yields a dict with ``services``, ``dc`` (compose CLI base list) and
    ``project_dir``.
    """
    project_dir = _project_dir()
    compose_path = _ensure_compose_file(project_dir)

    with tempfile.TemporaryDirectory() as tmpdir:
        merged_path = _merged_compose_file(compose_path, tmpdir)
        dc = [
            "docker",
            "compose",
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
            start = time.monotonic()
            last_status = {}
            while time.monotonic() - start < HEALTH_TIMEOUT:
                ps = subprocess.run(
                    dc + ["ps", "--format", "json"],
                    capture_output=True,
                    text=True,
                )
                containers = _parse_ps_json(ps.stdout)
                healthy_by_svc = {svc: False for svc in INFRA_SERVICES}
                for c in containers:
                    svc = c.get("Service") or c.get("service")
                    health = c.get("Health") or c.get("health")
                    if svc in healthy_by_svc and health == "healthy":
                        healthy_by_svc[svc] = True
                last_status = {
                    (c.get("Service") or c.get("service")): (
                        c.get("Health") or c.get("health")
                    )
                    for c in containers
                }
                if all(healthy_by_svc.values()):
                    break
                time.sleep(POLL_INTERVAL)
            else:
                # Timeout reached — collect logs and fail
                logs = {}
                for svc in INFRA_SERVICES:
                    if not healthy_by_svc.get(svc):
                        log_res = subprocess.run(
                            dc + ["logs", svc],
                            capture_output=True,
                            text=True,
                        )
                        logs[svc] = log_res.stdout + log_res.stderr
                msg = (
                    f"Services did not become healthy within {HEALTH_TIMEOUT}s.\n"
                    f"Last status: {last_status}\n"
                )
                for svc, log in logs.items():
                    msg += f"\n--- {svc} logs ---\n{log}\n"
                pytest.fail(msg)

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
    network_name = f"{PROJECT_NAME}_default"
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
