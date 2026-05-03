"""Tests for matrix_adapter.py."""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-populate mock modules for matrix-nio so the adapter
# can be imported even when the optional dep is not installed.
if "nio" not in sys.modules:
    nio_mock = MagicMock()
    nio_mock.AsyncClient = MagicMock()
    nio_mock.RoomMessageText = MagicMock()
    # SyncResponse must be a real type for isinstance() checks
    class MockSyncResponse:
        pass
    nio_mock.SyncResponse = MockSyncResponse
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


def test_normalize_creates_unified_message(adapter):
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


def test_is_authorized_all(adapter):
    adapter._allow_all = True
    assert adapter._is_authorized("@anyone:example.com") is True


def test_is_authorized_specific(adapter):
    adapter._allow_all = False
    adapter._allowed_user_ids = {"@user:example.com"}
    assert adapter._is_authorized("@user:example.com") is True
    assert adapter._is_authorized("@other:example.com") is False


def test_should_respond_to_bot_zero_limit(adapter):
    """With bot_chat_limit=0, never respond to bots."""
    adapter.agent.personality.bot_chat_limit = 0
    assert adapter._should_respond_to_bot("room1", True) is False
