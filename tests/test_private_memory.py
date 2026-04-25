from datetime import datetime, timezone
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.memory.private import PrivateMemory


@pytest.fixture
def memory():
    return PrivateMemory(
        database_url="postgresql://test:test@localhost:5432/testdb", agent_id="puck"
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
async def test_connect_creates_pool(memory):
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    with patch(
        "pillywiggins.memory.private.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await memory.connect()

    assert memory._pool is mock_pool
    await memory.close()


@pytest.mark.asyncio
async def test_connect_sets_agent_id(memory):
    init_callback = None
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    async def capture_init(dsn, **kwargs):
        nonlocal init_callback
        init_callback = kwargs.get("init")
        return mock_pool

    with patch("pillywiggins.memory.private.asyncpg.create_pool", side_effect=capture_init):
        await memory.connect()

    assert init_callback is not None
    mock_conn = AsyncMock()
    await init_callback(mock_conn)
    mock_conn.execute.assert_called_once_with(
        "SELECT set_config('app.agent_id', $1, false)", "puck"
    )
    await memory.close()


@pytest.mark.asyncio
async def test_save_inserts_memory(memory):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.private.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await memory.connect()
        await memory.save("test memory", [0.1, 0.2, 0.3], {"source": "test"})

    mock_conn.execute.assert_called_once()
    call_args = mock_conn.execute.call_args
    assert "INSERT INTO private_memory" in call_args[0][0]
    assert "embedding, metadata)" in call_args[0][0]
    assert call_args[0][1] == "puck"
    assert call_args[0][2] == "test memory"
    assert call_args[0][3] == [0.1, 0.2, 0.3]
    await memory.close()


@pytest.mark.asyncio
async def test_save_without_metadata(memory):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.private.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await memory.connect()
        await memory.save("test memory", [0.1, 0.2, 0.3])

    call_args = mock_conn.execute.call_args
    assert call_args[0][4] == {}
    await memory.close()


@pytest.mark.asyncio
async def test_search_returns_results(memory):
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, key: {
        "id": "abc-123",
        "content": "remembered thing",
        "metadata": {"key": "value"},
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "similarity": 0.95,
    }[key]
    mock_row.items = lambda: {
        "id": "abc-123",
        "content": "remembered thing",
        "metadata": {"key": "value"},
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "similarity": 0.95,
    }.items()

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(
        return_value=[
            {
                "id": "abc-123",
                "content": "remembered thing",
                "metadata": {"key": "value"},
                "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "similarity": 0.95,
            }
        ]
    )

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.private.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await memory.connect()
        results = await memory.search([0.1, 0.2, 0.3], limit=5)

    assert len(results) == 1
    assert results[0]["content"] == "remembered thing"
    assert results[0]["similarity"] == 0.95
    await memory.close()


@pytest.mark.asyncio
async def test_search_empty_results(memory):
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.private.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await memory.connect()
        results = await memory.search([0.1, 0.2, 0.3])

    assert results == []
    await memory.close()


@pytest.mark.asyncio
async def test_delete_removes_memory(memory):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value="DELETE 1")

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.private.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await memory.connect()
        result = await memory.delete("abc-123")

    assert result is True
    await memory.close()


@pytest.mark.asyncio
async def test_delete_not_found(memory):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value="DELETE 0")

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.private.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await memory.connect()
        result = await memory.delete("nonexistent")

    assert result is False
    await memory.close()


@pytest.mark.asyncio
async def test_save_passes_embedding_as_vector_cast(memory):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.private.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await memory.connect()
        await memory.save("test memory", [0.1, 0.2, 0.3])

    call_args = mock_conn.execute.call_args
    assert "$3::vector" in call_args[0][0]
    assert call_args[0][3] == [0.1, 0.2, 0.3]
    await memory.close()


@pytest.mark.asyncio
async def test_search_passes_embedding_as_vector_cast(memory):
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.private.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await memory.connect()
        results = await memory.search([0.1, 0.2, 0.3])

    call_args = mock_conn.fetch.call_args
    assert "$1::vector" in call_args[0][0]
    assert call_args[0][1] == [0.1, 0.2, 0.3]
    assert results == []
    await memory.close()


@pytest.mark.asyncio
async def test_save_without_pool_logs_error(memory):
    memory._pool = None
    await memory.save("test", [0.1])


@pytest.mark.asyncio
async def test_search_without_pool_returns_empty(memory):
    memory._pool = None
    results = await memory.search([0.1])
    assert results == []


@pytest.mark.asyncio
async def test_delete_without_pool_returns_false(memory):
    memory._pool = None
    result = await memory.delete("abc")
    assert result is False


@pytest.mark.asyncio
async def test_close_cleans_up_pool(memory):
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()
    memory._pool = mock_pool

    await memory.close()

    mock_pool.close.assert_called_once()
    assert memory._pool is None


@pytest.mark.asyncio
async def test_close_does_nothing_if_no_pool(memory):
    assert memory._pool is None
    await memory.close()
    assert memory._pool is None


# ---------------------------------------------------------------------------
# Real PostgreSQL integration tests (pytest-postgresql)
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS private_memory (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(768),
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore::ResourceWarning")
async def test_private_memory_real_postgres(postgresql_proc):
    host = postgresql_proc.host
    port = postgresql_proc.port
    user = postgresql_proc.user
    dsn = f"postgresql://{user}@{host}:{port}/postgres"

    import asyncpg

    temp_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    async with temp_pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    await temp_pool.close()

    mem = PrivateMemory(database_url=dsn, agent_id="puck")
    await mem.connect()

    await mem.save("integration memory", [0.1, 0.2, 0.3], {"source": "test"})
    results = await mem.search([0.1, 0.2, 0.3], limit=5)
    assert len(results) == 1
    assert results[0]["content"] == "integration memory"
    assert results[0]["metadata"] == {"source": "test"}

    memory_id = results[0]["id"]
    assert await mem.delete(memory_id) is True
    assert len(await mem.search([0.1, 0.2, 0.3], limit=5)) == 0

    await mem.close()
