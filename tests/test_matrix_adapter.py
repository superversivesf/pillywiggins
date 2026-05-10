"""Tests for matrix_adapter.py."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-populate mock modules for matrix-nio so the adapter
# can be imported even when the optional dep is not installed.
if "nio" not in sys.modules:
    nio_mock = MagicMock()
    nio_mock.AsyncClient = MagicMock()
    # SyncResponse must be a real type for isinstance() checks.
    # Using MagicMock as the base class lets us set arbitrary attributes
    # (e.g. .rooms.join) and still pass isinstance checks.
    class MockSyncResponse(MagicMock):
        pass
    nio_mock.SyncResponse = MockSyncResponse
    # RoomMessageText must also be a real class for isinstance() checks
    class MockRoomMessageText(MagicMock):
        pass
    nio_mock.RoomMessageText = MockRoomMessageText
    sys.modules["nio"] = nio_mock

from pillywiggins.adapters.matrix_adapter import MatrixAdapter
from pillywiggins.messaging.unified import ChannelType


@pytest.fixture
def adapter():
    agent = MagicMock()
    agent.personality = MagicMock()
    agent.personality.bot_chat_limit = 0
    agent.agent_id = "test-agent"
    settings = MagicMock()
    settings.allowed_user_ids = ""
    settings.get_allowed_user_ids.return_value = set()
    return MatrixAdapter(
        agent=agent,
        homeserver="https://matrix.example.com",
        user_id="@bot:example.com",
        access_token="test-token",
        settings=settings,
    )


def test_matrix_adapter_init(adapter):
    assert adapter.homeserver == "https://matrix.example.com"
    assert adapter.user_id == "@bot:example.com"


@pytest.mark.asyncio
async def test_connect_sets_access_token(adapter):
    """connect() should set the access token on the AsyncClient."""
    nio_mod = sys.modules["nio"]
    mock_client = AsyncMock()
    nio_mod.AsyncClient.return_value = mock_client
    mock_client.sync = AsyncMock(return_value=MagicMock())

    await adapter.connect()

    assert adapter._client is mock_client
    assert mock_client.access_token == "test-token"
    mock_client.sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_success_logs_info(adapter, caplog):
    """connect() with a SyncResponse should log success."""
    nio_mod = sys.modules["nio"]
    mock_client = AsyncMock()
    nio_mod.AsyncClient.return_value = mock_client
    mock_resp = MagicMock(spec=nio_mod.SyncResponse)
    mock_client.sync = AsyncMock(return_value=mock_resp)

    with caplog.at_level("INFO", logger="pillywiggins.adapters.matrix_adapter"):
        await adapter.connect()

    assert adapter._client is mock_client
    mock_client.sync.assert_awaited_once_with(timeout_ms=30000, full_state=True)
    assert "Matrix client connected" in caplog.text


@pytest.mark.asyncio
async def test_connect_failure_logs_warning(adapter, caplog):
    """connect() with a non-SyncResponse should log a warning."""
    nio_mod = sys.modules["nio"]
    mock_client = AsyncMock()
    nio_mod.AsyncClient.return_value = mock_client
    mock_client.sync = AsyncMock(return_value=MagicMock())

    with caplog.at_level("WARNING", logger="pillywiggins.adapters.matrix_adapter"):
        await adapter.connect()

    assert "Matrix sync returned non-success" in caplog.text


@pytest.mark.asyncio
async def test_listen_processes_room_message(adapter):
    """listen() should read sync responses and pass RoomMessageText events to _handle_message."""
    nio_mod = sys.modules["nio"]
    mock_client = AsyncMock()
    adapter._client = mock_client

    mock_event = nio_mod.RoomMessageText()
    mock_event.sender = "@user:example.com"
    mock_event.body = "Hello!"
    mock_event.event_id = "$event123"
    mock_event.server_timestamp = 1234567890

    mock_room_info = MagicMock()
    mock_room_info.timeline.events = [mock_event]

    mock_resp = nio_mod.SyncResponse()
    mock_resp.rooms = MagicMock()
    mock_resp.rooms.join = {"!room:example.com": mock_room_info}

    mock_client.sync = AsyncMock(return_value=mock_resp)

    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        with patch.object(adapter, "_handle_message", new_callable=AsyncMock) as mock_handle:
            with patch.object(adapter._shutdown_event, "is_set", side_effect=[False, True]):
                await adapter.listen()

            pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            mock_handle.assert_awaited_once()
            msg = mock_handle.call_args[0][0]
            assert msg.content == "Hello!"
            assert msg.metadata["sender"] == "@user:example.com"
            assert mock_handle.call_args[0][1] == "!room:example.com"


@pytest.mark.asyncio
async def test_handle_message_authorized_routes_to_agent(adapter):
    """_handle_message() should route normal messages to the agent and send the reply."""
    adapter._allow_all = True
    adapter.agent.should_process_message = MagicMock(return_value=True)
    adapter.agent.handle_message = AsyncMock(return_value="Agent reply")

    with patch.object(adapter, "send", new_callable=AsyncMock) as mock_send:
        msg = adapter.normalize({
            "room_id": "!room:example.com",
            "sender": "@user:example.com",
            "body": "Hello agent",
            "event_id": "$abc",
            "timestamp": 1234567890,
        })
        await adapter._handle_message(msg, "!room:example.com")

        adapter.agent.handle_message.assert_awaited_once_with(msg)
        mock_send.assert_awaited_once_with("!room:example.com", "Agent reply")


@pytest.mark.asyncio
async def test_handle_message_unauthorized_skips(adapter):
    """_handle_message() should ignore messages from unauthorized users."""
    adapter._allow_all = False
    adapter._allowed_user_ids = set()
    adapter.agent.handle_message = AsyncMock()

    with patch.object(adapter, "send", new_callable=AsyncMock) as mock_send:
        with patch.object(adapter, "dispatch_command") as mock_dispatch:
            msg = adapter.normalize({
                "room_id": "!room:example.com",
                "sender": "@unauthorized:example.com",
                "body": "Hello",
                "event_id": "$abc",
                "timestamp": 1234567890,
            })
            await adapter._handle_message(msg, "!room:example.com")

            adapter.agent.handle_message.assert_not_called()
            mock_dispatch.assert_not_called()
            mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_command_dispatches(adapter):
    """_handle_message() should dispatch commands prefixed with '!' and send the response."""
    adapter._allow_all = True
    adapter.agent.should_process_message = MagicMock(return_value=True)

    with patch.object(adapter, "dispatch_command", new_callable=AsyncMock, return_value="Status: OK") as mock_dispatch:
        with patch.object(adapter, "send", new_callable=AsyncMock) as mock_send:
            msg = adapter.normalize({
                "room_id": "!room:example.com",
                "sender": "@user:example.com",
                "body": "!status",
                "event_id": "$abc",
                "timestamp": 1234567890,
            })
            await adapter._handle_message(msg, "!room:example.com")

            mock_dispatch.assert_awaited_once_with("!status", "!room:example.com")
            mock_send.assert_awaited_once_with("!room:example.com", "Status: OK")


@pytest.mark.asyncio
async def test_send_success(adapter):
    """send() should call room_send with the correct Matrix message payload."""
    mock_client = AsyncMock()
    adapter._client = mock_client

    await adapter.send("!room:example.com", "Hello Matrix")

    mock_client.room_send.assert_awaited_once_with(
        room_id="!room:example.com",
        message_type="m.room.message",
        content={
            "msgtype": "m.text",
            "body": "Hello Matrix",
            "format": "org.matrix.custom.html",
            "formatted_body": "Hello Matrix",
        },
    )


@pytest.mark.asyncio
async def test_send_failure_logs_error(adapter, caplog):
    """send() should log an error when room_send raises an exception."""
    mock_client = AsyncMock()
    mock_client.room_send = AsyncMock(side_effect=Exception("Boom"))
    adapter._client = mock_client

    with caplog.at_level("ERROR", logger="pillywiggins.adapters.matrix_adapter"):
        await adapter.send("!room:example.com", "Hello")

    assert "Failed to send Matrix message" in caplog.text


def test_normalize_creates_unified_message(adapter):
    """normalize() should map Matrix-specific fields to a UnifiedMessage."""
    msg = adapter.normalize({
        "room_id": "!room:example.com",
        "sender": "@user:example.com",
        "body": "Hello",
        "event_id": "$abc",
        "timestamp": 1234567890,
    })
    assert msg.channel == ChannelType.MATRIX
    assert msg.channel_user_id == "@user:example.com"
    assert msg.content == "Hello"
    assert msg.conversation_key == "!room:example.com"
    assert msg.metadata["event_id"] == "$abc"
    assert msg.metadata["sender"] == "@user:example.com"
    assert msg.metadata["server_timestamp"] == 1234567890
    assert msg.metadata["is_group"] is True
    assert msg.metadata["is_bot"] is False


def test_is_authorized_all(adapter):
    adapter._allow_all = True
    assert adapter._is_authorized("@anyone:example.com") is True


def test_is_authorized_specific(adapter):
    adapter._allow_all = False
    adapter._allowed_user_ids = {"@user:example.com"}
    assert adapter._is_authorized("@user:example.com") is True
    assert adapter._is_authorized("@other:example.com") is False
