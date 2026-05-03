"""Smoke tests: verify infrastructure services are reachable. Requires Docker Compose infrastructure running."""

import socket
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest


def _check_tcp(host: str, port: int, timeout: float = 2) -> bool:
    """Attempt a TCP connection and return True if the port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _check_http(url: str, timeout: float = 2):
    """Attempt an HTTP GET and return (status_code, body) or (None, None) on failure."""
    try:
        with urlopen(Request(url, method="GET"), timeout=timeout) as response:
            return response.status, response.read()
    except HTTPError as e:
        return e.code, None
    except (HTTPError, URLError, OSError):
        return None, None


_docker_services_cache = None


@pytest.fixture(scope="session")
def docker_services_running():
    """Return the set of Docker Compose services with status=running, cached for the session."""
    global _docker_services_cache
    if _docker_services_cache is not None:
        return _docker_services_cache

    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--services", "--filter", "status=running"],
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _docker_services_cache = set()
        return _docker_services_cache

    if result.returncode != 0:
        _docker_services_cache = set()
        return _docker_services_cache

    _docker_services_cache = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return _docker_services_cache


def _require_service(running_services: set, name: str) -> None:
    if name not in running_services:
        pytest.skip(f"Docker Compose service '{name}' is not running")


@pytest.mark.smoke
def test_postgres_port_open(docker_services_running):
    """TCP connect to localhost:5432, skip if postgres container is missing."""
    _require_service(docker_services_running, "postgres")
    assert _check_tcp("127.0.0.1", 5432), "Cannot connect to postgres on port 5432"


@pytest.mark.smoke
def test_redis_port_open(docker_services_running):
    """TCP connect to localhost:6379, skip if redis container is missing."""
    _require_service(docker_services_running, "redis")
    assert _check_tcp("127.0.0.1", 6379), "Cannot connect to redis on port 6379"


@pytest.mark.smoke
def test_nats_tcp_open(docker_services_running):
    """TCP connect to localhost:4222, skip if nats container is missing."""
    _require_service(docker_services_running, "nats")
    assert _check_tcp("127.0.0.1", 4222), "Cannot connect to nats on port 4222"


@pytest.mark.smoke
def test_nats_http_health(docker_services_running):
    """HTTP GET http://localhost:8222/healthz, skip if nats container is missing."""
    _require_service(docker_services_running, "nats")
    status, _ = _check_http("http://127.0.0.1:8222/healthz")
    assert status == 200, f"Expected HTTP 200 from NATS healthz, got {status}"


@pytest.mark.smoke
def test_searxng_health(docker_services_running):
    """HTTP GET SearXNG health endpoint, skip if searxng container is missing."""
    _require_service(docker_services_running, "searxng")
    # Mapped to host port 8888 in docker-compose.yaml (container port is 8080)
    status, _ = _check_http("http://127.0.0.1:8888/healthz")
    assert status == 200, f"Expected HTTP 200 from SearXNG healthz, got {status}"


@pytest.mark.smoke
def test_ollama_http_ping():
    """HTTP GET http://localhost:11434, skip if Ollama is not installed or reachable."""
    status, _ = _check_http("http://127.0.0.1:11434")
    if status is None:
        pytest.skip("Ollama is not reachable on localhost:11434")
    # Ollama typically returns 404 on root; any HTTP response means it's up.
    assert status is not None
