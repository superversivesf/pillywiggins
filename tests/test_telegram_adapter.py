"""Tests for telegram_adapter.py."""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-populate mock modules for telegram so the adapter
# can be imported even when the optional dep is not installed.
if "telegram" not in sys.modules:
    telegram_mock = MagicMock()
    telegram_mock.Update = MagicMock()
    telegram_error_mock = MagicMock()

    class _MockTimedOut(Exception):
        pass

    telegram_error_mock.TimedOut = _MockTimedOut
    telegram_mock.error = telegram_error_mock
    sys.modules["telegram"] = telegram_mock
    telegram_ext_mock = MagicMock()
    telegram_ext_mock.Application = MagicMock()
    telegram_ext_mock.CommandHandler = MagicMock()
    telegram_ext_mock.MessageHandler = MagicMock()
    telegram_ext_mock.filters = MagicMock()
    sys.modules["telegram.ext"] = telegram_ext_mock

from pillywiggins.adapters.telegram_adapter import TelegramAdapter, TimedOut
from pillywiggins.messaging.unified import ChannelType
from tests.helpers import make_mock_agent, make_mock_settings


def _make_update(
    text="hello",
    user_id=42,
    username="testuser",
    first_name="Test",
    is_bot=False,
    chat_id=99,
    chat_type="private",
):
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = text
    update.message.chat_id = chat_id
    update.message.chat = MagicMock()
    update.message.chat.type = chat_type
    update.message.from_user = MagicMock()
    update.message.from_user.id = user_id
    update.message.from_user.username = username
    update.message.from_user.first_name = first_name
    update.message.from_user.is_bot = is_bot
    return update


def _make_adapter():
    agent = make_mock_agent(channel="telegram")
    agent.personality.bot_chat_limit = 3
    agent.should_process_message = MagicMock(return_value=True)
    agent._get_history = MagicMock(return_value=[])
    agent._skill_registry = MagicMock()
    agent._skill_registry.list_skills = MagicMock(return_value=[])
    settings = make_mock_settings()
    adapter = TelegramAdapter(agent, "fake-token", settings)
    adapter._app = MagicMock()
    adapter._app.bot = MagicMock()
    adapter._app.bot.send_message = AsyncMock()
    return adapter


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


def test_normalize_creates_unified_message():
    adapter = _make_adapter()
    update = _make_update(
        text="hi there", user_id=123, username="alice", chat_id=456, chat_type="private"
    )

    result = adapter.normalize(update)

    assert result.channel == ChannelType.TELEGRAM
    assert result.channel_user_id == "123"
    assert result.content == "hi there"
    assert result.conversation_key == "456"
    assert result.metadata["username"] == "alice"
    assert result.metadata["is_bot"] is False


def test_normalize_uses_first_name_when_no_username():
    adapter = _make_adapter()
    update = _make_update(username=None, first_name="Bob", user_id=42, chat_id=7)

    result = adapter.normalize(update)

    assert result.metadata["username"] == "Bob"


def test_normalize_uses_user_id_when_no_username_or_first_name():
    adapter = _make_adapter()
    update = _make_update(username=None, first_name=None, user_id=42, chat_id=7)

    result = adapter.normalize(update)

    assert result.metadata["username"] == "42"


def test_normalize_group_uses_user_id_as_conversation_key():
    adapter = _make_adapter()
    update = _make_update(user_id=123, chat_id=456, chat_type="supergroup")

    result = adapter.normalize(update)

    assert result.conversation_key == "123"
    assert result.metadata["is_group"] is True
    assert result.metadata["chat_id"] == "456"


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_uses_metadata_chat_id():
    adapter = _make_adapter()
    await adapter.send("conv-key", "hello", metadata={"chat_id": "789"})
    adapter._app.bot.send_message.assert_awaited_once_with(chat_id=789, text="hello")


