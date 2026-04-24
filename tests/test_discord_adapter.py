import asyncio
import signal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.adapters.discord_adapter import DiscordAdapter, HELP_TEXT
from pillywiggins.messaging.unified import ChannelType


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
    agent = MagicMock()
    agent.agent_id = "puck"
    agent.personality = MagicMock()
    agent.personality.channel = "discord"
    agent.model_name = "qwen3.5:8b"
    agent.handle_message = AsyncMock(return_value="response")
    agent.switch_model = MagicMock()
    agent.clear_history = AsyncMock()
    agent.get_status = MagicMock(
        return_value={
            "agent_id": "puck",
            "channel": "discord",
            "model_name": "qwen3.5:8b",
            "message_count": 7,
            "estimated_tokens": 1500,
        }
    )
    mock_msg = MagicMock()
    mock_msg.parts = [MagicMock(content="x" * 857)]
    agent._get_history = MagicMock(return_value=[mock_msg] * 7)
    agent.compact_history = AsyncMock(return_value="Compacted: 7 messages → 1 summary")
    settings = MagicMock()
    settings.llm_base_url = "http://localhost:11434"
    settings.llm_api_key = ""
    settings.llm_provider = "ollama"
    settings.get_allowed_user_ids = MagicMock(return_value=set())
    settings.allowed_user_ids = "all"
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
    settings = MagicMock()
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
    settings = MagicMock()
    adapter = DiscordAdapter(agent, "fake-token", settings)
    message = _make_message(author_id=42, author_name="bob", content="dm text", channel_id=789)

    result = adapter.normalize(message)

    assert result.metadata.get("guild_id") is None


def test_normalize_handles_guild_message():
    agent = MagicMock()
    settings = MagicMock()
    adapter = DiscordAdapter(agent, "fake-token", settings)
    message = _make_message(
        author_id=42, author_name="bob", content="guild text", channel_id=789, guild_id=1001
    )

    result = adapter.normalize(message)

    assert result.metadata["guild_id"] == "1001"


def test_normalize_timestamp_is_aware_utc():
    agent = MagicMock()
    settings = MagicMock()
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
    settings = MagicMock()
    settings.get_allowed_user_ids = MagicMock(return_value=set())
    settings.allowed_user_ids = "all"
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
    settings = MagicMock()
    settings.get_allowed_user_ids = MagicMock(return_value=set())
    settings.allowed_user_ids = "all"
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
    settings = MagicMock()
    adapter = DiscordAdapter(agent, "fake-token", settings)
    adapter._client = None

    await adapter.shutdown()


@pytest.mark.asyncio
async def test_idle_awaits_signal_event():
    adapter = _make_adapter()

    event = asyncio.Event()

    def mock_add_signal_handler(sig, cb):
        # Schedule the callback immediately so the event gets set
        asyncio.get_event_loop().call_later(0.01, cb)

    with patch.object(asyncio.get_event_loop(), "add_signal_handler", mock_add_signal_handler):
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
    asyncio.get_event_loop().call_later(0.05, done.set)

    await asyncio.wait_for(adapter._keep_typing("99", done), timeout=1.0)

    assert mock_channel.typing.call_count >= 1


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_help_replies_with_help_text():
    adapter = _make_adapter()
    message = _make_message(content="!help")

    await adapter._cmd_help(message)

    message.channel.send.assert_called_once_with(HELP_TEXT)


@pytest.mark.asyncio
async def test_cmd_status_shows_fields():
    adapter = _make_adapter()
    message = _make_message(content="!status")

    await adapter._cmd_status(message)

    reply = message.channel.send.call_args[0][0]
    assert "puck" in reply
    assert "discord" in reply
    assert "qwen3.5:8b" in reply
    assert "7" in reply
    assert "1500" in reply


@pytest.mark.asyncio
async def test_cmd_models_replies_with_model_list():
    adapter = _make_adapter()
    message = _make_message(content="!models")

    mock_model = MagicMock()
    mock_model.id = "qwen3.5:8b"
    mock_model.owned_by = "ollama"
    with patch(
        "pillywiggins.adapters.discord_adapter.list_models",
        new_callable=AsyncMock,
        return_value=[mock_model],
    ):
        await adapter._cmd_models(message)

    reply = message.channel.send.call_args[0][0]
    assert "qwen3.5:8b" in reply
    assert "✅" in reply


