from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from pillywiggins.adapters.telegram_adapter import HELP_TEXT, TelegramAdapter
from pillywiggins.messaging.unified import ChannelType


def _make_update(user_id=42, username="testuser", text="hello", chat_id=99):
    update = MagicMock()
    update.message = MagicMock()
    update.message.from_user = MagicMock()
    update.message.from_user.id = user_id
    update.message.from_user.username = username
    update.message.text = text
    update.message.chat_id = chat_id
    return update


def test_help_text_constant_exists():
    assert HELP_TEXT is not None
    assert isinstance(HELP_TEXT, str)
    assert "/help" in HELP_TEXT
    assert "/models" in HELP_TEXT
    assert "/model" in HELP_TEXT
    assert "/reset" in HELP_TEXT


def test_normalize_converts_update_to_unified_message():
    agent = MagicMock()
    settings = MagicMock()
    adapter = TelegramAdapter(agent, "fake-token", settings)
    update = _make_update(user_id=123, username="alice", text="hi there", chat_id=456)

    result = adapter.normalize(update)

    assert result.channel == ChannelType.TELEGRAM
    assert result.channel_user_id == "123"
    assert result.content == "hi there"
    assert result.conversation_key == "456"
    assert result.metadata == {"username": "alice"}


def test_normalize_handles_none_text():
    agent = MagicMock()
    settings = MagicMock()
    adapter = TelegramAdapter(agent, "fake-token", settings)
    update = _make_update(text=None)

    result = adapter.normalize(update)

    assert result.content == ""


def test_normalize_preserves_large_chat_id():
    agent = MagicMock()
    settings = MagicMock()
    adapter = TelegramAdapter(agent, "fake-token", settings)
    update = _make_update(chat_id=-1001234567890)

    result = adapter.normalize(update)

    assert result.conversation_key == "-1001234567890"


def test_normalize_timestamp_is_aware_utc():
    agent = MagicMock()
    settings = MagicMock()
    adapter = TelegramAdapter(agent, "fake-token", settings)
    update = _make_update()

    result = adapter.normalize(update)

    assert result.timestamp.tzinfo is not None