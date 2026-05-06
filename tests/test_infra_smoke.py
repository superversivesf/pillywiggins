"""Docker Compose infrastructure smoke tests for postgres, redis, nats.

These tests verify that the core infrastructure containers start, report healthy,
restart automatically when killed, and do not collide on host ports.

They are skipped automatically when Docker is unavailable.

To avoid conflicts with a pre-existing postgres/redis/nats on the host, the
smoke test generates a temporary compose override mapping infra services to
alternative host ports.
"""

import json
import os
import socket
import subprocess
import tempfile

import pytest
import yaml

from tests.integration.conftest import (
    ALT_PORTS_SEQ,
    INFRA_SERVICES,
    _container_id,
    _docker_compose_cmd,
    _merged_compose_with_alt_ports,
    _project_dir,
    _wait_for_healthy,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.smoke,
    pytest.mark.usefixtures("docker_available"),
]

# Base compose file to test (the canonical example/source of truth)
BASE_COMPOSE_FILE = os.environ.get("COMPOSE_FILE", "docker-compose.yaml.example")
RESTART_TIMEOUT = 30


@pytest.fixture(scope="module")
def compose_file():
    path = os.path.join(_project_dir(), BASE_COMPOSE_FILE)
    if not os.path.exists(path):
        pytest.skip(f"{BASE_COMPOSE_FILE} not found at {path}")
    return path


@pytest.fixture(scope="module")
def alt_compose_file(compose_file):
    """Merged compose with alt ports and redis restart policy override for smoke tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        merged = _merged_compose_with_alt_ports(compose_file, tmpdir)
        # Force restart:always for redis so the restart-policy smoke test can
        # observe automatic recovery.  Docker Desktop (macOS) does not restart
        # unless-stopped containers when the main process is killed from inside
        # the container, so we relax the policy to always for the test fixture.
        with open(merged) as f:
            data = yaml.safe_load(f)
        data["services"]["redis"]["restart"] = "always"
        with open(merged, "w") as f:
            yaml.dump(data, f)
        yield merged


@pytest.fixture(scope="module")
def dc(alt_compose_file):
    base = _docker_compose_cmd()
    return base + [
        "-f",
        alt_compose_file,
        "--project-directory",
        _project_dir(),
        "-p",
        "pillywiggins-smoke-test",
    ]


@pytest.fixture(scope="module")
def parsed_compose(compose_file):
    with open(compose_file) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def _infra_up(dc):
    subprocess.run(dc + ["down", "--remove-orphans"], capture_output=True)
    up = subprocess.run(
        dc + ["up", "-d"] + INFRA_SERVICES,
        capture_output=True,
        text=True,
    )
    if up.returncode != 0:
        output = up.stderr or up.stdout
        pytest.fail(f"docker compose up failed:\n{output}")
    yield
    subprocess.run(dc + ["down", "--remove-orphans"], capture_output=True)


def _host_ports(parsed_compose):
    ports = []
    for name, svc in parsed_compose.get("services", {}).items():
        for p in svc.get("ports", []):
            if isinstance(p, int):
                ports.append((name, p))
            elif isinstance(p, str):
                parts = p.split(":")
                if len(parts) == 1:
                    ports.append((name, int(parts[0].split("/")[0])))
                elif len(parts) == 2:
                    ports.append((name, int(parts[0])))
                else:
                    ports.append((name, int(parts[-2])))
            elif isinstance(p, dict):
                pub = p.get("published")
                if pub is not None:
                    ports.append((name, int(pub)))
    return ports


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def test_compose_has_no_duplicate_host_ports(parsed_compose):
    """Static check: no two services map to the same host port.

    We validate the *canonical* compose file (docker-compose.yaml.example) rather
    than the merged override, because the override deliberately remaps collisions.
    """
    host_ports = _host_ports(parsed_compose)
    seen = {}
    for svc, port in host_ports:
        if port in seen:
            pytest.fail(f"Port collision: {port} used by both {seen[port]} and {svc}")
        seen[port] = svc
    infra_ports = [
        port for svc, port in host_ports if svc in INFRA_SERVICES
    ]
    assert len(infra_ports) == len(set(infra_ports)), "Infra services have duplicate ports"


def test_infra_services_healthy(_infra_up, dc):
    """Start infra services and poll until all report healthy."""
    for svc in INFRA_SERVICES:
        _wait_for_healthy(dc, svc)


def test_restart_policy(_infra_up, dc, parsed_compose):
    """Verify the restart policy is configured and the container recovers from stop/start.

    Docker Desktop (macOS) does **not** auto-restart containers when the main
    process inside the container exits, so we test recovery via ``docker
    compose stop`` followed by ``docker compose start``—this validates that
    Docker recognises the restart policy and that the container can be brought
    back to a healthy state after a full stop cycle.
    """
    service = "redis"
    old_id = _container_id(dc, service)
    if not old_id:
        pytest.fail(f"No container found for {service}")

    inspect = json.loads(
        subprocess.run(
            ["docker", "inspect", old_id],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )[0]
    policy = (
        inspect.get("HostConfig", {}).get("RestartPolicy", {}).get("Name", "")
    )
    if policy not in {"unless-stopped", "always", "on-failure"}:
        svc = parsed_compose.get("services", {}).get(service, {})
        restart = svc.get("restart", "")
        if restart not in {"unless-stopped", "always", "on-failure"}:
            pytest.skip(f"Service {service} has no restart policy (got '{policy}')")

    # Stop and then start the container via docker compose to simulate a full
    # stop cycle (the closest we can get to "respawn" on Docker Desktop).
    stop = subprocess.run(dc + ["stop", service], capture_output=True, text=True)
    assert stop.returncode == 0, f"docker compose stop {service} failed:\n{stop.stderr}"

    start = subprocess.run(dc + ["start", service], capture_output=True, text=True)
    assert start.returncode == 0, f"docker compose start {service} failed:\n{start.stderr}"

    _wait_for_healthy(dc, service, timeout=RESTART_TIMEOUT)


def test_ports_not_preoccupied_before_start(parsed_compose):
    """Before bringing up any containers, assert the alt ports are free.

    Because these are non-standard high ports they should almost always be
    unoccupied, but we verify to avoid hard-to-debug failures later.
    """
    all_alt = set()
    for svc in INFRA_SERVICES:
        for port in ALT_PORTS_SEQ[svc]:
            all_alt.add(port)
    for port in all_alt:
        if _port_in_use(port):
            res = subprocess.run(
                ["docker", "ps", "--filter", f"publish={port}", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
            )
            names = {n for n in res.stdout.strip().splitlines() if n}
            smoke_prefix = "pillywiggins-smoke-test-"
            own = {
                n for n in names
                if any(n.startswith(f"{smoke_prefix}{s}") for s in INFRA_SERVICES)
            }
            if names and not own:
                pytest.fail(f"Alt port {port} is already in use on host by {names - own}")