@pytest.mark.asyncio
async def test_send_falls_back_to_channel_id():
    adapter = _make_adapter()
    await adapter.send("456", "hello")
    adapter._app.bot.send_message.assert_awaited_once_with(chat_id=456, text="hello")


# ---------------------------------------------------------------------------
# _on_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_message_ignores_empty_text():
    adapter = _make_adapter()
    update = _make_update(text=None)
    await adapter._on_message(update, None)
    adapter.agent.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_rejects_unauthorized_user():
    adapter = _make_adapter()
    adapter._allow_all = False
    adapter._allowed_user_ids = {42}
    update = _make_update(user_id=999, chat_id=99)
    update.message.reply_text = AsyncMock()

    await adapter._on_message(update, None)

    adapter.agent.handle_message.assert_not_called()
    update.message.reply_text.assert_awaited_once_with("You are not authorized to use this bot.")


@pytest.mark.asyncio
async def test_on_message_sends_reply():
    adapter = _make_adapter()
    adapter.agent.handle_message = AsyncMock(return_value="Puck says hi")
    update = _make_update(text="hey", user_id=1, chat_id=99)

    await adapter._on_message(update, None)

    adapter.agent.handle_message.assert_awaited_once()
    adapter._app.bot.send_message.assert_awaited_once_with(chat_id=99, text="Puck says hi")


@pytest.mark.asyncio
async def test_on_message_logs_warning_on_timed_out(caplog):
    adapter = _make_adapter()
    adapter.agent.handle_message = AsyncMock(return_value="reply")
    adapter.send = AsyncMock(side_effect=TimedOut())
    update = _make_update(text="hey", user_id=1, chat_id=99)

    with caplog.at_level("WARNING", logger="pillywiggins.adapters.telegram_adapter"):
        await adapter._on_message(update, None)

    # Should not propagate
    assert "Timed out sending reply to Telegram chat 99" in caplog.text
    assert "message may be retried automatically" in caplog.text


@pytest.mark.asyncio
async def test_on_message_logs_error_on_other_exceptions(caplog):
    adapter = _make_adapter()
    adapter.agent.handle_message = AsyncMock(return_value="reply")
    adapter.send = AsyncMock(side_effect=RuntimeError("boom"))
    update = _make_update(text="hey", user_id=1, chat_id=99)

    with caplog.at_level("ERROR", logger="pillywiggins.adapters.telegram_adapter"):
        await adapter._on_message(update, None)

    assert "Error handling Telegram message" in caplog.text
    assert "RuntimeError: boom" in caplog.text


# ---------------------------------------------------------------------------
# authorization
# ---------------------------------------------------------------------------


def test_is_authorized_allows_all():
    adapter = _make_adapter()
    assert adapter._is_authorized(999) is True


def test_is_authorized_restricts_to_allowed_ids():
    adapter = _make_adapter()
    adapter._allow_all = False
    adapter._allowed_user_ids = {42, 100}
    assert adapter._is_authorized(42) is True
    assert adapter._is_authorized(100) is True
    assert adapter._is_authorized(999) is False


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_help_replies_with_help_text():
    adapter = _make_adapter()
    update = _make_update()
    update.message.reply_text = AsyncMock()

    await adapter._cmd_help(update, None)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "/help" in text


@pytest.mark.asyncio
async def test_cmd_reset_clears_history():
    adapter = _make_adapter()
    update = _make_update(chat_id=99)
    update.message.reply_text = AsyncMock()

    await adapter._cmd_reset(update, None)

    adapter.agent.clear_history.assert_awaited_once_with(conversation_key="99")
    update.message.reply_text.assert_awaited_once_with("Conversation history cleared.")


@pytest.mark.asyncio
async def test_cmd_compact_calls_agent():
    adapter = _make_adapter()
    update = _make_update(chat_id=99)
    update.message.reply_text = AsyncMock()

    await adapter._cmd_compact(update, None)

    adapter.agent.compact_history.assert_awaited_once_with(conversation_key="99")
