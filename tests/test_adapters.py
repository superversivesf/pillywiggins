import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.adapters.telegram_adapter import HELP_TEXT, TelegramAdapter
from pillywiggins.messaging.unified import ChannelType


def _make_update(user_id=42, username="testuser", first_name="Test", text="hello", chat_id=99):
    update = MagicMock()
    update.message = MagicMock()
    update.message.from_user = MagicMock()
    update.message.from_user.id = user_id
    update.message.from_user.username = username
    update.message.from_user.first_name = first_name
    update.message.from_user.is_bot = False
    update.message.text = text
    update.message.chat_id = chat_id
    update.message.chat = MagicMock()
    update.message.chat.type = "private"
    update.message.reply_text = AsyncMock()
    return update


def _make_adapter():
    agent = MagicMock()
    agent.model_name = "qwen3.5:8b"
    agent.handle_message = AsyncMock(return_value="response")
    agent.switch_model = MagicMock()
    agent.clear_history = MagicMock()
    agent.get_status = MagicMock(
        return_value={
            "agent_id": "puck",
            "channel": "telegram",
            "model_name": "qwen3.5:8b",
            "message_count": 7,
            "estimated_tokens": 1500,
        }
    )
    agent.compact_history = AsyncMock(return_value="Compacted: 7 messages → 1 summary")
    settings = MagicMock()
    settings.llm_base_url = "http://localhost:11434"
    settings.llm_api_key = ""
    settings.llm_provider = "ollama"
    settings.get_allowed_user_ids = MagicMock(return_value=set())
    settings.allowed_user_ids = "all"
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
    assert "/status" in HELP_TEXT
    assert "/models" in HELP_TEXT
    assert "/model" in HELP_TEXT
    assert "/skills" in HELP_TEXT
    assert "/compact" in HELP_TEXT
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
    assert result.metadata["username"] == "alice"


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
    with patch(
        "pillywiggins.adapters.telegram_adapter.list_models",
        new_callable=AsyncMock,
        return_value=[mock_model],
    ):
        await adapter._cmd_models(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "qwen3.5:8b" in reply
    assert "✅" in reply


@pytest.mark.asyncio
async def test_cmd_models_handles_empty_list():
    adapter = _make_adapter()
    update = _make_update()
    context = MagicMock()

    with patch(
        "pillywiggins.adapters.telegram_adapter.list_models",
        new_callable=AsyncMock,
        return_value=[],
    ):
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


@pytest.mark.asyncio
async def test_cmd_status_shows_fields():
    adapter = _make_adapter()
    update = _make_update()
    context = MagicMock()

    await adapter._cmd_status(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "`puck`" in reply
    assert "`telegram`" in reply
    assert "`qwen3.5:8b`" in reply
    assert "7" in reply
    assert "~1500" in reply


@pytest.mark.asyncio
async def test_cmd_compact_calls_agent():
    adapter = _make_adapter()
    update = _make_update()
    context = MagicMock()

    await adapter._cmd_compact(update, context)

    adapter.agent.compact_history.assert_called_once()
    update.message.reply_text.assert_called_once_with("Compacted: 7 messages → 1 summary")


@pytest.mark.asyncio
async def test_cmd_models_sorted_alphabetically():
    adapter = _make_adapter()
    update = _make_update()
    context = MagicMock()

    model_z = MagicMock()
    model_z.id = "zephyr:7b"
    model_z.owned_by = "ollama"
    model_a = MagicMock()
    model_a.id = "alpha:3b"
    model_a.owned_by = "ollama"
    model_m = MagicMock()
    model_m.id = "mistral:7b"
    model_m.owned_by = "ollama"

    with patch(
        "pillywiggins.adapters.telegram_adapter.list_models",
        new_callable=AsyncMock,
        return_value=[model_z, model_a, model_m],
    ):
        await adapter._cmd_models(update, context)

    reply = update.message.reply_text.call_args[0][0]
    lines = reply.split("\n")
    model_lines = [l for l in lines if l.startswith("•")]
    ids = [l.split("`")[1] for l in model_lines]
    assert ids == ["alpha:3b", "mistral:7b", "zephyr:7b"]


def test_is_authorized_denies_all_by_default():
    agent = MagicMock()
    settings = MagicMock()
    settings.get_allowed_user_ids = MagicMock(return_value=set())
    settings.allowed_user_ids = ""
    adapter = TelegramAdapter(agent, "fake-token", settings)

    assert adapter._is_authorized(42) is False
    assert adapter._is_authorized(1) is False


def test_is_authorized_allows_all_with_all_keyword():
    agent = MagicMock()
    settings = MagicMock()
    settings.get_allowed_user_ids = MagicMock(return_value=set())
    settings.allowed_user_ids = "all"
    adapter = TelegramAdapter(agent, "fake-token", settings)

    assert adapter._is_authorized(999) is True
    assert adapter._is_authorized(1) is True


def test_is_authorized_restricts_to_allowed_ids():
    agent = MagicMock()
    settings = MagicMock()
    settings.get_allowed_user_ids = MagicMock(return_value={42, 100})
    settings.allowed_user_ids = "42,100"
    adapter = TelegramAdapter(agent, "fake-token", settings)

    assert adapter._is_authorized(42) is True
    assert adapter._is_authorized(100) is True
    assert adapter._is_authorized(999) is False


@pytest.mark.asyncio
async def test_on_message_rejects_unauthorized_user():
    adapter = _make_adapter()
    adapter._allowed_user_ids = {42}
    adapter._allow_all = False
    update = _make_update(user_id=999, text="hello")
    context = MagicMock()

    await adapter._on_message(update, context)

    adapter.agent.handle_message.assert_not_called()
    reply = update.message.reply_text.call_args[0][0]
    assert "not authorized" in reply


@pytest.mark.asyncio
async def test_on_message_allows_authorized_user():
    adapter = _make_adapter()
    adapter._allowed_user_ids = {42}
    adapter._allow_all = False
    update = _make_update(user_id=42, text="hello")
    context = MagicMock()

    await adapter._on_message(update, context)

    adapter.agent.handle_message.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_skills_lists_skills():
    adapter = _make_adapter()
    mock_skill = MagicMock()
    mock_skill.name = "roll_dice"
    mock_skill.description = "Roll one or more dice"
    mock_skill.permissions = {"network": False, "subprocess": False, "file_write": False}
    mock_skill.meta = {
        "name": "roll_dice",
        "description": "Roll one or more dice",
        "parameters": {},
        "version": "1.0",
        "permissions": {"network": False, "subprocess": False, "file_write": False},
    }
    adapter.agent._skill_registry = MagicMock()
    adapter.agent._skill_registry.list_skills = MagicMock(return_value=[mock_skill])

    update = _make_update()
    context = MagicMock()

    await adapter._cmd_skills(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "roll_dice" in reply
    assert "Roll one or more dice" in reply


@pytest.mark.asyncio
async def test_cmd_skills_shows_network_permission():
    adapter = _make_adapter()
    mock_skill = MagicMock()
    mock_skill.name = "check_website"
    mock_skill.description = "Check if a URL is reachable"
    mock_skill.permissions = {"network": True, "subprocess": False, "file_write": False}
    mock_skill.meta = {
        "name": "check_website",
        "description": "Check if a URL is reachable",
        "parameters": {},
        "version": "1.0",
    }
    adapter.agent._skill_registry = MagicMock()
    adapter.agent._skill_registry.list_skills = MagicMock(return_value=[mock_skill])

    update = _make_update()
    context = MagicMock()

    await adapter._cmd_skills(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "network" in reply


@pytest.mark.asyncio
async def test_cmd_skills_no_skills():
    adapter = _make_adapter()
    adapter.agent._skill_registry = MagicMock()
    adapter.agent._skill_registry.list_skills = MagicMock(return_value=[])

    update = _make_update()
    context = MagicMock()

    await adapter._cmd_skills(update, context)

    update.message.reply_text.assert_called_once_with("No skills loaded.")


@pytest.mark.asyncio
async def test_listen_connects_if_no_app():
    adapter = _make_adapter()
    adapter._app = None

    with patch("pillywiggins.adapters.telegram_adapter.Application") as mock_app_cls:
        mock_builder = MagicMock()
        mock_app_instance = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app_instance
        mock_app_cls.builder.return_value = mock_builder
        mock_app_instance.initialize = AsyncMock()
        mock_app_instance.start = AsyncMock()
        mock_app_instance.updater = MagicMock()
        mock_app_instance.updater.start_polling = AsyncMock()

        with patch.object(adapter, "_idle", new_callable=AsyncMock):
            await adapter.listen()

    mock_app_instance.initialize.assert_called_once()
    mock_app_instance.start.assert_called_once()
    mock_app_instance.updater.start_polling.assert_called_once()


@pytest.mark.asyncio
async def test_on_message_typing_cancellation_on_success():
    adapter = _make_adapter()
    adapter.agent.handle_message = AsyncMock(return_value="response")
    update = _make_update(text="hello")
    context = MagicMock()

    await adapter._on_message(update, context)

    adapter._app.bot.send_message.assert_called_once_with(chat_id=99, text="response")


@pytest.mark.asyncio
async def test_cmd_skills_description_truncation():
    adapter = _make_adapter()
    mock_skill = MagicMock()
    mock_skill.name = "long_desc_skill"
    mock_skill.description = "A" * 100
    mock_skill.permissions = {"network": False, "subprocess": False, "file_write": False}
    mock_skill.meta = {
        "name": "long_desc_skill",
        "description": "A" * 100,
        "parameters": {},
        "version": "1.0",
        "permissions": {"network": False, "subprocess": False, "file_write": False},
    }
    adapter.agent._skill_registry = MagicMock()
    adapter.agent._skill_registry.list_skills = MagicMock(return_value=[mock_skill])

    update = _make_update()
    context = MagicMock()

    await adapter._cmd_skills(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "..." in reply


@pytest.mark.asyncio
async def test_cmd_skills_subprocess_permission():
    adapter = _make_adapter()
    mock_skill = MagicMock()
    mock_skill.name = "shell_runner"
    mock_skill.description = "Runs shell commands"
    mock_skill.permissions = {"network": False, "subprocess": True, "file_write": False}
    mock_skill.meta = {
        "name": "shell_runner",
        "description": "Runs shell commands",
        "parameters": {},
        "version": "1.0",
        "permissions": {"network": False, "subprocess": True, "file_write": False},
    }
    adapter.agent._skill_registry = MagicMock()
    adapter.agent._skill_registry.list_skills = MagicMock(return_value=[mock_skill])

    update = _make_update()
    context = MagicMock()

    await adapter._cmd_skills(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "subprocess" in reply


@pytest.mark.asyncio
async def test_cmd_compact_error():
    adapter = _make_adapter()
    adapter.agent.compact_history = AsyncMock(side_effect=Exception("compact failed"))
    update = _make_update()
    context = MagicMock()

    with pytest.raises(Exception, match="compact failed"):
        await adapter._cmd_compact(update, context)


def test_is_authorized_whitespace_all_keyword():
    agent = MagicMock()
    settings = MagicMock()
    settings.get_allowed_user_ids = MagicMock(return_value=set())
    settings.allowed_user_ids = "  ALL  "
    adapter = TelegramAdapter(agent, "fake-token", settings)

    assert adapter._is_authorized(42) is True


def test_normalize_handles_missing_username():
    agent = MagicMock()
    settings = MagicMock()
    adapter = TelegramAdapter(agent, "fake-token", settings)
    update = _make_update(username=None)

    result = adapter.normalize(update)

    assert result.metadata["username"] == "Test"


@pytest.mark.asyncio
async def test_on_message_sends_via_send_method():
    adapter = _make_adapter()
    adapter.agent.handle_message = AsyncMock(return_value="bot reply")
    update = _make_update(text="hi", chat_id=42)
    context = MagicMock()

    await adapter._on_message(update, context)

    adapter._app.bot.send_message.assert_called_once_with(chat_id=42, text="bot reply")


@pytest.mark.asyncio
async def test_cmd_model_with_multiword_args():
    adapter = _make_adapter()
    update = _make_update()
    context = MagicMock()
    context.args = ["qwen3.5", "8b"]

    await adapter._cmd_model(update, context)

    adapter.agent.switch_model.assert_called_once_with("qwen3.5 8b")
    reply = update.message.reply_text.call_args[0][0]
    assert "qwen3.5 8b" in reply
