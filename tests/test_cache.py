from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.memory.cache import ConversationCache


@pytest.fixture
def cache():
    return ConversationCache(redis_url="redis://localhost:6379/0")


@pytest.mark.asyncio
async def test_save_and_load_round_trip():
    from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, ModelResponse, UserPromptPart, TextPart

    messages = [
        ModelRequest(parts=[UserPromptPart(content="hello")]),
        ModelResponse(parts=[TextPart(content="hi there")]),
    ]
    serialized = ModelMessagesTypeAdapter.dump_json(messages)

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()
    mock_redis.get = AsyncMock(return_value=serialized)
    mock_redis.close = AsyncMock()

    cache = ConversationCache(redis_url="redis://localhost:6379/0")

    with patch("pillywiggins.memory.cache.aioredis.from_url", return_value=mock_redis):
        await cache.save("puck", messages)
        result = await cache.load("puck")

    assert result is not None
    assert len(result) == 2
    assert result[0].kind == "request"
    assert result[1].kind == "response"


@pytest.mark.asyncio
async def test_load_returns_none_for_missing_key(cache):
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.close = AsyncMock()

    with patch("pillywiggins.memory.cache.aioredis.from_url", return_value=mock_redis):
        result = await cache.load("unknown_agent")

    assert result is None
    cache._redis = None


@pytest.mark.asyncio
async def test_save_failure_is_graceful(cache):
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(side_effect=Exception("connection refused"))
    mock_redis.close = AsyncMock()

    with patch("pillywiggins.memory.cache.aioredis.from_url", return_value=mock_redis):
        await cache.save("puck", [])

    cache._redis = None


@pytest.mark.asyncio
async def test_load_failure_returns_none(cache):
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=Exception("connection refused"))
    mock_redis.close = AsyncMock()

    with patch("pillywiggins.memory.cache.aioredis.from_url", return_value=mock_redis):
        result = await cache.load("puck")

    assert result is None
    cache._redis = None


@pytest.mark.asyncio
async def test_close_cleans_up_connection(cache):
    mock_redis = AsyncMock()
    mock_redis.close = AsyncMock()
    cache._redis = mock_redis

    await cache.close()

    mock_redis.close.assert_called_once()
    assert cache._redis is None


@pytest.mark.asyncio
async def test_close_does_nothing_if_no_connection(cache):
    assert cache._redis is None
    await cache.close()
    assert cache._redis is None


@pytest.mark.asyncio
async def test_save_sets_ttl(cache):
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    messages = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()
    mock_redis.close = AsyncMock()

    with patch("pillywiggins.memory.cache.aioredis.from_url", return_value=mock_redis):
        await cache.save("puck", messages)

    call_args = mock_redis.set.call_args
    assert call_args[0][0] == "conversation:puck"
    assert call_args[1]["ex"] == 1800
    cache._redis = None