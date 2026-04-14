import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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
    update.message.reply_text = AsyncMock()
    return update


def _make_adapter():
    agent = MagicMock()
    agent.model_name = "qwen3.5:8b"
    agent.handle_message = AsyncMock(return_value="response")
    agent.switch_model = MagicMock()
    agent.clear_history = MagicMock()
    settings = MagicMock()
    settings.llm_base_url = "http://localhost:11434"
    settings.llm_api_key = ""
    settings.llm_provider = "ollama"
    adapter = TelegramAdapter(agent, "fake-token", settings)
    adapter._app = MagicMock()
    adapter._app.bot = MagicMock()
    adapter._app.bot.send_message = AsyncMock()
    adapter._app.bot.send_chat_action = AsyncMock()
    adapter._app.updater = MagicMock()
    adapter._app.updater.start_polling = AsyncMock()
    adapter._app.updater.stop = AsyncMock()
    adapter._app.initialize = AsyncMock()
    adapter._app.start = AsyncMock()
    adapter._app.stop = AsyncMock()
    adapter._app.shutdown = AsyncMock()
    return adapter


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


@pytest.mark.asyncio
async def test_send_calls_bot_send_message():
    adapter = _make_adapter()
    await adapter.send("12345", "hello world")

    adapter._app.bot.send_message.assert_called_once_with(chat_id=12345, text="hello world")


@pytest.mark.asyncio
async def test_cmd_help_replies_with_help_text():
    adapter = _make_adapter()
    update = _make_update()
    context = MagicMock()

    await adapter._cmd_help(update, context)

    update.message.reply_text.assert_called_once_with(HELP_TEXT, parse_mode="Markdown")


@pytest.mark.asyncio
async def test_cmd_models_replies_with_model_list():
    adapter = _make_adapter()
    update = _make_update()
    context = MagicMock()

    mock_model = MagicMock()
    mock_model.id = "qwen3.5:8b"
    mock_model.owned_by = "ollama"
    with patch("pillywiggins.adapters.telegram_adapter.list_models", new_callable=AsyncMock, return_value=[mock_model]):
        await adapter._cmd_models(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "qwen3.5:8b" in reply
    assert "✅" in reply


@pytest.mark.asyncio
async def test_cmd_models_handles_empty_list():
    adapter = _make_adapter()
    update = _make_update()
    context = MagicMock()

    with patch("pillywiggins.adapters.telegram_adapter.list_models", new_callable=AsyncMock, return_value=[]):
        await adapter._cmd_models(update, context)

    update.message.reply_text.assert_called_once_with("Could not fetch model list.")


@pytest.mark.asyncio
async def test_cmd_model_without_args_shows_current():
    adapter = _make_adapter()
    update = _make_update()
    context = MagicMock()
    context.args = []

    await adapter._cmd_model(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "qwen3.5:8b" in reply


@pytest.mark.asyncio
async def test_cmd_model_with_args_switches_model():
    adapter = _make_adapter()
    update = _make_update()
    context = MagicMock()
    context.args = ["qwen3.5:27b"]

    await adapter._cmd_model(update, context)

    adapter.agent.switch_model.assert_called_once_with("qwen3.5:27b")
    reply = update.message.reply_text.call_args[0][0]
    assert "qwen3.5:27b" in reply


@pytest.mark.asyncio
async def test_cmd_reset_clears_history():
    adapter = _make_adapter()
    update = _make_update()
    context = MagicMock()

    await adapter._cmd_reset(update, context)

    adapter.agent.clear_history.assert_called_once()
    update.message.reply_text.assert_called_once_with("Conversation history cleared.")


@pytest.mark.asyncio
async def test_on_message_handles_text():
    adapter = _make_adapter()
    adapter.agent.handle_message = AsyncMock(return_value="Puck says hi")
    update = _make_update(text="hey")
    context = MagicMock()

    await adapter._on_message(update, context)

    adapter.agent.handle_message.assert_called_once()
    adapter._app.bot.send_message.assert_called_once_with(chat_id=99, text="Puck says hi")


@pytest.mark.asyncio
async def test_on_message_ignores_non_text():
    adapter = _make_adapter()
    update = MagicMock()
    update.message = None
    context = MagicMock()

    await adapter._on_message(update, context)

    adapter.agent.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_ignores_empty_text():
    adapter = _make_adapter()
    update = _make_update(text=None)
    update.message.text = None
    context = MagicMock()

    await adapter._on_message(update, context)

    adapter.agent.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_handles_error():
    adapter = _make_adapter()
    adapter.agent.handle_message = AsyncMock(side_effect=Exception("LLM down"))
    update = _make_update(text="hello")
    context = MagicMock()

    await adapter._on_message(update, context)

    adapter._app.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_keep_typing_sends_action():
    adapter = _make_adapter()
    done = asyncio.Event()

    async def send_once_then_set():
        await asyncio.sleep(0.05)
        done.set()

    asyncio.create_task(send_once_then_set())
    await adapter._keep_typing("123", done)

    adapter._app.bot.send_chat_action.assert_called_with(chat_id="123", action="typing")
    assert adapter._app.bot.send_chat_action.call_count >= 1


@pytest.mark.asyncio
async def test_keep_typing_retries_on_timeout():
    adapter = _make_adapter()
    done = asyncio.Event()
    call_count = 0

    async def counting_send(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            done.set()

    adapter._app.bot.send_chat_action = AsyncMock(side_effect=counting_send)

    with patch("pillywiggins.adapters.telegram_adapter.asyncio.wait_for", side_effect=TimeoutError):
        await adapter._keep_typing("123", done)

    assert call_count >= 2


@pytest.mark.asyncio
async def test_shutdown_stops_app():
    adapter = _make_adapter()

    await adapter.shutdown()

    adapter._app.updater.stop.assert_called_once()
    adapter._app.stop.assert_called_once()
    adapter._app.shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_does_nothing_if_no_app():
    adapter = _make_adapter()
    adapter._app = None

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_connect_builds_app():
    adapter = _make_adapter()
    adapter._app = None

    with patch("pillywiggins.adapters.telegram_adapter.Application") as mock_app_cls:
        mock_builder = MagicMock()
        mock_app_instance = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app_instance
        mock_app_cls.builder.return_value = mock_builder

        await adapter.connect()

    assert adapter._app is not None