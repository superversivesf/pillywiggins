import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.memory.embeddings import embed, embed_texts


@pytest.fixture(autouse=True)
def clear_embedding_cache(monkeypatch):
    """Clear the global embedding cache before every test so tests are isolated."""
    from pillywiggins.memory import embeddings as emb_mod

    emb_mod._embedding_cache.clear()
    monkeypatch.setattr(emb_mod, "_CACHE_TTL_SECONDS", 3600)
    monkeypatch.setattr(emb_mod, "_MAX_RETRIES", 3)


@pytest.fixture
def ollama_response():
    return {
        "model": "nomic-embed-text",
        "embeddings": [[0.1, 0.2, 0.3]],
    }


@pytest.fixture
def openai_response():
    return {
        "data": [{"embedding": [0.4, 0.5, 0.6], "index": 0}],
        "model": "nomic-embed-text",
    }


@pytest.mark.asyncio
async def test_embed_texts_ollama_empty_embeddings_returns_empty():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "model": "nomic-embed-text",
            "embeddings": [],
        }
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed_texts(["hello"], "http://localhost:11434", "", "ollama")

    assert result == []


# ---- Retry logic tests ----


@pytest.mark.asyncio
async def test_embed_retries_on_5xx_then_succeeds():
    """Should retry on 5xx and eventually succeed."""
    fail_resp = AsyncMock()
    fail_resp.status = 503
    fail_resp.text = AsyncMock(return_value="ollama busy")
    fail_resp.__aenter__ = AsyncMock(return_value=fail_resp)
    fail_resp.__aexit__ = AsyncMock(return_value=False)

    success_resp = AsyncMock()
    success_resp.status = 200
    success_resp.json = AsyncMock(
        return_value={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]}
    )
    success_resp.__aenter__ = AsyncMock(return_value=success_resp)
    success_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(side_effect=[fail_resp, success_resp])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        start = time.monotonic()
        result = await embed("hello", "http://localhost:11434", "", "ollama")
        elapsed = time.monotonic() - start

    assert result == [0.1, 0.2, 0.3]
    assert mock_session.post.call_count == 2
    assert elapsed >= 0.5  # at least one backoff delay


@pytest.mark.asyncio
async def test_embed_retries_on_network_exception_then_succeeds():
    """Should retry on network exception and eventually succeed."""
    success_resp = AsyncMock()
    success_resp.status = 200
    success_resp.json = AsyncMock(
        return_value={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]}
    )
    success_resp.__aenter__ = AsyncMock(return_value=success_resp)
    success_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(side_effect=[Exception("connection refused"), success_resp])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama")

    assert result == [0.1, 0.2, 0.3]
    assert mock_session.post.call_count == 2


@pytest.mark.asyncio
async def test_embed_retries_exhaustion_returns_none():
    """Should return None after all retries exhausted."""
    fail_resp = AsyncMock()
    fail_resp.status = 503
    fail_resp.text = AsyncMock(return_value="still busy")
    fail_resp.__aenter__ = AsyncMock(return_value=fail_resp)
    fail_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(side_effect=[fail_resp, fail_resp, fail_resp, fail_resp])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama")

    assert result is None
    assert mock_session.post.call_count == 3  # _MAX_RETRIES attempts total


@pytest.mark.asyncio
async def test_embed_no_retry_on_4xx():
    """Should not retry on 4xx client errors."""
    fail_resp = AsyncMock()
    fail_resp.status = 400
    fail_resp.text = AsyncMock(return_value="bad request")
    fail_resp.__aenter__ = AsyncMock(return_value=fail_resp)
    fail_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=fail_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama")

    assert result is None
    assert mock_session.post.call_count == 1


# ---- Cache logic tests ----


