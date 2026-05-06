from abc import ABC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.adapters.base import BaseAdapter
from pillywiggins.messaging.unified import ChannelType, UnifiedMessage


def test_base_adapter_is_abc():
    assert issubclass(BaseAdapter, ABC)


def test_cannot_instantiate_base_adapter_directly():
    mock_agent = MagicMock()
    with pytest.raises(TypeError):
        BaseAdapter(mock_agent)


def test_incomplete_subclass_missing_all_methods():
    class IncompleteAdapter(BaseAdapter):
        pass

    mock_agent = MagicMock()
    with pytest.raises(TypeError):
        IncompleteAdapter(mock_agent)


def test_incomplete_subclass_missing_connect():
    class PartialAdapter(BaseAdapter):
        async def listen(self) -> None:
            pass

        async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
            pass

        def normalize(self, raw_message: dict) -> UnifiedMessage:
            pass

    mock_agent = MagicMock()
    with pytest.raises(TypeError):
        PartialAdapter(mock_agent)


def test_incomplete_subclass_missing_listen():
    class PartialAdapter(BaseAdapter):
        async def connect(self) -> None:
            pass

        async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
            pass

        def normalize(self, raw_message: dict) -> UnifiedMessage:
            pass

    mock_agent = MagicMock()
    with pytest.raises(TypeError):
        PartialAdapter(mock_agent)


def test_incomplete_subclass_missing_send():
    class PartialAdapter(BaseAdapter):
        async def connect(self) -> None:
            pass

        async def listen(self) -> None:
            pass

        def normalize(self, raw_message: dict) -> UnifiedMessage:
            pass

    mock_agent = MagicMock()
    with pytest.raises(TypeError):
        PartialAdapter(mock_agent)


def test_incomplete_subclass_missing_normalize():
    class PartialAdapter(BaseAdapter):
        async def connect(self) -> None:
            pass

        async def listen(self) -> None:
            pass

        async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
            pass

    mock_agent = MagicMock()
    with pytest.raises(TypeError):
        PartialAdapter(mock_agent)


def test_complete_subclass_can_instantiate():
    class ConcreteAdapter(BaseAdapter):
        async def connect(self) -> None:
            pass

        async def listen(self) -> None:
            pass

        async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
            pass

        def normalize(self, raw_message: dict) -> UnifiedMessage:
            return UnifiedMessage(
                channel=ChannelType.TELEGRAM,
                channel_user_id="1",
                content="",
                conversation_key="1",
            )

    mock_agent = MagicMock()
    adapter = ConcreteAdapter(mock_agent)
    assert adapter.agent is mock_agent


def test_init_stores_agent_reference():
    class ConcreteAdapter(BaseAdapter):
        async def connect(self) -> None:
            pass

        async def listen(self) -> None:
            pass

        async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
            pass

        def normalize(self, raw_message: dict) -> UnifiedMessage:
            return UnifiedMessage(
                channel=ChannelType.TELEGRAM,
                channel_user_id="1",
                content="",
                conversation_key="1",
            )

    mock_agent = MagicMock()
    mock_agent.agent_id = "puck"
    adapter = ConcreteAdapter(mock_agent)

    assert adapter.agent is mock_agent
    assert adapter.agent.agent_id == "puck"


@pytest.mark.asyncio
async def test_connect_is_async():
    class ConcreteAdapter(BaseAdapter):
        connected = False

        async def connect(self) -> None:
            self.connected = True

        async def listen(self) -> None:
            pass

        async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
            pass

        def normalize(self, raw_message: dict) -> UnifiedMessage:
            return UnifiedMessage(
                channel=ChannelType.TELEGRAM,
                channel_user_id="1",
                content="",
                conversation_key="1",
            )

    adapter = ConcreteAdapter(MagicMock())
    await adapter.connect()
    assert adapter.connected is True


