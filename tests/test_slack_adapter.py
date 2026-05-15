"""Tests for slack_adapter.py."""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-populate mock modules for slack_bolt and slack_sdk so the adapter
# can be imported even when the optional deps are not installed.
if "slack_bolt" not in sys.modules:
    slack_bolt_mock = MagicMock()
    slack_bolt_mock.AsyncApp = MagicMock()
    sys.modules["slack_bolt"] = slack_bolt_mock
    sys.modules["slack_bolt.async_app"] = slack_bolt_mock
    socket_handler_mock = MagicMock()
    socket_handler_mock.AsyncSocketModeHandler = MagicMock()
    sys.modules["slack_bolt.adapter.socket_mode.async_handler"] = socket_handler_mock
if "slack_sdk.web.async_client" not in sys.modules:
    slack_sdk_mock = MagicMock()
    slack_sdk_mock.AsyncWebClient = MagicMock()
    sys.modules["slack_sdk.web.async_client"] = slack_sdk_mock

from pillywiggins.adapters.slack_adapter import SlackAdapter


@pytest.fixture
def adapter():
    agent = MagicMock()
    agent.personality = MagicMock()
    agent.personality.bot_chat_limit = 3
    agent.agent_id = "test-agent"
    settings = MagicMock()
    settings.allowed_user_ids = ""
    settings.get_allowed_user_ids.return_value = set()
    return SlackAdapter(
        agent=agent,
        bot_token="xoxb-test-token",
        settings=settings,
    )


def test_slack_adapter_init(adapter):
    assert adapter.bot_token == "xoxb-test-token"


@pytest.mark.asyncio
async def test_connect_creates_app_and_client(adapter):
    """connect() should create AsyncApp and AsyncWebClient."""
    slack_mock = sys.modules["slack_bolt"]
    web_mock = sys.modules["slack_sdk.web.async_client"]
    slack_mock.AsyncApp.return_value = MagicMock()
    web_mock.AsyncWebClient.return_value = MagicMock()

    await adapter.connect()

    slack_mock.AsyncApp.assert_called_once_with(token="xoxb-test-token")
    web_mock.AsyncWebClient.assert_called_once_with(token="xoxb-test-token")
    assert adapter._app is not None
    assert adapter._web_client is not None


@pytest.mark.asyncio
async def test_send_posts_message(adapter):
    """send() should call chat_postMessage on the web client."""
    mock_client = AsyncMock()
    adapter._web_client = mock_client

    await adapter.send("C123", "Hello!", {"thread_ts": "1234.56"})

    mock_client.chat_postMessage.assert_awaited_once_with(
        channel="C123",
        text="Hello!",
        thread_ts="1234.56",
    )


def test_normalize_creates_unified_message(adapter):
    from pillywiggins.messaging.unified import ChannelType

    msg = adapter.normalize({
        "user": "U123",
        "text": "Hello",
        "channel": "C456",
        "ts": "1234.56",
        "thread_ts": "1234.00",
        "is_group": True,
    })
    assert msg.channel == ChannelType.SLACK
    assert msg.channel_user_id == "U123"
    assert msg.content == "Hello"
    assert msg.conversation_key == "1234.56"
    assert msg.metadata["channel"] == "C456"
    assert msg.metadata["is_group"] is True


def test_is_authorized_all(adapter):
    adapter._allow_all = True
    assert adapter._is_authorized("U123") is True


@pytest.mark.asyncio
async def test_listen_not_connected_raises(adapter):
    with pytest.raises(RuntimeError, match="not connected"):
        await adapter.listen()


@pytest.mark.asyncio
async def test_listen_starts_handler_and_shuts_down(adapter):
    adapter._app = MagicMock()
    adapter._shutdown_event.set()
    with patch("pillywiggins.adapters.slack_adapter.AsyncSocketModeHandler") as MockHandler:
        mock_handler = AsyncMock()
        MockHandler.return_value = mock_handler
        await adapter.listen()
        MockHandler.assert_called_once_with(adapter._app, adapter.bot_token)
        mock_handler.start_async.assert_awaited_once()
        mock_handler.close_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_bot_user_id_caches(adapter):
    mock_client = AsyncMock()
    mock_client.auth_test.return_value = {"user_id": "UBOT123"}
    result = await adapter._get_bot_user_id(mock_client)
    assert result == "UBOT123"
    mock_client.auth_test.assert_awaited_once()
    # Second call uses cache
    mock_client.auth_test.reset_mock()
    result2 = await adapter._get_bot_user_id(mock_client)
    assert result2 == "UBOT123"
    mock_client.auth_test.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_skips_bot_own_message(adapter):
    adapter._allow_all = True
    mock_client = AsyncMock()
    mock_client.auth_test.return_value = {"user_id": "UBOT"}
    say = AsyncMock()
    body = {"event": {"user": "UBOT", "text": "hi", "channel": "C1", "ts": "123"}}
    await adapter._on_message(body, say, mock_client)
    say.assert_not_awaited()
    adapter.agent.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_skips_unauthorized_user(adapter):
    adapter._allow_all = False
    adapter._allowed_user_ids = {"U999"}
    mock_client = AsyncMock()
    mock_client.auth_test.return_value = {"user_id": "UBOT"}
    say = AsyncMock()
    body = {"event": {"user": "U123", "text": "hi", "channel": "C1", "ts": "123"}}
    await adapter._on_message(body, say, mock_client)
    say.assert_not_awaited()
    adapter.agent.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_handles_normal_message(adapter):
    adapter._allow_all = True
    adapter.agent.should_process_message.return_value = True
    adapter.agent.handle_message = AsyncMock(return_value="Reply text")
    mock_client = AsyncMock()
    mock_client.auth_test.return_value = {"user_id": "UBOT"}
    say = AsyncMock()
    body = {
        "event": {
            "user": "U123",
            "text": "hello",
            "channel": "C1",
            "ts": "123.45",
            "thread_ts": "123.00",
            "channel_type": "channel",
            "bot_id": None,
        }
    }
    await adapter._on_message(body, say, mock_client)
    adapter.agent.handle_message.assert_awaited_once()
    args, _ = adapter.agent.handle_message.call_args
    msg = args[0]
    assert msg.channel_user_id == "U123"
    assert msg.content == "hello"
    assert msg.metadata["thread_ts"] == "123.00"
    assert msg.metadata["is_group"] is True
    say.assert_awaited_once_with("Reply text")