@pytest.mark.asyncio
async def test_embed_caches_result():
    """Same text should hit cache on second call."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]}
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result1 = await embed("hello", "http://localhost:11434", "", "ollama")
        result2 = await embed("hello", "http://localhost:11434", "", "ollama")

    assert result1 == [0.1, 0.2, 0.3]
    assert result2 == [0.1, 0.2, 0.3]
    assert mock_session.post.call_count == 1  # cached on second call


@pytest.mark.asyncio
async def test_embed_cache_key_includes_model_and_provider():
    """Cache key should differentiate by model and provider."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]}
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    openai_resp = AsyncMock()
    openai_resp.status = 200
    openai_resp.json = AsyncMock(
        return_value={"data": [{"embedding": [0.4, 0.5, 0.6], "index": 0}]}
    )
    openai_resp.__aenter__ = AsyncMock(return_value=openai_resp)
    openai_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(side_effect=[mock_resp, mock_resp, openai_resp])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        r1 = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")
        r2 = await embed("hello", "http://localhost:11434", "", "ollama", model="all-minilm")
        r3 = await embed("hello", "http://other", "", "openai")

    assert r1 is not None
    assert r2 is not None
    assert r3 is not None
    assert mock_session.post.call_count == 3


@pytest.mark.asyncio
async def test_embed_cache_ttl_expires(monkeypatch):
    """Cache entry should expire after TTL."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]}
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("pillywiggins.memory.embeddings._CACHE_TTL_SECONDS", 0.05)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result1 = await embed("hello", "http://localhost:11434", "", "ollama")
        await asyncio.sleep(0.1)  # wait for TTL
        result2 = await embed("hello", "http://localhost:11434", "", "ollama")

    assert result1 == [0.1, 0.2, 0.3]
    assert result2 == [0.1, 0.2, 0.3]
    assert mock_session.post.call_count == 2  # not cached after TTL


@pytest.mark.asyncio
async def test_embed_cache_can_be_disabled():
    """Passing use_cache=False should skip the cache."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]}
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result1 = await embed("hello", "http://localhost:11434", "", "ollama")
        result2 = await embed("hello", "http://localhost:11434", "", "ollama", use_cache=False)

    assert result1 == [0.1, 0.2, 0.3]
    assert result2 == [0.1, 0.2, 0.3]
    assert mock_session.post.call_count == 2


@pytest.mark.asyncio
async def test_embed_texts_caches_result():
    """Same batch should hit cache on second call."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "model": "nomic-embed-text",
            "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        }
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result1 = await embed_texts(["hello", "world"], "http://localhost:11434", "", "ollama")
        result2 = await embed_texts(["hello", "world"], "http://localhost:11434", "", "ollama")

    assert result1 == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert result2 == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert mock_session.post.call_count == 1


@pytest.mark.asyncio
async def test_embed_texts_retries_on_5xx_then_succeeds():
    """Batch embed should also retry on 5xx."""
    fail_resp = AsyncMock()
    fail_resp.status = 502
    fail_resp.text = AsyncMock(return_value="bad gateway")
    fail_resp.__aenter__ = AsyncMock(return_value=fail_resp)
    fail_resp.__aexit__ = AsyncMock(return_value=False)

    success_resp = AsyncMock()
    success_resp.status = 200
    success_resp.json = AsyncMock(
        return_value={
            "model": "nomic-embed-text",
            "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        }
    )
    success_resp.__aenter__ = AsyncMock(return_value=success_resp)
    success_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(side_effect=[fail_resp, success_resp])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed_texts(["hello", "world"], "http://localhost:11434", "", "ollama")

    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert mock_session.post.call_count == 2


@pytest.mark.asyncio
async def test_embed_openai_no_api_key_no_auth():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}]})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "https://api.example.com/v1", "", "openai")

    assert result == [0.1, 0.2, 0.3]
    call_kwargs = mock_session.post.call_args
    headers = call_kwargs[1].get("headers", {}) if len(call_kwargs) > 1 else {}
    assert "Authorization" not in headers
    assert headers.get("Content-Type") == "application/json"


@pytest.mark.asyncio
async def test_embed_ollama_no_api_key_no_auth():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]}
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama")

    assert result == [0.1, 0.2, 0.3]
    call_kwargs = mock_session.post.call_args
    headers = call_kwargs[1].get("headers", {}) if len(call_kwargs) > 1 else {}
    assert headers == {}
