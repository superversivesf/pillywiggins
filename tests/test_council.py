from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from pillywiggins.memory.council import (
    CouncilMemory,
    DEDUP_SIMILARITY_THRESHOLD,
    MAX_CONTENT_LENGTH,
    RATE_LIMIT_PER_HOUR,
    TAG_WHITELIST,
    VALID_MESSAGE_TYPES,
)


@pytest.fixture
def memory():
    return CouncilMemory(database_url="postgresql://test:test@localhost:5432/testdb", agent_id="puck")


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

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()

    assert memory._pool is mock_pool
    await memory.close()


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


@pytest.mark.asyncio
async def test_write_entry_inserts_row(memory):
    entry_id = uuid4()
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=0)
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value={"id": entry_id})

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        result = await memory.write_entry("hello council", ["general"], [0.1, 0.2, 0.3])

    assert result["success"] is True
    assert result["id"] == str(entry_id)
    mock_conn.fetchrow.assert_called_once()
    call_args = mock_conn.fetchrow.call_args[0]
    assert "INSERT INTO council_memory" in call_args[0]
    assert call_args[1] == "puck"
    assert call_args[2] == "hello council"
    await memory.close()


@pytest.mark.asyncio
async def test_write_entry_with_custom_message_type(memory):
    entry_id = uuid4()
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=0)
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value={"id": entry_id})

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        result = await memory.write_entry("new skill available", ["skill"], [0.1], message_type="skill_announcement")

    assert result["success"] is True
    call_args = mock_conn.fetchrow.call_args[0]
    assert call_args[5] == "skill_announcement"
    await memory.close()


@pytest.mark.asyncio
async def test_write_rejects_content_over_2000_chars(memory):
    memory._pool = MagicMock()
    long_content = "x" * (MAX_CONTENT_LENGTH + 1)
    result = await memory.write_entry(long_content, ["general"], [0.1])
    assert result["success"] is False
    assert f"Content exceeds {MAX_CONTENT_LENGTH} characters" in result["error"]
    assert result["id"] is None


@pytest.mark.asyncio
async def test_write_accepts_content_at_max_length(memory):
    entry_id = uuid4()
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=0)
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value={"id": entry_id})

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        max_content = "x" * MAX_CONTENT_LENGTH
        result = await memory.write_entry(max_content, ["general"], [0.1])

    assert result["success"] is True
    await memory.close()


@pytest.mark.asyncio
async def test_write_rejects_invalid_message_type(memory):
    memory._pool = MagicMock()
    result = await memory.write_entry("content", ["general"], [0.1], message_type="invalid_type")
    assert result["success"] is False
    assert "Invalid message_type: invalid_type" in result["error"]
    assert result["id"] is None


@pytest.mark.asyncio
async def test_write_rejects_invalid_tags(memory):
    memory._pool = MagicMock()
    result = await memory.write_entry("content", ["general", "notarealtag"], [0.1])
    assert result["success"] is False
    assert "Invalid tags" in result["error"]
    assert "notarealtag" in result["error"]
    assert result["id"] is None


@pytest.mark.asyncio
async def test_write_validation_order_content_before_message_type(memory):
    result = await memory.write_entry("x" * (MAX_CONTENT_LENGTH + 1), ["notarealtag"], [0.1], message_type="bad_type")
    assert result["success"] is False
    assert f"Content exceeds {MAX_CONTENT_LENGTH} characters" in result["error"]


@pytest.mark.asyncio
async def test_write_validation_order_message_type_before_tags(memory):
    result = await memory.write_entry("valid content", ["notarealtag"], [0.1], message_type="bad_type")
    assert result["success"] is False
    assert "Invalid message_type: bad_type" in result["error"]


@pytest.mark.asyncio
async def test_write_rate_limits_ten_per_hour(memory):
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=RATE_LIMIT_PER_HOUR)

    memory._pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    memory._pool.acquire = _acquire

    result = await memory.write_entry("content", ["general"], [0.1])
    assert result["success"] is False
    assert f"Rate limit exceeded: {RATE_LIMIT_PER_HOUR} writes/hour" in result["error"]


@pytest.mark.asyncio
async def test_write_allows_under_rate_limit(memory):
    entry_id = uuid4()
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=RATE_LIMIT_PER_HOUR - 1)
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value={"id": entry_id})

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        result = await memory.write_entry("content", ["general"], [0.1])

    assert result["success"] is True
    await memory.close()