@pytest.mark.asyncio
async def test_cmd_models_handles_empty_list():
    adapter = _make_adapter()
    message = _make_message(content="!models")

    with patch(
        "pillywiggins.adapters.discord_adapter.list_models",
        new_callable=AsyncMock,
        return_value=[],
    ):
        await adapter._cmd_models(message)

    message.channel.send.assert_called_once_with("Could not fetch model list.")


@pytest.mark.asyncio
async def test_cmd_model_without_args_shows_current():
    adapter = _make_adapter()
    message = _make_message(content="!model")

    await adapter._cmd_model(message)

    reply = message.channel.send.call_args[0][0]
    assert "qwen3.5:8b" in reply


@pytest.mark.asyncio
async def test_cmd_model_with_args_switches_model():
    adapter = _make_adapter()
    message = _make_message(content="!model qwen3.5:27b")

    await adapter._cmd_model(message)

    adapter.agent.switch_model.assert_called_once_with("qwen3.5:27b")
    reply = message.channel.send.call_args[0][0]
    assert "qwen3.5:27b" in reply


@pytest.mark.asyncio
async def test_cmd_reset_clears_history():
    adapter = _make_adapter()
    message = _make_message(content="!reset", channel_id=99)

    await adapter._cmd_reset(message)

    adapter.agent.clear_history.assert_called_once()
    message.channel.send.assert_called_once_with("Conversation history cleared.")


@pytest.mark.asyncio
async def test_cmd_compact_calls_agent():
    adapter = _make_adapter()
    message = _make_message(content="!compact", channel_id=99)

    await adapter._cmd_compact(message)

    adapter.agent.compact_history.assert_called_once()
    message.channel.send.assert_called_once_with("Compacted: 7 messages → 1 summary")


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

    message = _make_message(content="!skills")

    await adapter._cmd_skills(message)

    reply = message.channel.send.call_args[0][0]
    assert "roll_dice" in reply
    assert "Roll one or more dice" in reply


@pytest.mark.asyncio
async def test_cmd_skills_no_skills():
    adapter = _make_adapter()
    adapter.agent._skill_registry = MagicMock()
    adapter.agent._skill_registry.list_skills = MagicMock(return_value=[])

    message = _make_message(content="!skills")

    await adapter._cmd_skills(message)

    message.channel.send.assert_called_once_with("No skills loaded.")


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

    message = _make_message(content="!skills")

    await adapter._cmd_skills(message)

    reply = message.channel.send.call_args[0][0]
    assert "..." in reply


# ---------------------------------------------------------------------------
# authorization
# ---------------------------------------------------------------------------


def test_is_authorized_denies_all_by_default():
    agent = MagicMock()
    settings = MagicMock()
    settings.get_allowed_user_ids = MagicMock(return_value=set())
    settings.allowed_user_ids = ""
    adapter = DiscordAdapter(agent, "fake-token", settings)

    assert adapter._is_authorized(42) is False
    assert adapter._is_authorized(1) is False


def test_is_authorized_allows_all_with_all_keyword():
    agent = MagicMock()
    settings = MagicMock()
    settings.get_allowed_user_ids = MagicMock(return_value=set())
    settings.allowed_user_ids = "all"
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
# bot_chat_limit
# ---------------------------------------------------------------------------


def test_should_respond_to_bot_allows_non_bot():
    adapter = _make_adapter()
    assert adapter._should_respond_to_bot("ch1", False) is True


def test_should_respond_to_bot_respects_limit():
    adapter = _make_adapter()
    adapter.agent.personality.bot_chat_limit = 2
    assert adapter._should_respond_to_bot("ch1", True) is True
    adapter._bot_chat_counts["ch1"] = 1
    assert adapter._should_respond_to_bot("ch1", True) is True
    adapter._bot_chat_counts["ch1"] = 2
    assert adapter._should_respond_to_bot("ch1", True) is False


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
