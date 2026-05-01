import asyncio
import nats
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.messaging.nats_bus import (
    BROADCAST_SUBJECT,
    COUNCIL_STREAM,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_RECONNECT_ATTEMPTS,
    DEFAULT_RETRY_DELAY,
    DEFAULT_RETRY_MAX_DELAY,
    DIRECT_SUBJECT_PREFIX,
    NatsBus,
    NatsConnectError,
)


@pytest.fixture
def bus():
    return NatsBus(nats_url="nats://localhost:4222", agent_id="puck")


@pytest.fixture
def bus_with_fast_retry():
    """Bus configured for fast retry in tests (no real sleep)."""
    return NatsBus(
        nats_url="nats://localhost:4222",
        agent_id="puck",
        reconnect_attempts=3,
        retry_delay=0.01,  # minimal delay for tests
        retry_max_delay=0.01,
        connect_timeout=0.5,
    )


def _mock_nats_connection():
    nc = MagicMock()
    nc.is_connected = True
    nc.jetstream = MagicMock()
    js = MagicMock()
    nc.jetstream.return_value = js
    js.publish = AsyncMock()
    js.subscribe = AsyncMock()
    js.add_stream = AsyncMock()
    js.stream_info = AsyncMock(side_effect=nats.js.errors.NotFoundError)
    nc.drain = AsyncMock()
    nc.close = AsyncMock()
    return nc, js


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_creates_nats_connection(bus):
    nc, js = _mock_nats_connection()

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        await bus.connect()

    assert bus._nc is nc
    assert bus.is_connected is True


@pytest.mark.asyncio
async def test_connect_passes_timeout(bus):
    nc, js = _mock_nats_connection()
    bus._connect_timeout = 10.0

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc) as mock_connect:
        await bus.connect()

    mock_connect.assert_called_once()
    call_kwargs = mock_connect.call_args.kwargs
    assert call_kwargs["connect_timeout"] == 10.0


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
    assert call_kwargs.kwargs["config"].name == COUNCIL_STREAM
    subjects = call_kwargs.kwargs["config"].subjects
    assert BROADCAST_SUBJECT in subjects
    assert f"{DIRECT_SUBJECT_PREFIX}.>" in subjects


@pytest.mark.asyncio
async def test_connect_handles_existing_stream(bus):
    nc, js = _mock_nats_connection()
    js.stream_info = AsyncMock(return_value={})

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        await bus.connect()

    assert bus._nc is nc
    assert bus._js is js
    js.add_stream.assert_not_called()


# ---------------------------------------------------------------------------
# is_connected property
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_connected_false_before_connect(bus):
    assert bus.is_connected is False


@pytest.mark.asyncio
async def test_is_connected_true_after_connect(bus):
    nc, js = _mock_nats_connection()

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        await bus.connect()

    assert bus.is_connected is True


@pytest.mark.asyncio
async def test_is_connected_false_after_close(bus):
    nc, js = _mock_nats_connection()
    bus._nc = nc
    bus._js = js
    bus._connected = True

    await bus.close()

    assert bus.is_connected is False


# ---------------------------------------------------------------------------
# Retry logic tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_retries_on_failure(bus_with_fast_retry):
    """Connect should retry multiple times before raising NatsConnectError."""
    call_count = 0

    def failing_connect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise Exception("connection refused")

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, side_effect=failing_connect):
        with pytest.raises(NatsConnectError) as exc_info:
            await bus_with_fast_retry.connect()

    assert call_count == bus_with_fast_retry._reconnect_attempts
    assert exc_info.value.url == "nats://localhost:4222"
    assert exc_info.value.attempts == 3


@pytest.mark.asyncio
async def test_connect_succeeds_on_second_attempt(bus_with_fast_retry):
    """Connect should succeed if the second attempt works."""
    call_count = 0
    nc, js = _mock_nats_connection()

    def connect_with_retry(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("connection refused")
        return nc

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, side_effect=connect_with_retry):
        await bus_with_fast_retry.connect()

    assert bus_with_fast_retry.is_connected is True
    assert call_count == 2


@pytest.mark.asyncio
async def test_connect_raises_nats_connect_error(bus_with_fast_retry):
    """After all retries exhausted, connect() raises NatsConnectError."""
    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, side_effect=Exception("connection refused")):
        with pytest.raises(NatsConnectError) as exc_info:
            await bus_with_fast_retry.connect()

    assert exc_info.value.url == "nats://localhost:4222"
    assert exc_info.value.attempts == 3
    assert "connection refused" in str(exc_info.value)


@pytest.mark.asyncio
async def test_nats_connect_error_attributes():
    """NatsConnectError should carry URL, attempts, and last_error."""
    last_err = OSError("timeout")
    err = NatsConnectError("nats://nats:4222", 5, last_err)
    assert err.url == "nats://nats:4222"
    assert err.attempts == 5
    assert err.last_error is last_err
    assert "nats://nats:4222" in str(err)
    assert "5 attempts" in str(err)


@pytest.mark.asyncio
async def test_nats_connect_error_no_last_error():
    """NatsConnectError with last_error=None."""
    err = NatsConnectError("nats://nats:4222", 3, None)
    assert err.last_error is None
    assert "nats://nats:4222" in str(err)
    assert "3 attempts" in str(err)


# ---------------------------------------------------------------------------
# connect_or_log tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_or_log_returns_true_on_success(bus):
    nc, js = _mock_nats_connection()

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc):
        result = await bus.connect_or_log()

    assert result is True
    assert bus.is_connected is True