@pytest.mark.asyncio
async def test_write_dedup_rejects_cosine_similarity_above_threshold(memory):
    existing_embedding = [1.0, 0.0, 0.0]
    new_embedding = [0.999, 0.001, 0.0]
    sim = CouncilMemory._cosine_similarity(new_embedding, existing_embedding)

    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, key: {"embedding": existing_embedding}[key]

    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=0)
    mock_conn.fetch = AsyncMock(return_value=[{"embedding": existing_embedding}])

    memory._pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    memory._pool.acquire = _acquire

    if sim > DEDUP_SIMILARITY_THRESHOLD:
        result = await memory.write_entry("duplicate content", ["general"], new_embedding)
        assert result["success"] is False
        assert "Duplicate entry" in result["error"]


@pytest.mark.asyncio
async def test_write_dedup_allows_below_threshold(memory):
    entry_id = uuid4()
    existing_embedding = [1.0, 0.0, 0.0]
    new_embedding = [0.5, 0.5, 0.5]
    sim = CouncilMemory._cosine_similarity(new_embedding, existing_embedding)

    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=0)
    mock_conn.fetch = AsyncMock(return_value=[{"embedding": existing_embedding}])
    mock_conn.fetchrow = AsyncMock(return_value={"id": entry_id})

    memory._pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    memory._pool.acquire = _acquire

    if sim <= DEDUP_SIMILARITY_THRESHOLD:
        result = await memory.write_entry("different content", ["general"], new_embedding)
        assert result["success"] is True


@pytest.mark.asyncio
async def test_write_without_pool_returns_not_connected(memory):
    memory._pool = None
    result = await memory.write_entry("content", ["general"], [0.1])
    assert result["success"] is False
    assert result["error"] == "Not connected"


@pytest.mark.asyncio
async def test_search_returns_matching_entries(memory):
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[
        {
            "id": uuid4(),
            "contributing_agent": "puck",
            "content": "council insight",
            "tags": ["general"],
            "message_type": "insight",
            "confidence": 0.9,
            "created_at": now,
        }
    ])

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        results = await memory.search([0.1, 0.2, 0.3])

    assert len(results) == 1
    assert results[0]["content"] == "council insight"
    assert results[0]["contributing_agent"] == "puck"
    assert results[0]["message_type"] == "insight"
    assert results[0]["confidence"] == 0.9
    await memory.close()


@pytest.mark.asyncio
async def test_search_filters_by_tags(memory):
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        results = await memory.search([0.1, 0.2, 0.3], tags=["skill"])

    assert results == []
    call_args = mock_conn.fetch.call_args[0]
    assert "tags &&" in call_args[0]
    assert call_args[1] == ["skill"]
    await memory.close()


@pytest.mark.asyncio
async def test_search_without_tags_omits_filter(memory):
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        results = await memory.search([0.1, 0.2, 0.3])

    call_args = mock_conn.fetch.call_args[0]
    assert "tags &&" not in call_args[0]
    await memory.close()


@pytest.mark.asyncio
async def test_search_respects_limit(memory):
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        await memory.search([0.1], limit=5)

    call_args = mock_conn.fetch.call_args[0]
    assert call_args[-1] == 5
    await memory.close()


@pytest.mark.asyncio
async def test_search_without_pool_returns_empty(memory):
    memory._pool = None
    results = await memory.search([0.1])
    assert results == []


@pytest.mark.asyncio
async def test_delete_entry_removes_row(memory):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value="DELETE 1")

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        result = await memory.delete_entry(str(uuid4()))

    assert result is True
    await memory.close()


@pytest.mark.asyncio
async def test_delete_entry_not_found(memory):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value="DELETE 0")

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        result = await memory.delete_entry(str(uuid4()))

    assert result is False
    await memory.close()


@pytest.mark.asyncio
async def test_delete_entry_without_pool(memory):
    memory._pool = None
    result = await memory.delete_entry(str(uuid4()))
    assert result is False


@pytest.mark.asyncio
async def test_get_entry_returns_entry(memory):
    entry_id = uuid4()
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={
        "id": entry_id,
        "contributing_agent": "puck",
        "content": "an insight",
        "tags": ["general"],
        "message_type": "insight",
        "confidence": 0.85,
        "created_at": now,
    })

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        result = await memory.get_entry(str(entry_id))

    assert result is not None
    assert result["id"] == str(entry_id)
    assert result["content"] == "an insight"
    assert result["tags"] == ["general"]
    await memory.close()


