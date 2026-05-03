"""Real NATS + JetStream integration tests using Docker."""

import asyncio
import os
import socket
import subprocess
import time
import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("docker_available"),
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_nats_ready(url: str, timeout: int = 30):
    import nats

    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            nc = await nats.connect(url, connect_timeout=1)
            await nc.close()
            return
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5)
    pytest.fail(f"NATS did not become ready in {timeout}s: {last_err}")


@pytest.fixture(scope="module")
def nats_url_and_name():
    port = _free_port()
    name = f"pillywiggins-test-nats-{uuid.uuid4().hex[:8]}"
    # Note: we intentionally omit --rm so that docker start works for the
    # reconnection test.  Cleanup is handled explicitly in the finally block.
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "-p",
            f"{port}:4222",
            "--name",
            name,
            "nats:2.10-alpine",
            "--js",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    url = f"nats://127.0.0.1:{port}"
    try:
        asyncio.run(_wait_nats_ready(url))
        yield (url, name)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture
def nats_url(nats_url_and_name):
    return nats_url_and_name[0]


@pytest.fixture
def nats_container_name(nats_url_and_name):
    return nats_url_and_name[1]


# ---------------------------------------------------------------------------
# Broadcast pub/sub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_pub_sub(nats_url):
    from pillywiggins.messaging.nats_bus import NatsBus

    bus_a = NatsBus(nats_url=nats_url, agent_id="agent_a")
    bus_b = NatsBus(nats_url=nats_url, agent_id="agent_b")
    await bus_a.connect()
    await bus_b.connect()

    received = []

    async def handler(msg_type, data):
        received.append((msg_type, data))

    await bus_b.subscribe_broadcast(handler)
    await asyncio.sleep(0.5)

    await bus_a.publish_broadcast("skill_published", {"skill": "web_search"})
    await asyncio.sleep(1.0)

    assert len(received) == 1
    assert received[0][0] == "skill_published"
    assert received[0][1]["skill"] == "web_search"

    await bus_a.close()
    await bus_b.close()


# ---------------------------------------------------------------------------
# Direct message routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_message_routing(nats_url):
    from pillywiggins.messaging.nats_bus import NatsBus

    bus_a = NatsBus(nats_url=nats_url, agent_id="agent_a")
    bus_b = NatsBus(nats_url=nats_url, agent_id="agent_b")
    await bus_a.connect()
    await bus_b.connect()

    received_b = []

    async def handler_b(msg_type, data):
        received_b.append((msg_type, data))
        await bus_b.publish_direct("agent_a", "reply", {"text": "got it"})

    await bus_b.subscribe_direct(handler_b)
    await asyncio.sleep(0.5)

    received_a = []

    async def handler_a(msg_type, data):
        received_a.append((msg_type, data))

    await bus_a.subscribe_direct(handler_a)
    await asyncio.sleep(0.5)

    await bus_a.publish_direct("agent_b", "question", {"text": "hello?"})
    await asyncio.sleep(1.0)

    assert len(received_b) == 1
    assert received_b[0][0] == "question"

    assert len(received_a) == 1
    assert received_a[0][0] == "reply"
    assert received_a[0][1]["text"] == "got it"

    await bus_a.close()
    await bus_b.close()


# ---------------------------------------------------------------------------
# Reconnection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconnection(nats_url, nats_container_name):
    from pillywiggins.messaging.nats_bus import NatsBus

    bus = NatsBus(
        nats_url=nats_url,
        agent_id="recon_agent",
        reconnect_attempts=10,
        retry_delay=0.5,
        connect_timeout=2,
    )
    await bus.connect()
    assert bus.is_connected is True

    # Subscribe before the outage
    received = []

    async def handler(msg_type, data):
        received.append((msg_type, data))

    await bus.subscribe_broadcast(handler)
    await asyncio.sleep(0.3)

    # Stop the container (do NOT use --rm, otherwise start fails)
    subprocess.run(
        ["docker", "stop", "-t", "1", nats_container_name],
        capture_output=True,
        check=True,
    )

    # Wait for the client to notice the disconnect
    for _ in range(20):
        if not bus.is_connected:
            break
        await asyncio.sleep(0.5)
    assert bus.is_connected is False

    # Restart container
    subprocess.run(
        ["docker", "start", nats_container_name],
        capture_output=True,
        check=True,
    )
    await _wait_nats_ready(nats_url, timeout=30)

    # Reconnect and re-subscribe
    await bus.reconnect()
    assert bus.is_connected is True
    await bus.subscribe_broadcast(handler)
    await asyncio.sleep(0.5)

    # Publish from a fresh bus to verify re-subscription works
    bus2 = NatsBus(nats_url=nats_url, agent_id="publisher")
    await bus2.connect()
    await bus2.publish_broadcast("after_reconnect", {"status": "ok"})
    await asyncio.sleep(1.0)

    assert len(received) >= 1
    assert any(r[0] == "after_reconnect" and r[1]["status"] == "ok" for r in received)

    await bus.close()
    await bus2.close()