@pytest.mark.asyncio
async def test_connect_or_log_returns_false_on_failure(bus_with_fast_retry):
    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, side_effect=Exception("connection refused")):
        result = await bus_with_fast_retry.connect_or_log()

    assert result is False
    assert bus_with_fast_retry.is_connected is False


@pytest.mark.asyncio
async def test_connect_or_log_does_not_raise(bus_with_fast_retry):
    """connect_or_log should never raise, even when all retries fail."""
    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, side_effect=Exception("connection refused")):
        # This should NOT raise
        result = await bus_with_fast_retry.connect_or_log()

    assert result is False


# ---------------------------------------------------------------------------
# reconnect tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconnect_closes_existing_and_reconnects(bus):
    nc1, js1 = _mock_nats_connection()
    nc2, js2 = _mock_nats_connection()

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc1):
        await bus.connect()

    assert bus._nc is nc1
    assert bus.is_connected is True

    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, return_value=nc2):
        await bus.reconnect()

    assert bus._nc is nc2
    assert bus.is_connected is True


@pytest.mark.asyncio
async def test_reconnect_raises_on_failure(bus_with_fast_retry):
    """reconnect() should raise NatsConnectError if it can't reconnect."""
    with patch("pillywiggins.messaging.nats_bus.nats.connect", new_callable=AsyncMock, side_effect=Exception("connection refused")):
        with pytest.raises(NatsConnectError):
            await bus_with_fast_retry.reconnect()


# ---------------------------------------------------------------------------
# Publish tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Subscribe tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Close tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_drains_and_closes_connection(bus):
    nc, js = _mock_nats_connection()
    bus._nc = nc
    bus._js = js
    bus._connected = True
    bus._subs = [MagicMock()]

    await bus.close()

    nc.drain.assert_called_once()
    nc.close.assert_called_once()
    assert bus._nc is None
    assert bus._js is None
    assert bus._subs == []
    assert bus.is_connected is False


@pytest.mark.asyncio
async def test_close_handles_exception_gracefully(bus):
    nc, js = _mock_nats_connection()
    nc.drain = AsyncMock(side_effect=Exception("drain failed"))
    bus._nc = nc
    bus._js = js
    bus._connected = True

    await bus.close()

    assert bus._nc is None
    assert bus._js is None
    assert bus.is_connected is False


@pytest.mark.asyncio
async def test_close_does_nothing_if_not_connected(bus):
    assert bus._nc is None
    assert bus.is_connected is False
    await bus.close()
    assert bus._nc is None
    assert bus.is_connected is False


# ---------------------------------------------------------------------------
# Graceful degradation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graceful_degradation_publish_broadcast_noop(bus):
    bus._js = None
    bus._nc = None
    bus._connected = False
    await bus.publish_broadcast("insight", {"content": "hello"})


@pytest.mark.asyncio
async def test_graceful_degradation_publish_direct_noop(bus):
    bus._js = None
    bus._nc = None
    bus._connected = False
    await bus.publish_direct("mustardseed", "question", {"text": "what?"})


@pytest.mark.asyncio
async def test_graceful_degradation_subscribe_broadcast_noop(bus):
    bus._js = None
    bus._nc = None
    bus._connected = False
    handler = AsyncMock()
    await bus.subscribe_broadcast(handler)


@pytest.mark.asyncio
async def test_graceful_degradation_subscribe_direct_noop(bus):
    bus._js = None
    bus._nc = None
    bus._connected = False
    handler = AsyncMock()
    await bus.subscribe_direct(handler)


# ---------------------------------------------------------------------------
# Payload tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Subscription callback tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Monitor tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_triggers_reconnect_and_re_subscribes(bus):
    """When is_connected becomes False, _monitor calls reconnect and re-subscribes."""
    nc = MagicMock()
    nc.is_connected = False

    bus._nc = nc
    bus._broadcast_handler = AsyncMock()
    bus._direct_handler = AsyncMock()

    reconnect_called = False

    async def fake_reconnect():
        nonlocal reconnect_called
        reconnect_called = True
        bus._nc = nc  # restore connection

    bus.reconnect = fake_reconnect

    subscribe_broadcast_called = False
    subscribe_direct_called = False

    async def fake_subscribe_broadcast(handler):
        nonlocal subscribe_broadcast_called
        subscribe_broadcast_called = True

    async def fake_subscribe_direct(handler):
        nonlocal subscribe_direct_called
        subscribe_direct_called = True

    bus.subscribe_broadcast = fake_subscribe_broadcast
    bus.subscribe_direct = fake_subscribe_direct

    sleep_count = 0

    async def fake_sleep(_):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError()

    with patch("pillywiggins.messaging.nats_bus.asyncio.sleep", fake_sleep):
        await bus._monitor()

    assert reconnect_called is True
    assert subscribe_broadcast_called is True
    assert subscribe_direct_called is True


# ---------------------------------------------------------------------------
# Constant tests
# ---------------------------------------------------------------------------


def test_broadcast_subject_constant():
    assert BROADCAST_SUBJECT == "council.broadcast"


def test_direct_subject_prefix_constant():
    assert DIRECT_SUBJECT_PREFIX == "council.direct"


def test_council_stream_constant():
    assert COUNCIL_STREAM == "COUNCIL"


def test_default_connect_timeout():
    assert DEFAULT_CONNECT_TIMEOUT == 5


def test_default_reconnect_attempts():
    assert DEFAULT_RECONNECT_ATTEMPTS == 5


def test_default_retry_delay():
    assert DEFAULT_RETRY_DELAY == 1.0


def test_default_retry_max_delay():
    assert DEFAULT_RETRY_MAX_DELAY == 60.0