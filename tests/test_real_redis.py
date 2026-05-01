"""Real Redis integration tests using Docker."""

import asyncio
import os
import socket
import subprocess
import time
import uuid

import pytest

DOCKER_AVAILABLE = False
try:
    subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    DOCKER_AVAILABLE = True
except (subprocess.CalledProcessError, FileNotFoundError):
    pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_redis_ready(url: str, timeout: int = 30):
    import redis.asyncio as aioredis

    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            r = aioredis.from_url(url)
            await r.ping()
            await r.close()
            return
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5)
    pytest.fail(f"Redis did not become ready in {timeout}s: {last_err}")


@pytest.fixture(scope="module")
def redis_url():
    if not DOCKER_AVAILABLE:
        pytest.skip("Docker not available")
    port = _free_port()
    name = f"pillywiggins-test-redis-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "-p",
            f"{port}:6379",
            "--name",
            name,
            "redis:7-alpine",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    url = f"redis://127.0.0.1:{port}/0"
    try:
        asyncio.run(_wait_redis_ready(url))
        yield url
    finally:
        subprocess.run(["docker", "stop", "-t", "3", name], capture_output=True)


# ---------------------------------------------------------------------------
# Basic connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_connection(redis_url):
    import redis.asyncio as aioredis

    r = aioredis.from_url(redis_url)
    pong = await r.ping()
    assert pong is True
    await r.close()


# ---------------------------------------------------------------------------
# SET / GET
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_get(redis_url):
    import redis.asyncio as aioredis

    r = aioredis.from_url(redis_url, decode_responses=False)
    await r.set("key1", b"value1")
    val = await r.get("key1")
    assert val == b"value1"
    await r.close()


# ---------------------------------------------------------------------------
# TTL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ttl(redis_url):
    import redis.asyncio as aioredis

    r = aioredis.from_url(redis_url, decode_responses=False)
    await r.set("key2", b"value2", ex=2)
    val = await r.get("key2")
    assert val == b"value2"

    # Wait for expiry
    await asyncio.sleep(3)
    val = await r.get("key2")
    assert val is None
    await r.close()