@pytest.mark.asyncio
async def test_on_message_dispatches_command(adapter):
    adapter._allow_all = True
    adapter.agent.should_process_message.return_value = True
    say = AsyncMock()
    mock_client = AsyncMock()
    mock_client.auth_test.return_value = {"user_id": "UBOT"}
    body = {"event": {"user": "U123", "text": "!help", "channel": "C1", "ts": "123"}}
    await adapter._on_message(body, say, mock_client)
    adapter.agent.handle_message.assert_not_called()
    say.assert_awaited_once_with(adapter.HELP_TEXT)


@pytest.mark.asyncio
async def test_on_message_agent_error(adapter):
    adapter._allow_all = True
    adapter.agent.should_process_message.return_value = True
    adapter.agent.handle_message = AsyncMock(side_effect=Exception("boom"))
    mock_client = AsyncMock()
    mock_client.auth_test.return_value = {"user_id": "UBOT"}
    say = AsyncMock()
    body = {"event": {"user": "U123", "text": "hello", "channel": "C1", "ts": "123"}}
    await adapter._on_message(body, say, mock_client)
    say.assert_awaited_once_with("Sorry, something went wrong processing your message.")


@pytest.mark.asyncio
async def test_send_failure_logs_exception(adapter):
    mock_client = AsyncMock()
    mock_client.chat_postMessage = AsyncMock(side_effect=Exception("network down"))
    adapter._web_client = mock_client
    await adapter.send("C123", "Hello!", {"thread_ts": "1234.56"})
    mock_client.chat_postMessage.assert_awaited_once_with(
        channel="C123",
        text="Hello!",
        thread_ts="1234.56",
    )


def test_is_authorized_specific_user(adapter):
    """Authorized user should pass."""
    adapter._allow_all = False
    adapter._allowed_user_ids = {"U123"}
    assert adapter._is_authorized("U123") is True


def test_is_authorized_string_user_id():
    """_is_authorized should work with non-numeric string user IDs."""
    agent = MagicMock()
    agent.personality = MagicMock()
    agent.personality.bot_chat_limit = 3
    agent.agent_id = "test-agent"
    settings = MagicMock()
    settings.allowed_user_ids = "U07ABCD1234,W018XY9999"
    settings.get_allowed_user_ids.return_value = {"U07ABCD1234", "W018XY9999"}
    adapter = SlackAdapter(agent=agent, bot_token="xoxb-test-token", settings=settings)
    assert adapter._is_authorized("U07ABCD1234") is True
    assert adapter._is_authorized("W018XY9999") is True
    assert adapter._is_authorized("U999UNKNOWN") is False


def test_is_authorized_mixed_numeric_and_string_ids():
    """_is_authorized should work with mixed int/string IDs (all treated as strings)."""
    agent = MagicMock()
    agent.personality = MagicMock()
    agent.personality.bot_chat_limit = 3
    agent.agent_id = "test-agent"
    settings = MagicMock()
    settings.allowed_user_ids = "42,U07ABCD1234,100"
    settings.get_allowed_user_ids.return_value = {"42", "U07ABCD1234", "100"}
    adapter = SlackAdapter(agent=agent, bot_token="xoxb-test-token", settings=settings)
    # String comparison means "42" matches "42"
    assert adapter._is_authorized("42") is True
    assert adapter._is_authorized("U07ABCD1234") is True
    assert adapter._is_authorized("100") is True
    # int 42 passed as argument gets str()-ed by BaseAdapter, so it should match
    assert adapter._is_authorized(42) is True


def test_connect_logs_masked_token(adapter, caplog):
    """connect() should not log the full token prefix."""
    import logging
    slack_mock = sys.modules["slack_bolt"]
    web_mock = sys.modules["slack_sdk.web.async_client"]
    slack_mock.AsyncApp.return_value = MagicMock()
    web_mock.AsyncWebClient.return_value = MagicMock()

    import asyncio
    with caplog.at_level(logging.INFO, logger="pillywiggins.adapters.slack_adapter"):
        asyncio.run(adapter.connect())

    log_text = caplog.text
    # The raw token should never appear in logs (even partially beyond the mask)
    assert "xoxb-test-token" not in log_text
    # Should indicate masked/token info in a safe way
    assert "token" in log_text.lower()


def test_mask_token_helper():
    """The _mask_token helper should redact all but first/last few chars."""
    from pillywiggins.adapters.slack_adapter import SlackAdapter

    # Short token - should be fully masked or show very little
    result_short = SlackAdapter._mask_token("abc")
    assert "abc" not in result_short

    # Typical Slack bot token
    result = SlackAdapter._mask_token("xoxb-1234567890-abcdef1234567890abcdef")
    assert "xoxb-1234567890" not in result  # middle should be hidden
    assert result.startswith("xoxb-")  # prefix preserved
    assert "****" in result  # masked portion
    assert result.endswith("cdef")  # last few chars preserved

    # Empty token
    result_empty = SlackAdapter._mask_token("")
    assert result_empty == ""

    # None token
    result_none = SlackAdapter._mask_token(None)
    assert result_none == ""