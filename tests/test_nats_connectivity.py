"""NATS connectivity integration test.

Starts a NATS container via Docker Compose, connects via nats-py,
and verifies pub/sub and JetStream streams work end-to-end.
Skips if Docker or NATS is not available.
"""

import asyncio
import socket
import subprocess
import time
from pathlib import Path

import nats
import pytest

NATS_URL = "nats://localhost:4222"
TEST_STREAM = "TEST_STREAM"
TEST_SUBJECT = "test.subject"
STREAM_SUBJECT = "test.stream.hello"


def _docker_compose_up():
    """Start the nats service from docker-compose.yaml."""
    subprocess.run(
        ["docker", "compose", "up", "-d", "nats"],
        cwd=Path(__file__).resolve().parent.parent,
        check=True,
        capture_output=True,
        text=True,
    )


def _docker_compose_down():
    """Stop the nats service."""
    subprocess.run(
        ["docker", "compose", "down", "--volumes", "nats"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
    )


def _is_nats_available(timeout: float = 30.0) -> bool:
    """Poll NATS TCP port 4222 until it accepts connections or timeout hits."""
    host, port = "localhost", 4222
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                # If TCP connect succeeds, NATS is listening. Give JS another moment.
                time.sleep(0.5)
                return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def nats_container():
    """Module-scoped fixture that starts/stops the NATS container."""
    has_docker = False
    try:
        subprocess.run(["docker", "compose", "version"], capture_output=True, check=True)
        has_docker = True
    except Exception:
        pytest.skip("Docker Compose not available")

    if not has_docker:
        pytest.skip("Docker Compose not available")

    _docker_compose_up()

    if not _is_nats_available(timeout=30.0):
        _docker_compose_down()
        pytest.skip("NATS container did not become available within 30s")

    yield

    _docker_compose_down()


@pytest.mark.asyncio
async def test_nats_basic_connect(nats_container):
    """Basic connection and close cycle."""
    nc = await nats.connect(servers=[NATS_URL])
    assert nc.is_connected
    await nc.close()
    assert not nc.is_connected


@pytest.mark.asyncio
async def test_nats_pub_sub(nats_container):
    """Publish to a core NATS subject and receive via subscription."""
    received = []

    async def handler(msg):
        received.append(msg.data.decode())

    nc = await nats.connect(servers=[NATS_URL])
    sub = await nc.subscribe(TEST_SUBJECT, cb=handler)

    await nc.publish(TEST_SUBJECT, b"hello nats")
    # Give the server a moment to fan-out
    await asyncio.sleep(0.5)

    assert len(received) == 1
    assert received[0] == "hello nats"

    await sub.unsubscribe()
    await nc.close()


@pytest.mark.asyncio
async def test_jetstream_stream_pub_sub(nats_container):
    """Create a JetStream stream, publish, pull-subscribe, and verify delivery."""
    nc = await nats.connect(servers=[NATS_URL])
    js = nc.jetstream()

    # Ensure the stream doesn't already exist
    try:
        await js.delete_stream(TEST_STREAM)
    except Exception:  # noqa: S110
        pass

    # Create stream (add_stream is idempotent-ish, but we cleaned above)
    await js.add_stream(name=TEST_STREAM, subjects=[STREAM_SUBJECT])

    # Publish a message
    ack = await js.publish(STREAM_SUBJECT, b"hello jetstream")
    assert ack is not None

    # Pull subscribe on the stream
    psub = await js.pull_subscribe(STREAM_SUBJECT, stream=TEST_STREAM)
    msgs = await psub.fetch(1, timeout=2)
    assert len(msgs) == 1
    assert msgs[0].data == b"hello jetstream"
    await msgs[0].ack()

    # Clean up
    await js.delete_stream(TEST_STREAM)
    await nc.close()


@pytest.mark.asyncio
async def test_jetstream_direct_publish(nats_container):
    """Publish via the JetStream API directly without an explicit stream."""
    nc = await nats.connect(servers=[NATS_URL])
    js = nc.jetstream()

    # Re-use the same stream
    stream_name = TEST_STREAM + "_DP"
    try:
        await js.delete_stream(stream_name)
    except Exception:  # noqa: S110
        pass

    await js.add_stream(name=stream_name, subjects=["test.dp.*"])

    ack = await js.publish("test.dp.message", b"direct payload")
    assert ack.seq > 0

    psub = await js.pull_subscribe("test.dp.message", stream=stream_name)
    msgs = await psub.fetch(1, timeout=2)
    assert len(msgs) == 1
    assert msgs[0].data == b"direct payload"
    await msgs[0].ack()

    await js.delete_stream(stream_name)
    await nc.close()
