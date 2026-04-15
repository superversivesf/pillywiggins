import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.messaging.nats_bus import (
    BROADCAST_SUBJECT,
    COUNCIL_STREAM,
    DIRECT_SUBJECT_PREFIX,
    NatsBus,
)


@pytest.fixture
def bus():
    return NatsBus(nats_url="nats://localhost:4222", agent_id="puck")


def _mock_nats_connection():
    nc = MagicMock()
    nc.jetstream = MagicMock()
    js = MagicMock()
    nc.jetstream.return_value = js
    js.publish = AsyncMock()
    js.subscribe = AsyncMock()
    js.add_stream = AsyncMock()
    nc.drain = AsyncMock()
    nc.close = AsyncMock()
    return nc, js


@pytest.mark.asyncio
async def test_connect_creates_nats_connection(bus):
    nc, js = _mock_nats_connection()

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        await bus.connect()

    assert bus._nc is nc


@pytest.mark.asyncio
async def test_connect_creates_jetstream(bus):
    nc, js = _mock_nats_connection()

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        await bus.connect()

    assert bus._js is js
    nc.jetstream.assert_called_once()


@pytest.mark.asyncio
async def test_connect_adds_council_stream(bus):
    nc, js = _mock_nats_connection()

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        await bus.connect()

    js.add_stream.assert_called_once()
    call_kwargs = js.add_stream.call_args
    assert call_kwargs.kwargs["name"] == COUNCIL_STREAM
    subjects = call_kwargs.kwargs["subjects"]
    assert BROADCAST_SUBJECT in subjects
    assert f"{DIRECT_SUBJECT_PREFIX}.>" in subjects


@pytest.mark.asyncio
async def test_connect_handles_existing_stream(bus):
    nc, js = _mock_nats_connection()
    js.add_stream = AsyncMock(side_effect=Exception("stream already exists"))

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        await bus.connect()

    assert bus._nc is nc
    assert bus._js is js


@pytest.mark.asyncio
async def test_publish_broadcast_sends_to_correct_subject(bus):
    nc, js = _mock_nats_connection()

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        await bus.connect()
        await bus.publish_broadcast("insight", {"content": "hello"})

    js.publish.assert_called_once()
    call_args = js.publish.call_args
    assert call_args[0][0] == BROADCAST_SUBJECT
    payload = json.loads(call_args[0][1])
    assert payload["type"] == "insight"
    assert payload["from"] == "puck"
    assert payload["data"] == {"content": "hello"}
    assert "timestamp" in payload


@pytest.mark.asyncio
async def test_publish_direct_sends_to_agent_subject(bus):
    nc, js = _mock_nats_connection()

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        await bus.connect()
        await bus.publish_direct("mustardseed", "question", {"text": "what?"})

    js.publish.assert_called_once()
    call_args = js.publish.call_args
    expected_subject = f"{DIRECT_SUBJECT_PREFIX}.mustardseed"
    assert call_args[0][0] == expected_subject
    payload = json.loads(call_args[0][1])
    assert payload["type"] == "question"
    assert payload["from"] == "puck"
    assert payload["data"] == {"text": "what?"}


@pytest.mark.asyncio
async def test_subscribe_broadcast_creates_durable_subscription(bus):
    nc, js = _mock_nats_connection()

    handler = AsyncMock()

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        await bus.connect()
        await bus.subscribe_broadcast(handler)

    js.subscribe.assert_called_once()
    call_kwargs = js.subscribe.call_args.kwargs
    assert call_kwargs["subject"] == BROADCAST_SUBJECT
    assert call_kwargs["durable"] == "pillywiggins-puck-broadcast"
    assert call_kwargs["queue"] == "pillywiggins-puck-broadcast"
    assert len(bus._subs) == 1


@pytest.mark.asyncio
async def test_subscribe_direct_creates_durable_subscription(bus):
    nc, js = _mock_nats_connection()

    handler = AsyncMock()

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        await bus.connect()
        await bus.subscribe_direct(handler)

    js.subscribe.assert_called_once()
    call_kwargs = js.subscribe.call_args.kwargs
    expected_subject = f"{DIRECT_SUBJECT_PREFIX}.puck"
    assert call_kwargs["subject"] == expected_subject
    assert call_kwargs["durable"] == "pillywiggins-puck-direct"
    assert call_kwargs["queue"] == "pillywiggins-puck-direct"
    assert len(bus._subs) == 1


@pytest.mark.asyncio
async def test_close_drains_and_closes_connection(bus):
    nc, js = _mock_nats_connection()
    bus._nc = nc
    bus._js = js
    bus._subs = [MagicMock()]

    await bus.close()

    nc.drain.assert_called_once()
    nc.close.assert_called_once()
    assert bus._nc is None
    assert bus._js is None
    assert bus._subs == []


