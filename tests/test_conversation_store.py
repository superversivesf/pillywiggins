from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.memory.store import ConversationStore


@pytest.fixture
def store():
    return ConversationStore(
        database_url="postgresql://test:test@localhost:5432/testdb",
        agent_id="puck",
        channel="telegram",
    )


def _make_pool_mock(acquire_return=None):
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    if acquire_return is not None:
        @asynccontextmanager
        async def _acquire():
            yield acquire_return

        mock_pool.acquire = _acquire

    return mock_pool


@pytest.mark.asyncio
async def test_connect_creates_pool(store):
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    with patch("pillywiggins.memory.store.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await store.connect()

    assert store._pool is mock_pool
    await store.close()


@pytest.mark.asyncio
async def test_save_upserts_conversation(store):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.store.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await store.connect()
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        messages = [ModelRequest(parts=[UserPromptPart(content="hello")])]
        await store.save("chat123", messages)

    mock_conn.execute.assert_called_once()
    call_args = mock_conn.execute.call_args
    assert "INSERT INTO conversation_cache" in call_args[0][0]
    assert call_args[0][1] == "puck"
    assert call_args[0][2] == "telegram"
    assert call_args[0][3] == "chat123"
    await store.close()


@pytest.mark.asyncio
async def test_load_returns_messages(store):
    from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, UserPromptPart

    messages = [ModelRequest(parts=[UserPromptPart(content="hello")])]
    serialized = ModelMessagesTypeAdapter.dump_json(messages).decode()

    mock_row = {"messages": serialized}
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=mock_row)

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.store.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await store.connect()
        result = await store.load("chat123")

    assert result is not None
    assert len(result) == 1
    await store.close()


@pytest.mark.asyncio
async def test_load_returns_none_when_missing(store):
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.store.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await store.connect()
        result = await store.load("nonexistent")

    assert result is None
    await store.close()


@pytest.mark.asyncio
async def test_save_without_pool_does_nothing(store):
    store._pool = None
    await store.save("chat123", [])


@pytest.mark.asyncio
async def test_load_without_pool_returns_none(store):
    store._pool = None
    result = await store.load("chat123")
    assert result is None


@pytest.mark.asyncio
async def test_save_handles_error_gracefully(store):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=Exception("db error"))

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.store.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await store.connect()
        await store.save("chat123", [])

    await store.close()


@pytest.mark.asyncio
async def test_load_handles_error_gracefully(store):
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(side_effect=Exception("db error"))

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.store.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await store.connect()
        result = await store.load("chat123")

    assert result is None
    await store.close()


@pytest.mark.asyncio
async def test_close_cleans_up_pool(store):
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()
    store._pool = mock_pool

    await store.close()

    mock_pool.close.assert_called_once()
    assert store._pool is None


@pytest.mark.asyncio
async def test_close_does_nothing_if_no_pool(store):
    assert store._pool is None
    await store.close()
    assert store._pool is None


def test_store_init_attributes():
    store = ConversationStore(
        database_url="postgresql://u:p@h:5432/db",
        agent_id="titania",
        channel="discord",
    )
    assert store._database_url == "postgresql://u:p@h:5432/db"
    assert store._agent_id == "titania"
    assert store._channel == "discord"
    assert store._pool is None


@pytest.mark.asyncio
async def test_double_close_is_safe(store):
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()
    store._pool = mock_pool

    await store.close()
    await store.close()

    mock_pool.close.assert_called_once()


@pytest.mark.asyncio
async def test_save_serializes_messages_correctly(store):
    from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.store.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await store.connect()
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[TextPart(content="hi")]),
        ]
        await store.save("chat456", messages)

    call_args = mock_conn.execute.call_args
    assert call_args[0][1] == "puck"
    assert call_args[0][2] == "telegram"
    assert call_args[0][3] == "chat456"
    await store.close()


@pytest.mark.asyncio
async def test_load_deserialization_error_returns_none(store):
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={"messages": "not valid json"})

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.store.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await store.connect()
        result = await store.load("chat123")

    assert result is None
    await store.close()


@pytest.mark.asyncio
async def test_connect_sets_pool(store):
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    with patch("pillywiggins.memory.store.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await store.connect()

    assert store._pool is mock_pool
    await store.close()


@pytest.mark.asyncio
async def test_save_empty_messages_list(store):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.store.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await store.connect()
        await store.save("chat_empty", [])

    mock_conn.execute.assert_called_once()
    await store.close()


@pytest.mark.asyncio
async def test_load_null_messages_column_returns_none(store):
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={"messages": None})

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.store.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await store.connect()
        result = await store.load("chat_null")

    assert result is None
    await store.close()


@pytest.mark.asyncio
async def test_connect_passes_init_callback_to_set_agent_id(store):
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()
    captured_init = None

    async def fake_create_pool(*args, init=None, **kwargs):
        nonlocal captured_init
        captured_init = init
        return mock_pool

    with patch("pillywiggins.memory.store.asyncpg.create_pool", side_effect=fake_create_pool):
        await store.connect()

    assert captured_init is not None, "create_pool should receive an init callback"

    mock_conn = AsyncMock()
    await captured_init(mock_conn)

    mock_conn.execute.assert_called_once()
    call_args = mock_conn.execute.call_args
    assert "SET app.agent_id" in call_args[0][0]
    assert call_args[0][1] == "puck"

    await store.close()