@pytest.mark.asyncio
async def test_listen_is_async():
    class ConcreteAdapter(BaseAdapter):
        listening = False

        async def connect(self) -> None:
            pass

        async def listen(self) -> None:
            self.listening = True

        async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
            pass

        def normalize(self, raw_message: dict) -> UnifiedMessage:
            return UnifiedMessage(
                channel=ChannelType.TELEGRAM,
                channel_user_id="1",
                content="",
                conversation_key="1",
            )

    adapter = ConcreteAdapter(MagicMock())
    await adapter.listen()
    assert adapter.listening is True


@pytest.mark.asyncio
async def test_send_is_async():
    class ConcreteAdapter(BaseAdapter):
        sent_messages = []

        async def connect(self) -> None:
            pass

        async def listen(self) -> None:
            pass

        async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
            self.sent_messages.append((channel_id, content, metadata))

        def normalize(self, raw_message: dict) -> UnifiedMessage:
            return UnifiedMessage(
                channel=ChannelType.TELEGRAM,
                channel_user_id="1",
                content="",
                conversation_key="1",
            )

    adapter = ConcreteAdapter(MagicMock())
    await adapter.send("ch1", "hello", {"foo": "bar"})
    assert adapter.sent_messages == [("ch1", "hello", {"foo": "bar"})]


@pytest.mark.asyncio
async def test_send_without_metadata():
    class ConcreteAdapter(BaseAdapter):
        sent_messages = []

        async def connect(self) -> None:
            pass

        async def listen(self) -> None:
            pass

        async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
            self.sent_messages.append((channel_id, content, metadata))

        def normalize(self, raw_message: dict) -> UnifiedMessage:
            return UnifiedMessage(
                channel=ChannelType.TELEGRAM,
                channel_user_id="1",
                content="",
                conversation_key="1",
            )

    adapter = ConcreteAdapter(MagicMock())
    await adapter.send("ch1", "hello")
    assert adapter.sent_messages == [("ch1", "hello", None)]


def test_normalize_returns_unified_message():
    class ConcreteAdapter(BaseAdapter):
        async def connect(self) -> None:
            pass

        async def listen(self) -> None:
            pass

        async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
            pass

        def normalize(self, raw_message: dict) -> UnifiedMessage:
            return UnifiedMessage(
                channel=ChannelType.DISCORD,
                channel_user_id=raw_message["user_id"],
                content=raw_message["text"],
                conversation_key=raw_message["channel_id"],
                metadata={"username": raw_message.get("username", "")},
            )

    adapter = ConcreteAdapter(MagicMock())
    raw = {"user_id": "42", "text": "hello", "channel_id": "99", "username": "alice"}
    result = adapter.normalize(raw)

    assert isinstance(result, UnifiedMessage)
    assert result.channel == ChannelType.DISCORD
    assert result.channel_user_id == "42"
    assert result.content == "hello"
    assert result.conversation_key == "99"
    assert result.metadata == {"username": "alice"}


def test_normalize_with_empty_raw_message():
    class ConcreteAdapter(BaseAdapter):
        async def connect(self) -> None:
            pass

        async def listen(self) -> None:
            pass

        async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
            pass

        def normalize(self, raw_message: dict) -> UnifiedMessage:
            return UnifiedMessage(
                channel=ChannelType.TELEGRAM,
                channel_user_id=raw_message.get("user_id", "unknown"),
                content=raw_message.get("text", ""),
                conversation_key=raw_message.get("channel_id", "0"),
            )

    adapter = ConcreteAdapter(MagicMock())
    result = adapter.normalize({})

    assert result.channel_user_id == "unknown"
    assert result.content == ""
    assert result.conversation_key == "0"


def test_abstract_methods_are_four():
    abstract_methods = getattr(BaseAdapter, "__abstractmethods__", set())
    assert abstract_methods == {"connect", "listen", "normalize", "send"}


# ---------------------------------------------------------------------------
# _is_authorized
# ---------------------------------------------------------------------------


