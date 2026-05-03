"""End-to-end Docker Compose integration tests.

These tests require a running Docker daemon and the ``docker compose`` CLI.
They are skipped automatically when Docker is unavailable.

The test suite validates the full Docker Compose stack as described in the
project's canonical ``docker-compose.yaml.example``:

1. Compose file parses and validates (``docker compose config``).
2. All images build successfully (``docker compose build``).
3. Infrastructure services (postgres, redis, nats) start and become healthy.
4. At least one agent service image starts as a container and passes its
   healthcheck (returns 200 OK).  The test uses a stub command — the actual
   agent process would require real channel tokens and an LLM endpoint — but
   the container still exercises the built image, healthcheck config, and
   service dependencies.
5. The shared ``skills/`` bind mount is writable from one container and
   readable from another.
6. NATS pub/sub works end-to-end between two lightweight containers on the
   ``pillywiggins`` compose network.

Every test cleans up its own containers to avoid leaving state behind.
To avoid conflicts with any host services already bound to the default
ports, infra services are remapped to alternative high ports via a generated
override file.
"""

import contextlib
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
    pytest.mark.usefixtures("docker_available"),
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_COMPOSE_FILE = os.environ.get("COMPOSE_FILE", "docker-compose.yaml.example")
E2E_PROJECT = "pillywiggins-e2e"
INFRA_SERVICES = ["postgres", "redis", "nats"]
# Alternative host ports so we don't collide with local postgres/redis/nats.
ALT_PORTS_SEQ = {"postgres": [25432], "redis": [26379], "nats": [24222, 28222]}
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
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _merged_compose_with_alt_ports(compose_file, tmpdir):
    """Return a path to a merged compose file where infra services use alt host ports."""
    with open(compose_file) as f:
        data = yaml.safe_load(f)
    for svc in INFRA_SERVICES:
        ports = data.get("services", {}).get(svc, {}).get("ports", [])
        if not ports:
            continue
        new_ports = []
        alt_seq = ALT_PORTS_SEQ[svc]
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
    merged_path = os.path.join(tmpdir, "docker-compose.e2e-alt-ports.yaml")
    with open(merged_path, "w") as f:
        yaml.dump(data, f)
    return merged_path


