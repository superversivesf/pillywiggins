from abc import ABC
from unittest.mock import MagicMock

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