@pytest.mark.asyncio
async def test_close_handles_exception_gracefully(bus):
    nc, js = _mock_nats_connection()
    nc.drain = AsyncMock(side_effect=Exception("drain failed"))
    bus._nc = nc
    bus._js = js

    await bus.close()

    assert bus._nc is None
    assert bus._js is None


@pytest.mark.asyncio
async def test_close_does_nothing_if_not_connected(bus):
    assert bus._nc is None
    await bus.close()
    assert bus._nc is None


@pytest.mark.asyncio
async def test_graceful_degradation_connect_failure(bus):
    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, side_effect=Exception("connection refused")):
        await bus.connect()

    assert bus._nc is None
    assert bus._js is None


@pytest.mark.asyncio
async def test_graceful_degradation_publish_broadcast_noop(bus):
    bus._js = None
    bus._nc = None
    await bus.publish_broadcast("insight", {"content": "hello"})


@pytest.mark.asyncio
async def test_graceful_degradation_publish_direct_noop(bus):
    bus._js = None
    bus._nc = None
    await bus.publish_direct("mustardseed", "question", {"text": "what?"})


@pytest.mark.asyncio
async def test_graceful_degradation_subscribe_broadcast_noop(bus):
    bus._js = None
    bus._nc = None
    handler = AsyncMock()
    await bus.subscribe_broadcast(handler)


@pytest.mark.asyncio
async def test_graceful_degradation_subscribe_direct_noop(bus):
    bus._js = None
    bus._nc = None
    handler = AsyncMock()
    await bus.subscribe_direct(handler)


@pytest.mark.asyncio
async def test_make_payload_contains_required_fields(bus):
    payload_bytes = bus._make_payload("insight", {"content": "test"})
    payload = json.loads(payload_bytes)

    assert "type" in payload
    assert "from" in payload
    assert "timestamp" in payload
    assert "data" in payload
    assert payload["type"] == "insight"
    assert payload["from"] == "puck"
    assert payload["data"] == {"content": "test"}


@pytest.mark.asyncio
async def test_make_payload_timestamp_is_iso8601_utc(bus):
    payload_bytes = bus._make_payload("insight", {})
    payload = json.loads(payload_bytes)

    ts = payload["timestamp"]
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None


@pytest.mark.asyncio
async def test_parse_payload_extracts_type_and_data(bus):
    original_payload = bus._make_payload("skill_announcement", {"skill": "web_search"})
    mock_msg = MagicMock()
    mock_msg.data = original_payload

    msg_type, data = bus._parse_payload(mock_msg)

    assert msg_type == "skill_announcement"
    assert data == {"skill": "web_search"}


@pytest.mark.asyncio
async def test_broadcast_subscription_callback_parses_message(bus):
    received = []

    async def handler(msg_type, data):
        received.append((msg_type, data))

    nc, js = _mock_nats_connection()

    inner_cb = None

    async def capture_subscribe(**kwargs):
        nonlocal inner_cb
        inner_cb = kwargs["cb"]

    js.subscribe = AsyncMock(side_effect=capture_subscribe)

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        await bus.connect()
        await bus.subscribe_broadcast(handler)

    payload_bytes = bus._make_payload("proposal", {"text": "new idea"})
    mock_msg = MagicMock()
    mock_msg.data = payload_bytes

    assert inner_cb is not None
    await inner_cb(mock_msg)

    assert len(received) == 1
    assert received[0][0] == "proposal"
    assert received[0][1] == {"text": "new idea"}


@pytest.mark.asyncio
async def test_direct_subscription_callback_parses_message(bus):
    received = []

    async def handler(msg_type, data):
        received.append((msg_type, data))

    nc, js = _mock_nats_connection()

    inner_cb = None

    async def capture_subscribe(**kwargs):
        nonlocal inner_cb
        inner_cb = kwargs["cb"]

    js.subscribe = AsyncMock(side_effect=capture_subscribe)

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        await bus.connect()
        await bus.subscribe_direct(handler)

    payload_bytes = bus._make_payload("question", {"text": "anyone tried this?"})
    mock_msg = MagicMock()
    mock_msg.data = payload_bytes

    assert inner_cb is not None
    await inner_cb(mock_msg)

    assert len(received) == 1
    assert received[0][0] == "question"
    assert received[0][1] == {"text": "anyone tried this?"}


def test_broadcast_subject_constant():
    assert BROADCAST_SUBJECT == "council.broadcast"


def test_direct_subject_prefix_constant():
    assert DIRECT_SUBJECT_PREFIX == "council.direct"


def test_council_stream_constant():
    assert COUNCIL_STREAM == "COUNCIL"