def _make_concrete_adapter(agent=None, settings=None):
    if agent is None:
        agent = MagicMock()
        agent.agent_id = "test"
    if settings is None:
        settings = MagicMock()
        settings.get_allowed_user_ids = MagicMock(return_value=set())
        settings.allowed_user_ids = ""
        settings.llm_base_url = "http://localhost:11434/v1"
        settings.llm_api_key = ""
        settings.llm_provider = "ollama"

    class ConcreteAdapter(BaseAdapter):
        command_prefix = "!"

        async def connect(self) -> None:
            pass

        async def listen(self) -> None:
            pass

        async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
            pass

        def normalize(self, raw_message: dict) -> UnifiedMessage:
            return UnifiedMessage(
                channel=ChannelType.TELEGRAM,
                channel_user_id="1",
                content="",
                conversation_key="1",
            )

    return ConcreteAdapter(agent, settings)


def test_is_authorized_allows_all_when_configured():
    adapter = _make_concrete_adapter(settings=MagicMock(
        get_allowed_user_ids=MagicMock(return_value=set()),
        allowed_user_ids="all",
    ))
    assert adapter._is_authorized("anyone") is True
    assert adapter._is_authorized(42) is True


def test_is_authorized_denies_when_not_in_allowed_list():
    adapter = _make_concrete_adapter(settings=MagicMock(
        get_allowed_user_ids=MagicMock(return_value={42, 100}),
        allowed_user_ids="42,100",
    ))
    assert adapter._is_authorized(42) is True
    assert adapter._is_authorized("42") is True
    assert adapter._is_authorized(100) is True
    assert adapter._is_authorized(999) is False


def test_is_authorized_denies_all_when_empty():
    adapter = _make_concrete_adapter(settings=MagicMock(
        get_allowed_user_ids=MagicMock(return_value=set()),
        allowed_user_ids="",
    ))
    assert adapter._is_authorized(42) is False
    assert adapter._is_authorized("anyone") is False


# ---------------------------------------------------------------------------
# _should_respond_to_bot
# ---------------------------------------------------------------------------


def test_should_respond_to_bot_allows_non_bot():
    adapter = _make_concrete_adapter()
    assert adapter._should_respond_to_bot("ch1", False) is True


def test_should_respond_to_bot_zero_limit():
    adapter = _make_concrete_adapter()
    adapter.agent.personality.bot_chat_limit = 0
    assert adapter._should_respond_to_bot("ch1", True) is False


def test_should_respond_to_bot_negative_limit():
    adapter = _make_concrete_adapter()
    adapter.agent.personality.bot_chat_limit = -1
    assert adapter._should_respond_to_bot("ch1", True) is True


def test_should_respond_to_bot_respects_limit():
    adapter = _make_concrete_adapter()
    adapter.agent.personality.bot_chat_limit = 2
    assert adapter._should_respond_to_bot("ch1", True) is True
    adapter._bot_chat_counts["ch1"] = 1
    assert adapter._should_respond_to_bot("ch1", True) is True
    adapter._bot_chat_counts["ch1"] = 2
    assert adapter._should_respond_to_bot("ch1", True) is False


def test_should_respond_to_bot_resets_on_human():
    adapter = _make_concrete_adapter()
    adapter.agent.personality.bot_chat_limit = 1
    adapter._bot_chat_counts["ch1"] = 1
    assert adapter._should_respond_to_bot("ch1", True) is False
    assert adapter._should_respond_to_bot("ch1", False) is True
    assert adapter._bot_chat_counts["ch1"] == 0


# ---------------------------------------------------------------------------
# command_prefix and HELP_TEXT
# ---------------------------------------------------------------------------


def test_default_command_prefix_is_exclamation():
    assert BaseAdapter.command_prefix == "!"


def test_help_text_uses_command_prefix():
    adapter = _make_concrete_adapter()
    text = adapter.HELP_TEXT
    assert "!help" in text
    assert "!status" in text
    assert "!models" in text