@pytest.mark.asyncio
async def test_get_entry_not_found(memory):
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        result = await memory.get_entry(str(uuid4()))

    assert result is None
    await memory.close()


@pytest.mark.asyncio
async def test_get_entry_without_pool(memory):
    memory._pool = None
    result = await memory.get_entry(str(uuid4()))
    assert result is None


@pytest.mark.asyncio
async def test_list_entries_returns_rows(memory):
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[
        {
            "id": uuid4(),
            "contributing_agent": "puck",
            "content": "first insight",
            "tags": ["general"],
            "message_type": "insight",
            "confidence": 0.9,
            "created_at": now,
        },
        {
            "id": uuid4(),
            "contributing_agent": "mustardseed",
            "content": "second insight",
            "tags": ["idea"],
            "message_type": "proposal",
            "confidence": 0.7,
            "created_at": now,
        },
    ])

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        results = await memory.list_entries()

    assert len(results) == 2
    assert results[0]["content"] == "first insight"
    assert results[1]["content"] == "second insight"
    await memory.close()


@pytest.mark.asyncio
async def test_list_entries_with_pagination(memory):
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        await memory.list_entries(limit=10, offset=20)

    call_args = mock_conn.fetch.call_args[0]
    assert call_args[1] == 10
    assert call_args[2] == 20
    await memory.close()


@pytest.mark.asyncio
async def test_list_entries_without_pool(memory):
    memory._pool = None
    results = await memory.list_entries()
    assert results == []


def test_tag_whitelist_values():
    assert "general" in TAG_WHITELIST
    assert "idea" in TAG_WHITELIST
    assert "observation" in TAG_WHITELIST
    assert "question" in TAG_WHITELIST
    assert "skill" in TAG_WHITELIST
    assert "proposal" in TAG_WHITELIST
    assert "announcement" in TAG_WHITELIST
    assert "learning" in TAG_WHITELIST


def test_tag_whitelist_excludes_invalid():
    assert "invalid" not in TAG_WHITELIST
    assert "random" not in TAG_WHITELIST


def test_valid_message_types():
    assert "insight" in VALID_MESSAGE_TYPES
    assert "skill_announcement" in VALID_MESSAGE_TYPES
    assert "question" in VALID_MESSAGE_TYPES
    assert "proposal" in VALID_MESSAGE_TYPES


def test_valid_message_types_excludes_invalid():
    assert "invalid" not in VALID_MESSAGE_TYPES
    assert "broadcast" not in VALID_MESSAGE_TYPES


def test_cosine_similarity_identical_vectors():
    vec = [1.0, 2.0, 3.0]
    sim = CouncilMemory._cosine_similarity(vec, vec)
    assert abs(sim - 1.0) < 1e-9


def test_cosine_similarity_orthogonal_vectors():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    sim = CouncilMemory._cosine_similarity(a, b)
    assert abs(sim) < 1e-9


def test_cosine_similarity_zero_vector():
    a = [1.0, 2.0]
    b = [0.0, 0.0]
    sim = CouncilMemory._cosine_similarity(a, b)
    assert sim == 0.0


def test_cosine_similarity_string_embedding():
    a = [1.0, 0.0, 0.0]
    b_str = "[1.0, 0.0, 0.0]"
    sim = CouncilMemory._cosine_similarity(a, b_str)
    assert abs(sim - 1.0) < 1e-9


def test_cosine_similarity_opposite_vectors():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    sim = CouncilMemory._cosine_similarity(a, b)
    assert abs(sim - (-1.0)) < 1e-9


def test_constants_values():
    assert MAX_CONTENT_LENGTH == 2000
    assert RATE_LIMIT_PER_HOUR == 10
    assert DEDUP_SIMILARITY_THRESHOLD == 0.95


@pytest.mark.asyncio
async def test_search_empty_results(memory):
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    mock_pool = _make_pool_mock(acquire_return=mock_conn)

    with patch("pillywiggins.memory.council.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        await memory.connect()
        results = await memory.search([0.1, 0.2, 0.3])

    assert results == []
    await memory.close()