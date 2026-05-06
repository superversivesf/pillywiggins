import asyncio
import signal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.adapters.discord_adapter import DiscordAdapter, HELP_TEXT
from pillywiggins.messaging.unified import ChannelType
from tests.helpers import make_mock_agent, make_mock_settings


def _make_message(
    author_id=42,
    author_name="testuser",
    content="hello",
    channel_id=99,
    guild_id=None,
    bot=False,
):
    message = MagicMock()
    message.author = MagicMock()
    message.author.id = author_id
    message.author.name = author_name
    message.author.bot = bot
    message.content = content
    message.channel = MagicMock()
    message.channel.id = channel_id
    message.channel.type = MagicMock()
    message.channel.type.name = "text"
    if guild_id is not None:
        message.guild = MagicMock()
        message.guild.id = guild_id
    else:
        message.guild = None
    message.created_at = datetime.now(timezone.utc)
    message.mentions = []
    message.channel.send = AsyncMock()
    return message


def _make_adapter():
    agent = make_mock_agent(channel="discord")
    settings = make_mock_settings()
    adapter = DiscordAdapter(agent, "fake-token", settings)
    adapter._client = MagicMock()
    adapter._client.get_channel = MagicMock()
    adapter._client.fetch_channel = AsyncMock()
    adapter._client.login = AsyncMock()
    adapter._client.connect = AsyncMock()
    adapter._client.close = AsyncMock()
    adapter._client.user = MagicMock()
    adapter._client.user.id = 1
    adapter._wait_until_ready = AsyncMock()
    return adapter


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


def test_normalize_converts_discord_message_to_unified_message():
    agent = MagicMock()
    settings = make_mock_settings()
    adapter = DiscordAdapter(agent, "fake-token", settings)
    message = _make_message(author_id=123, author_name="alice", content="hi there", channel_id=456)

    result = adapter.normalize(message)

    assert result.channel == ChannelType.DISCORD
    assert result.channel_user_id == "123"
    assert result.content == "hi there"
    assert result.conversation_key == "456"
    assert result.metadata["username"] == "alice"
    assert result.metadata["is_bot"] is False


def test_normalize_handles_dm_with_no_guild():
    agent = MagicMock()
    settings = make_mock_settings()
    adapter = DiscordAdapter(agent, "fake-token", settings)
    message = _make_message(author_id=42, author_name="bob", content="dm text", channel_id=789)

    result = adapter.normalize(message)

    assert result.metadata.get("guild_id") is None


def test_normalize_handles_guild_message():
    agent = MagicMock()
    settings = make_mock_settings()
    adapter = DiscordAdapter(agent, "fake-token", settings)
    message = _make_message(
        author_id=42, author_name="bob", content="guild text", channel_id=789, guild_id=1001
    )

    result = adapter.normalize(message)

    assert result.metadata["guild_id"] == "1001"


def test_normalize_timestamp_is_aware_utc():
    agent = MagicMock()
    settings = make_mock_settings()
    adapter = DiscordAdapter(agent, "fake-token", settings)
    message = _make_message()

    result = adapter.normalize(message)

    assert result.timestamp.tzinfo is not None


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_uses_get_channel_then_fetch():
    adapter = _make_adapter()
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    adapter._client.get_channel = MagicMock(return_value=mock_channel)

    await adapter.send("12345", "hello world")

    adapter._client.get_channel.assert_called_once_with(12345)
    mock_channel.send.assert_called_once_with("hello world")


@pytest.mark.asyncio
async def test_send_falls_back_to_fetch_channel():
    adapter = _make_adapter()
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    adapter._client.get_channel = MagicMock(return_value=None)
    adapter._client.fetch_channel = AsyncMock(return_value=mock_channel)

    await adapter.send("12345", "hello world")

    adapter._client.fetch_channel.assert_called_once_with(12345)
    mock_channel.send.assert_called_once_with("hello world")