def test_help_text_with_slash_prefix():
    class SlashAdapter(BaseAdapter):
        command_prefix = "/"

        async def connect(self) -> None:
            pass

        async def listen(self) -> None:
            pass

        async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
            pass

        def normalize(self, raw_message: dict) -> UnifiedMessage:
            return UnifiedMessage(channel=ChannelType.TELEGRAM, channel_user_id="1", content="", conversation_key="1")

    settings = MagicMock()
    settings.get_allowed_user_ids = MagicMock(return_value=set())
    settings.allowed_user_ids = ""
    adapter = SlashAdapter(MagicMock(), settings)
    text = adapter.HELP_TEXT
    assert "/help" in text
    assert "/status" in text


# ---------------------------------------------------------------------------
# dispatch_command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_command_help():
    adapter = _make_concrete_adapter()
    result = await adapter.dispatch_command("!help", "ch1")
    assert result is not None
    assert "!help" in result


@pytest.mark.asyncio
async def test_dispatch_command_status():
    adapter = _make_concrete_adapter()
    adapter.agent.get_status = MagicMock(return_value={
        "model_name": "test-model",
        "message_count": 5,
        "estimated_tokens": 100,
        "agent_id": "test-agent",
        "channel": "test-channel",
    })
    result = await adapter.dispatch_command("!status", "ch1")
    assert "test-model" in result
    assert "5" in result
    assert "100" in result


@pytest.mark.asyncio
async def test_dispatch_command_models():
    adapter = _make_concrete_adapter()
    mock_model = MagicMock()
    mock_model.id = "test-model"
    mock_model.owned_by = "test"
    with patch("pillywiggins.adapters.base.list_models", new_callable=AsyncMock, return_value=[mock_model]):
        result = await adapter.dispatch_command("!models", "ch1")
    assert "test-model" in result


@pytest.mark.asyncio
async def test_dispatch_command_model_switch():
    adapter = _make_concrete_adapter()
    def switch_model(name):
        adapter.agent.model_name = name
    adapter.agent.switch_model = MagicMock(side_effect=switch_model)
    result = await adapter.dispatch_command("!model new-model", "ch1")
    adapter.agent.switch_model.assert_called_once_with("new-model")
    assert "new-model" in result


@pytest.mark.asyncio
async def test_dispatch_command_model_no_arg():
    adapter = _make_concrete_adapter()
    result = await adapter.dispatch_command("!model", "ch1")
    assert "test" in result or "model" in result.lower()


@pytest.mark.asyncio
async def test_dispatch_command_skills():
    adapter = _make_concrete_adapter()
    mock_skill = MagicMock()
    mock_skill.name = "test_skill"
    mock_skill.description = "A test skill"
    adapter.agent._skill_registry = MagicMock()
    adapter.agent._skill_registry.list_skills = MagicMock(return_value=[mock_skill])
    result = await adapter.dispatch_command("!skills", "ch1")
    assert "test_skill" in result
    assert "A test skill" in result


@pytest.mark.asyncio
async def test_dispatch_command_skills_no_registry():
    adapter = _make_concrete_adapter()
    adapter.agent._skill_registry = None
    result = await adapter.dispatch_command("!skills", "ch1")
    assert result == "No skill registry loaded."


@pytest.mark.asyncio
async def test_dispatch_command_compact():
    adapter = _make_concrete_adapter()
    adapter.agent.compact_history = AsyncMock(return_value="5 messages compacted")
    result = await adapter.dispatch_command("!compact", "ch1")
    assert "5 messages compacted" in result


@pytest.mark.asyncio
async def test_dispatch_command_reset():
    adapter = _make_concrete_adapter()
    adapter.agent.clear_history = AsyncMock()
    result = await adapter.dispatch_command("!reset", "ch1")
    assert "cleared" in result.lower()


@pytest.mark.asyncio
async def test_dispatch_command_unknown_returns_none():
    adapter = _make_concrete_adapter()
    result = await adapter.dispatch_command("!unknown", "ch1")
    assert result is None


@pytest.mark.asyncio
async def test_dispatch_command_no_prefix_returns_none():
    adapter = _make_concrete_adapter()
    result = await adapter.dispatch_command("hello", "ch1")
    assert result is None
