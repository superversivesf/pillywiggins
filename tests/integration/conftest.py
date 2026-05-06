"""Shared infrastructure for Docker Compose integration tests.

Provides constants, helpers, and fixtures used by test_e2e_compose,
test_compose_health, and test_infra_smoke.

The ``docker_available`` fixture lives in ``tests/conftest.py`` (session-scoped)
so that it is available to *all* test files, not just integration tests.
"""

import json
import os
import subprocess
import time

import pytest
import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INFRA_SERVICES = ["postgres", "redis", "nats"]

# Alternative host ports (high ports to avoid conflicts with local services).
# Keys map to INFRA_SERVICES; values are lists so multi-port services (NATS)
# are fully covered.  Each test module may supply its own mapping to
# _merged_compose_with_alt_ports() when a different port range is needed.
ALT_PORTS_SEQ = {
    "postgres": [15432],
    "redis": [16379],
    "nats": [14222, 18222],
}

HEALTHY_TIMEOUT = 120
POLL_INTERVAL = 2

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _docker_compose_cmd():
    """Return the working Docker Compose command as a list.

    Prefers ``docker compose`` (Compose V2 plugin) and falls back to
    ``docker-compose`` (legacy standalone binary).
    """
    for base in (["docker", "compose"], ["docker-compose"]):
        if subprocess.run(base + ["version"], capture_output=True).returncode == 0:
            return base
    pytest.skip("No docker compose command available")


def _project_dir():
    """Return the project root directory (parent of tests/)."""
    # tests/integration/conftest.py -> tests/integration -> tests -> project root
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _merged_compose_with_alt_ports(compose_file, tmpdir, alt_ports=None):
    """Return a path to a merged compose file where infra services use alt host ports.

    Parameters
    ----------
    compose_file : str
        Path to the base compose YAML file.
    tmpdir : str
        Directory in which to write the merged file.
    alt_ports : dict, optional
        Mapping of service name to list of alternative host port numbers.
        Defaults to ALT_PORTS_SEQ.

    Returns
    -------
    str
        Path to the merged compose YAML file.
    """
    if alt_ports is None:
        alt_ports = ALT_PORTS_SEQ
    with open(compose_file) as f:
        data = yaml.safe_load(f)
    for svc in INFRA_SERVICES:
        ports = data.get("services", {}).get(svc, {}).get("ports", [])
        if not ports:
            continue
        new_ports = []
        alt_seq = alt_ports[svc]
        for idx, p in enumerate(ports):
            alt = alt_seq[idx] if idx < len(alt_seq) else alt_seq[0]
            if isinstance(p, str):
                parts = p.split(":")
                if len(parts) == 1:
                    new_ports.append(f"{alt}:{parts[0]}")
                elif len(parts) == 2:
                    new_ports.append(f"{alt}:{parts[1]}")
                else:
                    new_ports.append(f"{alt}:{parts[1]}")
            elif isinstance(p, dict):
                target = p.get("target", p.get("container", ""))
                proto = p.get("protocol", "tcp")
                if target:
                    new_ports.append(f"{alt}:{target}/{proto}")
                else:
                    new_ports.append(str(alt))
            elif isinstance(p, int):
                new_ports.append(f"{alt}:{p}")
        data["services"][svc]["ports"] = new_ports
    merged_path = os.path.join(tmpdir, "docker-compose.alt-ports.yaml")
    with open(merged_path, "w") as f:
        yaml.dump(data, f)
    return merged_path


def _container_id(dc, service: str) -> str:
    """Return the container ID for *service* in the compose project."""
    res = subprocess.run(
        dc + ["ps", "-q", service],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def _container_status(container_id: str) -> dict:
    """Inspect a container and return its running/healthy status."""
    if not container_id:
        return {"running": False, "healthy": False, "status": "missing"}
    inspect = subprocess.run(
        ["docker", "inspect", container_id],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(inspect.stdout)[0]
    state = data.get("State", {})
    health = state.get("Health", {})
    return {
        "running": state.get("Running", False),
        "status": state.get("Status", ""),
        "healthy": health.get("Status") == "healthy",
        "health_status": health.get("Status", "none"),
    }


def _wait_for_healthy(dc, service: str, timeout: int = HEALTHY_TIMEOUT):
    """Poll until *service* reports healthy, or fail."""
    cid = _container_id(dc, service)
    start = time.time()
    while time.time() - start < timeout:
        status = _container_status(cid)
        if status["healthy"]:
            return
        if not status["running"] and time.time() - start > 10:
            pytest.fail(
                f"Container for {service} is not running (status={status['status']})"
            )
        time.sleep(POLL_INTERVAL)
        cid = _container_id(dc, service)
    pytest.fail(f"Container for {service} did not become healthy within {timeout}s")