# ---------------------------------------------------------------------------
# connect / listen / shutdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_creates_discord_client():
    agent = MagicMock()
    settings = make_mock_settings()
    adapter = DiscordAdapter(agent, "fake-token", settings)

    with patch("pillywiggins.adapters.discord_adapter.discord.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance

        await adapter.connect()

    assert adapter._client is not None
    mock_client_cls.assert_called_once()
    call_kwargs = mock_client_cls.call_args[1]
    assert call_kwargs["intents"].message_content is True


@pytest.mark.asyncio
async def test_listen_logs_in_and_connects():
    adapter = _make_adapter()

    with patch.object(adapter, "_idle", new_callable=AsyncMock):
        await adapter.listen()

    adapter._client.login.assert_called_once_with("fake-token")
    adapter._client.connect.assert_called_once()


@pytest.mark.asyncio
async def test_listen_connects_if_no_client():
    agent = MagicMock()
    settings = make_mock_settings()
    adapter = DiscordAdapter(agent, "fake-token", settings)
    adapter._client = None

    with patch("pillywiggins.adapters.discord_adapter.discord.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_instance.login = AsyncMock()
        mock_instance.connect = AsyncMock()
        mock_client_cls.return_value = mock_instance

        with patch.object(adapter, "_idle", new_callable=AsyncMock):
            await adapter.listen()

    mock_instance.login.assert_called_once()
    mock_instance.connect.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_closes_client():
    adapter = _make_adapter()

    await adapter.shutdown()

    adapter._client.close.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_does_nothing_if_no_client():
    agent = MagicMock()
    settings = make_mock_settings()
    adapter = DiscordAdapter(agent, "fake-token", settings)
    adapter._client = None

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_idle_awaits_signal_event():
    adapter = _make_adapter()

    event = asyncio.Event()

    def mock_add_signal_handler(sig, cb):
        # Schedule the callback immediately so the event gets set
        asyncio.get_running_loop().call_later(0.01, cb)

    with patch.object(asyncio.get_running_loop(), "add_signal_handler", mock_add_signal_handler):
        await adapter._idle()

    assert True  # If we got here, event was triggered


# ---------------------------------------------------------------------------
# on_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_message_ignores_own_messages():
    adapter = _make_adapter()
    adapter._client.user.id = 42
    message = _make_message(author_id=42, content="hello")

    await adapter._on_message(message)

    adapter.agent.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_ignores_empty_content():
    adapter = _make_adapter()
    message = _make_message(content="")

    await adapter._on_message(message)

    adapter.agent.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_ignores_non_text():
    adapter = _make_adapter()
    message = _make_message(content=None)

    await adapter._on_message(message)

    adapter.agent.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_handles_text():
    adapter = _make_adapter()
    adapter.agent.handle_message = AsyncMock(return_value="Puck says hi")
    message = _make_message(content="hey", channel_id=99)
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    adapter._client.get_channel = MagicMock(return_value=mock_channel)

    await adapter._on_message(message)

    adapter.agent.handle_message.assert_called_once()
    mock_channel.send.assert_called_once_with("Puck says hi")


@pytest.mark.asyncio
async def test_on_message_rejects_unauthorized_user():
    adapter = _make_adapter()
    adapter._allowed_user_ids = {42}
    adapter._allow_all = False
    message = _make_message(author_id=999, content="hello", channel_id=99)
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    message.channel = mock_channel

    await adapter._on_message(message)

    adapter.agent.handle_message.assert_not_called()
    mock_channel.send.assert_called_once_with("You are not authorized to use this bot.")


@pytest.mark.asyncio
async def test_on_message_allows_authorized_user():
    adapter = _make_adapter()
    adapter._allowed_user_ids = {42}
    adapter._allow_all = False
    adapter.agent.handle_message = AsyncMock(return_value="hi")
    message = _make_message(author_id=42, content="hello", channel_id=99)
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    adapter._client.get_channel = MagicMock(return_value=mock_channel)

    await adapter._on_message(message)

    adapter.agent.handle_message.assert_called_once()


@pytest.mark.asyncio
async def test_on_message_handles_error():
    adapter = _make_adapter()
    adapter.agent.handle_message = AsyncMock(side_effect=Exception("LLM down"))
    message = _make_message(content="hello", channel_id=99)
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    adapter._client.get_channel = MagicMock(return_value=mock_channel)

    await adapter._on_message(message)

    mock_channel.send.assert_not_called()


@pytest.mark.asyncio
async def test_keep_typing_sends_typing():
    adapter = _make_adapter()

    mock_channel = MagicMock()
    mock_typing = MagicMock()
    mock_typing.__aenter__ = AsyncMock()
    mock_typing.__aexit__ = AsyncMock()
    mock_channel.typing = MagicMock(return_value=mock_typing)
    adapter._client.get_channel = MagicMock(return_value=mock_channel)

    done = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, done.set)

    await asyncio.wait_for(adapter._keep_typing("99", done), timeout=1.0)

    assert mock_channel.typing.call_count >= 1


# ---------------------------------------------------------------------------
# commands via dispatch_command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_help():
    adapter = _make_adapter()
    result = await adapter.dispatch_command("!help", "99")
    assert result is not None
    assert "!help" in result


@pytest.mark.asyncio
async def test_dispatch_status():
    adapter = _make_adapter()
    result = await adapter.dispatch_command("!status", "99")
    assert result is not None
    assert "puck" in result
    assert "discord" in result
    assert "qwen3.5:8b" in result
    assert "7" in result
    assert "1500" in result


@pytest.mark.asyncio
async def test_dispatch_models():
    adapter = _make_adapter()
    mock_model = MagicMock()
    mock_model.id = "qwen3.5:8b"
    mock_model.owned_by = "ollama"
    with patch(
        "pillywiggins.adapters.base.list_models",
        new_callable=AsyncMock,
        return_value=[mock_model],
    ):
        result = await adapter.dispatch_command("!models", "99")
    assert "qwen3.5:8b" in result


@pytest.mark.asyncio
async def test_dispatch_models_empty():
    adapter = _make_adapter()
    with patch(
        "pillywiggins.adapters.base.list_models",
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await adapter.dispatch_command("!models", "99")
    assert result == "No models available."


@pytest.mark.asyncio
async def test_dispatch_model_switch():
    adapter = _make_adapter()
    # Make switch_model actually update model_name
    def switch_model(name):
        adapter.agent.model_name = name
    adapter.agent.switch_model = MagicMock(side_effect=switch_model)

    result = await adapter.dispatch_command("!model qwen3.5:27b", "99")
    adapter.agent.switch_model.assert_called_once_with("qwen3.5:27b")
    assert "qwen3.5:27b" in result


@pytest.mark.asyncio
async def test_dispatch_reset():
    adapter = _make_adapter()
    result = await adapter.dispatch_command("!reset", "99")
    adapter.agent.clear_history.assert_called_once()
    assert "cleared" in result.lower()


@pytest.mark.asyncio
async def test_dispatch_compact():
    adapter = _make_adapter()
    result = await adapter.dispatch_command("!compact", "99")
    adapter.agent.compact_history.assert_called_once()
    assert "Compacted" in result


@pytest.mark.asyncio
async def test_dispatch_skills():
    adapter = _make_adapter()
    mock_skill = MagicMock()
    mock_skill.name = "roll_dice"
    mock_skill.description = "Roll one or more dice"
    mock_skill.permissions = {"network": False, "subprocess": False, "file_write": False}
    adapter.agent._skill_registry = MagicMock()
    adapter.agent._skill_registry.list_skills = MagicMock(return_value=[mock_skill])

    result = await adapter.dispatch_command("!skills", "99")
    assert "roll_dice" in result
    assert "Roll one or more dice" in result


@pytest.mark.asyncio
async def test_dispatch_skills_no_skills():
    adapter = _make_adapter()
    adapter.agent._skill_registry = MagicMock()
    adapter.agent._skill_registry.list_skills = MagicMock(return_value=[])

    result = await adapter.dispatch_command("!skills", "99")
    assert result == "No skills loaded."


@pytest.mark.asyncio
async def test_on_message_dispatches_command():
    adapter = _make_adapter()
    message = _make_message(content="!help")
    # _on_message should dispatch the command and send the response
    await adapter._on_message(message)
    message.channel.send.assert_called_once()
    reply = message.channel.send.call_args[0][0]
    assert "!help" in reply


# ---------------------------------------------------------------------------
# authorization
# ---------------------------------------------------------------------------


def test_is_authorized_denies_all_by_default():
    agent = MagicMock()
    settings = make_mock_settings(allowed_user_ids="")
    adapter = DiscordAdapter(agent, "fake-token", settings)

    assert adapter._is_authorized(42) is False
    assert adapter._is_authorized(1) is False


def test_is_authorized_allows_all_with_all_keyword():
    agent = MagicMock()
    settings = make_mock_settings()
    adapter = DiscordAdapter(agent, "fake-token", settings)

    assert adapter._is_authorized(999) is True
    assert adapter._is_authorized(1) is True


def test_is_authorized_restricts_to_allowed_ids():
    agent = MagicMock()
    settings = MagicMock()
    settings.get_allowed_user_ids = MagicMock(return_value={42, 100})
    settings.allowed_user_ids = "42,100"
    adapter = DiscordAdapter(agent, "fake-token", settings)

    assert adapter._is_authorized(42) is True
    assert adapter._is_authorized(100) is True
    assert adapter._is_authorized(999) is False


# ---------------------------------------------------------------------------
# help text
# ---------------------------------------------------------------------------


def test_help_text_constant_exists():
    assert HELP_TEXT is not None
    assert isinstance(HELP_TEXT, str)
    assert "!help" in HELP_TEXT or "/help" in HELP_TEXT
    assert "!status" in HELP_TEXT or "/status" in HELP_TEXT
    assert "!models" in HELP_TEXT or "/models" in HELP_TEXT
    assert "!model" in HELP_TEXT or "/model" in HELP_TEXT
    assert "!skills" in HELP_TEXT or "/skills" in HELP_TEXT
    assert "!compact" in HELP_TEXT or "/compact" in HELP_TEXT
    assert "!reset" in HELP_TEXT or "/reset" in HELP_TEXT