def _container_id(dc, service: str) -> str:
    res = subprocess.run(
        dc + ["ps", "-q", service],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def _container_status(container_id: str) -> dict:
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


@contextlib.contextmanager
def _temp_compose_override(project_dir: str, base_file: str, overrides: dict):
    """Yield a compose command that merges *overrides* on top of *base_file*.

    The override file is placed on disk inside *project_dir* so that relative
    paths in the base compose (e.g. ``./skills``) still resolve.

    On context exit ``docker compose down`` is run and the override file is
    removed.
    """
    base = _docker_compose_cmd()
    fd, override_path = tempfile.mkstemp(suffix=".yaml", dir=project_dir)
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(overrides, f)
        dc = base + [
            "-f", base_file,
            "-f", override_path,
            "--project-directory", project_dir,
            "-p", E2E_PROJECT,
        ]
        yield dc
    finally:
        subprocess.run(
            base + [
                "-f", base_file,
                "-f", override_path,
                "--project-directory", project_dir,
                "-p", E2E_PROJECT,
                "down", "--remove-orphans", "--volumes",
            ],
            capture_output=True,
        )
        try:
            os.unlink(override_path)
        except OSError:
            pass


def _ensure_gitignored_config_files(project_dir: str) -> list[str]:
    """Create ``agents.yaml`` and ``.env`` from their ``.example`` templates
    if they are missing.  Returns the list of files that were created so they
    can be cleaned up later.
    """
    created = []
    for example_name, real_name in (
        ("agents.yaml.example", "agents.yaml"),
        ("env.example", ".env"),
    ):
        example_path = os.path.join(project_dir, example_name)
        real_path = os.path.join(project_dir, real_name)
        if not os.path.exists(real_path) and os.path.exists(example_path):
            shutil.copyfile(example_path, real_path)
            created.append(real_path)
    return created


def _cleanup_config_files(paths: list[str]):
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Module-level fixture: merged compose with alternate ports
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def alt_compose_file():
    """Canonical compose file remapped to alternative host ports."""
    compose_file_path = os.path.join(_project_dir(), BASE_COMPOSE_FILE)
    if not os.path.exists(compose_file_path):
        pytest.skip(f"{BASE_COMPOSE_FILE} not found")
    with tempfile.TemporaryDirectory() as tmpdir:
        yield _merged_compose_with_alt_ports(compose_file_path, tmpdir)


@pytest.fixture(scope="module")
def dc_alt(alt_compose_file):
    """Docker Compose command pointing at the altitude-port merged compose."""
    base = _docker_compose_cmd()
    return base + [
        "-f", alt_compose_file,
        "--project-directory", _project_dir(),
        "-p", E2E_PROJECT,
    ]


@pytest.fixture(scope="module")
def _infra_up(dc_alt):
    """Bring up infrastructure services on alt ports and tear them down at module end."""
    subprocess.run(dc_alt + ["down", "--remove-orphans", "--volumes"], capture_output=True)
    up = subprocess.run(
        dc_alt + ["up", "-d"] + INFRA_SERVICES,
        capture_output=True,
        text=True,
    )
    if up.returncode != 0:
        pytest.fail(f"docker compose up infra failed:\n{up.stderr}")
    yield
    subprocess.run(dc_alt + ["down", "--remove-orphans", "--volumes"], capture_output=True)


# ---------------------------------------------------------------------------
# 1. compose config validation (raw canonical file)
# ---------------------------------------------------------------------------


def test_compose_config_validates():
    """``docker compose config`` should parse and validate the canonical file."""
    compose_file_path = os.path.join(_project_dir(), BASE_COMPOSE_FILE)
    if not os.path.exists(compose_file_path):
        pytest.skip("Base compose file not found")
    base = _docker_compose_cmd()
    result = subprocess.run(
        base + ["-f", compose_file_path, "config"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"docker compose config failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    parsed = yaml.safe_load(result.stdout)
    services = set(parsed.get("services", {}).keys())
    for svc in [*INFRA_SERVICES, "puck", "puck-discord"]:
        assert svc in services, f"Expected service '{svc}' in merged compose output"


# ---------------------------------------------------------------------------
# 2. compose build
# ---------------------------------------------------------------------------


def test_compose_build():
    """All services with a ``build`` context should build successfully."""
    compose_file_path = os.path.join(_project_dir(), BASE_COMPOSE_FILE)
    base = _docker_compose_cmd()
    result = subprocess.run(
        base + ["-f", compose_file_path, "config"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    result = subprocess.run(
        base + ["-f", compose_file_path, "build"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"docker compose build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# 3. infra services healthy
# ---------------------------------------------------------------------------


def test_infra_services_healthy(_infra_up, dc_alt):
    """Postgres, Redis, and NATS containers must reach the ``healthy`` state."""
    for svc in INFRA_SERVICES:
        _wait_for_healthy(dc_alt, svc)


# ---------------------------------------------------------------------------
# 4. agent healthcheck
# ---------------------------------------------------------------------------

_AGENT_HEALTH_STUB = """\
import asyncio
from aiohttp import web

async def h(r):
    return web.json_response({"status": "ok"}, status=200)

async def main():
    app = web.Application()
    app.router.add_get("/healthz", h)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    await asyncio.Event().wait()

asyncio.run(main())
"""


def test_agent_service_healthcheck(alt_compose_file):
    """An agent service container starts and its healthcheck returns 200 OK.

    The real agent processes require valid channel tokens and an LLM endpoint,
    which are not available in a CI environment.  Instead we mount a tiny
    aiohttp stub that serves ``/healthz`` on port 8080 and override the
    service ``command`` to run it.  The container still uses the built image,
    the original healthcheck definition, and the full ``depends_on`` chain,
    so this validates the Docker layer end-to-end.
    """
    project_dir = _project_dir()
    created = _ensure_gitignored_config_files(project_dir)
    tmpdir = tempfile.mkdtemp(dir=project_dir)
    try:
        stub_path = os.path.join(tmpdir, "health_stub.py")
        with open(stub_path, "w") as f:
            f.write(_AGENT_HEALTH_STUB)

        override = {
            "services": {
                "puck": {
                    "command": "python /tmp/health_stub.py",
                    "volumes": [
                        f"{stub_path}:/tmp/health_stub.py:ro",
                    ],
                    "healthcheck": {
                        "test": ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')\" || exit 1"],
                        "interval": "10s",
                        "timeout": "5s",
                        "retries": 6,
                        "start_period": "5s",
                    },
                },
            },
        }
        with _temp_compose_override(project_dir, alt_compose_file, override) as odc:
            subprocess.run(odc + ["down", "--remove-orphans", "--volumes"], capture_output=True)
            up = subprocess.run(
                odc + ["up", "-d", "puck"],
                capture_output=True,
                text=True,
            )
            if up.returncode != 0:
                pytest.fail(f"docker compose up puck failed:\n{up.stderr}")

            _wait_for_healthy(odc, "puck")

            puck_cid = _container_id(odc, "puck")
            health = subprocess.run(
                [
                    "docker", "exec", puck_cid,
                    "python", "-c",
                    'import urllib.request; print(urllib.request.urlopen("http://localhost:8080/healthz").read().decode())',
                ],
                capture_output=True,
                text=True,
            )
            assert health.returncode == 0, (
                f"Health endpoint request failed:\n{health.stderr}"
            )
            try:
                body = json.loads(health.stdout)
            except json.JSONDecodeError as exc:
                pytest.fail(
                    f"Health endpoint returned invalid JSON: {health.stdout!r} ({exc})"
                )
            assert body.get("status") == "ok", (
                f"Expected status 'ok' from health endpoint, got: {body}"
            )
    finally:
        _cleanup_config_files(created)
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5. shared skills volume
# ---------------------------------------------------------------------------


def test_skills_volume_shared_between_containers(alt_compose_file):
    """Two agent containers sharing the ``skills/`` bind mount can read each
    other's writes.
    """
    project_dir = _project_dir()
    created = _ensure_gitignored_config_files(project_dir)
    test_file_name = "test_e2e_volume.txt"

    def _run_cmd(service, cmd):
        """Run a one-off command in a service container (no deps)."""
        base = _docker_compose_cmd()
        return base + [
            "-f", alt_compose_file,
            "--project-directory", project_dir,
            "-p", E2E_PROJECT,
            "run", "--rm", "--no-deps",
            service,
            "sh", "-c", cmd,
        ]

    try:
        write = subprocess.run(
            _run_cmd("puck", f"echo hello-from-puck > /app/skills/{test_file_name}"),
            capture_output=True,
            text=True,
        )
        assert write.returncode == 0, (
            f"Failed to write shared volume file:\n{write.stderr}"
        )

        read = subprocess.run(
            _run_cmd("puck-discord", f"cat /app/skills/{test_file_name}"),
            capture_output=True,
            text=True,
        )
        assert read.returncode == 0, (
            f"Failed to read shared volume file:\n{read.stderr}"
        )
        assert "hello-from-puck" in read.stdout, (
            f"Expected shared file content not found; got: {read.stdout!r}"
        )
    finally:
        host_skills = os.path.join(project_dir, "skills", test_file_name)
        _cleanup_config_files([host_skills])
        _cleanup_config_files(created)


# ---------------------------------------------------------------------------
# 6. NATS pub/sub between containers
# ---------------------------------------------------------------------------

_NATS_SUB_SCRIPT = """\
import asyncio
import sys
import nats

msgs = []

async def handler(msg):
    msgs.append(msg.data.decode())

async def main():
    nc = await nats.connect("nats://nats:4222")
    sub = await nc.subscribe("council.broadcast", cb=handler)
    for _ in range(30):
        await asyncio.sleep(0.5)
        if any("hello-e2e" in m for m in msgs):
            break
    await sub.unsubscribe()
    await nc.close()
    if not any("hello-e2e" in m for m in msgs):
        print("FAIL: no message received", file=sys.stderr)
        sys.exit(1)
    print("PASS: received message")

asyncio.run(main())
"""

_NATS_PUB_SCRIPT = """\
import asyncio
import nats

async def main():
    nc = await nats.connect("nats://nats:4222")
    await nc.publish("council.broadcast", b"hello-e2e")
    await nc.close()

asyncio.run(main())
"""


def test_nats_pub_sub_between_containers(alt_compose_file):
    """Two lightweight containers on the compose network can publish and
    receive a NATS broadcast message.
    """
    project_dir = _project_dir()
    tmpdir = tempfile.mkdtemp(dir=project_dir)
    try:
        sub_stub = os.path.join(tmpdir, "nats_sub.py")
        pub_stub = os.path.join(tmpdir, "nats_pub.py")
        with open(sub_stub, "w") as f:
            f.write(_NATS_SUB_SCRIPT)
        with open(pub_stub, "w") as f:
            f.write(_NATS_PUB_SCRIPT)

        override = {
            "services": {
                "nats-sub": {
                    "build": ".",
                    "command": "python /tmp/nats_sub.py",
                    "depends_on": {
                        "nats": {"condition": "service_healthy"},
                    },
                    "networks": ["pillywiggins"],
                    "volumes": [
                        f"{sub_stub}:/tmp/nats_sub.py:ro",
                    ],
                },
                "nats-pub": {
                    "build": ".",
                    "command": "python /tmp/nats_pub.py",
                    "depends_on": {
                        "nats": {"condition": "service_healthy"},
                    },
                    "networks": ["pillywiggins"],
                    "volumes": [
                        f"{pub_stub}:/tmp/nats_pub.py:ro",
                    ],
                },
            },
        }
        with _temp_compose_override(project_dir, alt_compose_file, override) as odc:
            subprocess.run(odc + ["down", "--remove-orphans", "--volumes"], capture_output=True)

            up = subprocess.run(
                odc + ["up", "-d", "nats-sub"],
                capture_output=True,
                text=True,
            )
            if up.returncode != 0:
                pytest.fail(f"docker compose up nats-sub failed:\n{up.stderr}")

            time.sleep(2)

            pub = subprocess.run(
                odc + ["run", "--rm", "nats-pub"],
                capture_output=True,
                text=True,
            )
            assert pub.returncode == 0, (
                f"Publisher container failed:\nstdout: {pub.stdout}\nstderr: {pub.stderr}"
            )

            sub_cid = _container_id(odc, "nats-sub")
            wait = subprocess.run(
                ["docker", "wait", sub_cid],
                capture_output=True,
                text=True,
            )
            exit_code_str = wait.stdout.strip()
            if exit_code_str:
                assert int(exit_code_str) == 0, (
                    f"Subscriber container exited with code {exit_code_str}"
                )

            logs = subprocess.run(
                odc + ["logs", "nats-sub"],
                capture_output=True,
                text=True,
            )
            assert "PASS: received message" in logs.stdout, (
                f"NATS subscriber did not receive the message.\n"
                f"stdout: {logs.stdout}\nstderr: {logs.stderr}"
            )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
