import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.memory.embeddings import (
    check_embedding_health,
    embed,
    embed_texts,
    get_expected_dimension,
    normalize_ollama_url,
    KNOWN_EMBEDDING_DIMENSIONS,
)
from tests.helpers import make_mock_aiohttp_response, make_mock_aiohttp_session


@pytest.fixture(autouse=True)
def clear_embedding_cache(monkeypatch):
    """Clear the global embedding cache and session before every test so tests are isolated."""
    from pillywiggins.memory import embeddings as emb_mod

    emb_mod._embedding_cache.clear()
    monkeypatch.setattr(emb_mod, "_CACHE_TTL_SECONDS", 3600)
    monkeypatch.setattr(emb_mod, "_MAX_RETRIES", 3)
    emb_mod._session = None
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_DIMENSION", raising=False)


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
async def test_embed_texts_ollama_empty_embeddings_returns_none():
    """When Ollama returns an empty embeddings list, that's an error -- return None."""
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={
            "model": "nomic-embed-text",
            "embeddings": [],
        },
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed_texts(["hello"], "http://localhost:11434", "", "ollama", model="nomic-embed-text")

    assert result is None


# ---- Retry logic tests ----


@pytest.mark.asyncio
async def test_embed_retries_on_5xx_then_succeeds():
    """Should retry on 5xx and eventually succeed."""
    fail_resp = make_mock_aiohttp_response(status=503, text_data="ollama busy")
    success_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]},
    )

    mock_session = make_mock_aiohttp_session(method="post", side_effect=[fail_resp, success_resp])

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        start = time.monotonic()
        result = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")
        elapsed = time.monotonic() - start

    assert result == [0.1, 0.2, 0.3]
    assert mock_session.post.call_count == 2
    assert elapsed >= 0.5  # at least one backoff delay


@pytest.mark.asyncio
async def test_embed_retries_on_network_exception_then_succeeds():
    """Should retry on network exception and eventually succeed."""
    success_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]},
    )

    mock_session = make_mock_aiohttp_session(method="post", side_effect=[Exception("connection refused"), success_resp])

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")

    assert result == [0.1, 0.2, 0.3]
    assert mock_session.post.call_count == 2


@pytest.mark.asyncio
async def test_embed_retries_exhaustion_returns_none():
    """Should return None after all retries exhausted."""
    fail_resp = make_mock_aiohttp_response(status=503, text_data="still busy")

    mock_session = make_mock_aiohttp_session(method="post", side_effect=[fail_resp, fail_resp, fail_resp, fail_resp])

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")

    assert result is None
    assert mock_session.post.call_count == 3  # _MAX_RETRIES attempts total


@pytest.mark.asyncio
async def test_embed_no_retry_on_4xx():
    """Should not retry on 4xx client errors."""
    fail_resp = make_mock_aiohttp_response(status=400, text_data="bad request")

    mock_session = make_mock_aiohttp_session(method="post", response=fail_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")

    assert result is None
    assert mock_session.post.call_count == 1


# ---- Cache logic tests ----


@pytest.mark.asyncio
async def test_embed_caches_result():
    """Same text should hit cache on second call."""
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result1 = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")
        result2 = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")

    assert result1 == [0.1, 0.2, 0.3]
    assert result2 == [0.1, 0.2, 0.3]
    assert mock_session.post.call_count == 1  # cached on second call


@pytest.mark.asyncio
async def test_embed_cache_key_includes_model_and_provider():
    """Cache key should differentiate by model and provider."""
    ollama_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]},
    )
    openai_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"data": [{"embedding": [0.4, 0.5, 0.6], "index": 0}]},
    )

    mock_session = make_mock_aiohttp_session(method="post", side_effect=[ollama_resp, ollama_resp, openai_resp])

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        r1 = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")
        r2 = await embed("hello", "http://localhost:11434", "", "ollama", model="all-minilm")
        r3 = await embed("hello", "http://other", "", "openai", model="nomic-embed-text")

    assert r1 is not None
    assert r2 is not None
    assert r3 is not None
    assert mock_session.post.call_count == 3


@pytest.mark.asyncio
async def test_embed_cache_ttl_expires(monkeypatch):
    """Cache entry should expire after TTL."""
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    monkeypatch.setattr("pillywiggins.memory.embeddings._CACHE_TTL_SECONDS", 0.05)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result1 = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")
        await asyncio.sleep(0.1)  # wait for TTL
        result2 = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")

    assert result1 == [0.1, 0.2, 0.3]
    assert result2 == [0.1, 0.2, 0.3]
    assert mock_session.post.call_count == 2  # not cached after TTL


@pytest.mark.asyncio
async def test_embed_cache_can_be_disabled():
    """Passing use_cache=False should skip the cache."""
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result1 = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")
        result2 = await embed("hello", "http://localhost:11434", "", "ollama", use_cache=False, model="nomic-embed-text")

    assert result1 == [0.1, 0.2, 0.3]
    assert result2 == [0.1, 0.2, 0.3]
    assert mock_session.post.call_count == 2


@pytest.mark.asyncio
async def test_embed_texts_caches_result():
    """Same batch should hit cache on second call."""
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={
            "model": "nomic-embed-text",
            "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        },
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result1 = await embed_texts(["hello", "world"], "http://localhost:11434", "", "ollama", model="nomic-embed-text")
        result2 = await embed_texts(["hello", "world"], "http://localhost:11434", "", "ollama", model="nomic-embed-text")

    assert result1 == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert result2 == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert mock_session.post.call_count == 1


@pytest.mark.asyncio
async def test_embed_texts_retries_on_5xx_then_succeeds():
    """Batch embed should also retry on 5xx."""
    fail_resp = make_mock_aiohttp_response(status=502, text_data="bad gateway")
    success_resp = make_mock_aiohttp_response(
        status=200,
        json_data={
            "model": "nomic-embed-text",
            "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        },
    )

    mock_session = make_mock_aiohttp_session(method="post", side_effect=[fail_resp, success_resp])

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed_texts(["hello", "world"], "http://localhost:11434", "", "ollama", model="nomic-embed-text")

    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert mock_session.post.call_count == 2


@pytest.mark.asyncio
async def test_embed_openai_no_api_key_no_auth():
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "https://api.example.com/v1", "", "openai", model="nomic-embed-text")

    assert result == [0.1, 0.2, 0.3]
    call_kwargs = mock_session.post.call_args
    headers = call_kwargs[1].get("headers", {}) if len(call_kwargs) > 1 else {}
    assert "Authorization" not in headers
    assert headers.get("Content-Type") == "application/json"


@pytest.mark.asyncio
async def test_embed_ollama_no_api_key_no_auth():
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")

    assert result == [0.1, 0.2, 0.3]
    call_kwargs = mock_session.post.call_args
    headers = call_kwargs[1].get("headers", {}) if len(call_kwargs) > 1 else {}
    assert headers == {}


# ---- URL normalization tests ----


def test_normalize_ollama_url_strips_v1():
    """Should strip /v1 suffix from Ollama base URL."""
    assert normalize_ollama_url("http://localhost:11434/v1") == "http://localhost:11434"
    assert normalize_ollama_url("http://localhost:11434/v1/") == "http://localhost:11434"


def test_normalize_ollama_url_no_v1():
    """Should pass through URLs without /v1 unchanged."""
    assert normalize_ollama_url("http://localhost:11434") == "http://localhost:11434"
    assert normalize_ollama_url("http://localhost:11434/") == "http://localhost:11434"


def test_normalize_ollama_url_docker_internal():
    """Should handle docker-internal URLs with /v1."""
    assert normalize_ollama_url("http://host.docker.internal:11434/v1") == "http://host.docker.internal:11434"


@pytest.mark.asyncio
async def test_embed_ollama_url_strips_v1():
    """Embedding with Ollama should strip /v1 from base URL before calling /api/embed."""
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [[0.1] * 768]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://host.docker.internal:11434/v1", "", "ollama", model="nomic-embed-text")

    assert result is not None
    # Verify the URL was normalized: /v1 removed before /api/embed appended
    call_args = mock_session.post.call_args
    called_url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert called_url == "http://host.docker.internal:11434/api/embed"
    assert "/v1/api/embed" not in called_url


@pytest.mark.asyncio
async def test_embed_openai_url_preserves_v1():
    """Embedding with OpenAI provider should NOT strip /v1 from base URL."""
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "https://api.openai.com/v1", "", "openai", model="nomic-embed-text")

    assert result is not None
    call_args = mock_session.post.call_args
    called_url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert called_url == "https://api.openai.com/v1/embeddings"


# ---- Dimension validation tests ----


@pytest.mark.asyncio
async def test_embed_dimension_match_passes():
    """embed() should return the vector when expected_dimension matches."""
    vec768 = [0.1] * 768
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [vec768]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text", expected_dimension=768)

    assert result is not None
    assert len(result) == 768


@pytest.mark.asyncio
async def test_embed_dimension_mismatch_returns_none():
    """embed() should return None and log error when dimension doesn't match."""
    vec3 = [0.1, 0.2, 0.3]
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [vec3]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text", expected_dimension=768)

    assert result is None


@pytest.mark.asyncio
async def test_embed_texts_dimension_mismatch_returns_none():
    """embed_texts() should return None when any vector dimension doesn't match."""
    vec3 = [0.1, 0.2, 0.3]
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [vec3, vec3]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed_texts(
            ["hello", "world"], "http://localhost:11434", "", "ollama", expected_dimension=768
        )

    assert result is None


@pytest.mark.asyncio
async def test_embed_no_dimension_check_when_not_provided():
    """embed() without expected_dimension should not validate dimensions."""
    vec3 = [0.1, 0.2, 0.3]
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [vec3]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")

    # No expected_dimension provided, so short vector passes through
    assert result == vec3


# ---- get_expected_dimension / KNOWN_EMBEDDING_DIMENSIONS tests ----


def test_known_dimensions_include_nomic():
    """nomic-embed-text should be in the known dimensions map."""
    assert "nomic-embed-text" in KNOWN_EMBEDDING_DIMENSIONS
    assert KNOWN_EMBEDDING_DIMENSIONS["nomic-embed-text"] == 768


def test_get_expected_dimension_known():
    """get_expected_dimension should return the known dimension for a known model."""
    assert get_expected_dimension("nomic-embed-text") == 768
    assert get_expected_dimension("mxbai-embed-large") == 1024


def test_get_expected_dimension_unknown_uses_fallback():
    """get_expected_dimension should use fallback for unknown models."""
    assert get_expected_dimension("unknown-model", fallback=512) == 512


def test_get_expected_dimension_default_fallback():
    """get_expected_dimension default fallback should be 768."""
    assert get_expected_dimension("totally-unknown") == 768


def test_config_embedding_dimension_matches_schema():
    """Config.embedding_dimension default should match the pgvector column width."""
    from pillywiggins.config import Settings

    settings = Settings()
    assert settings.embedding_dimension == 768
    # The default model is 'auto', which resolves to a known 768-dim model
    # (e.g. nomic-embed-text).  get_expected_dimension handles the fallback.
    assert get_expected_dimension(settings.embedding_model) == settings.embedding_dimension


# ---- Embedding health check tests ----


@pytest.mark.asyncio
async def test_check_embedding_health_success():
    """Health check should report healthy when embedding endpoint works."""
    vec768 = [0.1] * 768
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [vec768]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await check_embedding_health(
            base_url="http://localhost:11434/v1",
            api_key="",
            provider="ollama",
            model="nomic-embed-text",
            expected_dimension=768,
        )

    assert result["healthy"] is True
    assert result["dimension"] == 768
    assert result["dimension_match"] is True
    assert result["error"] is None


@pytest.mark.asyncio
async def test_check_embedding_health_dimension_mismatch():
    """Health check should report unhealthy on dimension mismatch."""
    vec3 = [0.1, 0.2, 0.3]
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [vec3]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await check_embedding_health(
            base_url="http://localhost:11434/v1",
            api_key="",
            provider="ollama",
            model="nomic-embed-text",
            expected_dimension=768,
        )

    assert result["healthy"] is False
    assert result["dimension"] == 3
    assert result["dimension_match"] is False
    assert "mismatch" in result["error"].lower()


@pytest.mark.asyncio
async def test_check_embedding_health_endpoint_failure():
    """Health check should report unhealthy when endpoint fails."""
    fail_resp = make_mock_aiohttp_response(status=500, text_data="internal error")
    mock_session = make_mock_aiohttp_session(method="post", response=fail_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await check_embedding_health(
            base_url="http://localhost:11434/v1",
            api_key="",
            provider="ollama",
            model="nomic-embed-text",
            expected_dimension=768,
        )

    assert result["healthy"] is False
    assert "error" in result["error"].lower() or "None" in result["error"]


@pytest.mark.asyncio
async def test_check_embedding_health_no_expected_dimension():
    """Health check without expected_dimension should pass if endpoint works."""
    vec3 = [0.1, 0.2, 0.3]
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": [vec3]},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await check_embedding_health(
            base_url="http://localhost:11434/v1",
            api_key="",
            provider="ollama",
            model="nomic-embed-text",
            expected_dimension=None,
        )

    assert result["healthy"] is True
    assert result["dimension"] == 3
    assert result["dimension_match"] is None  # not checked


@pytest.mark.asyncio
async def test_embed_texts_empty_embeddings_returns_none():
    """When Ollama returns an empty embeddings list, that's an error -- return None."""
    mock_resp = make_mock_aiohttp_response(
        status=200,
        json_data={"model": "nomic-embed-text", "embeddings": []},
    )
    mock_session = make_mock_aiohttp_session(method="post", response=mock_resp)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed_texts(
            ["hello"], "http://localhost:11434", "", "ollama", model="nomic-embed-text"
        )

    assert result is None


@pytest.mark.asyncio
async def test_embed_unparseable_json_returns_none_then_retries(caplog):
    """When a response is not valid JSON, retry is attempted."""
    from tests.helpers import make_mock_aiohttp_response, make_mock_aiohttp_session

    bad_resp = make_mock_aiohttp_response(status=200, text_data="not json")
    bad_resp.json = AsyncMock(side_effect=RuntimeError("unparseable"))  # simulate json() raising
    good_resp = make_mock_aiohttp_response(
        status=200, json_data={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]}
    )
    mock_session = make_mock_aiohttp_session(method="post", side_effect=[bad_resp, good_resp])

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        with caplog.at_level("WARNING"):
            result = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")

    assert result == [0.1, 0.2, 0.3]
    assert mock_session.post.call_count == 2
    assert "retrying" in caplog.text


@pytest.mark.asyncio
async def test_embed_network_timeout_retries_then_fails(caplog, monkeypatch):
    """Network-level exception on every attempt should exhaust retries and return None."""
    monkeypatch.setattr("pillywiggins.memory.embeddings._MAX_RETRIES", 2)
    mock_session = make_mock_aiohttp_session(
        method="post", side_effect=[asyncio.TimeoutError("timed out"), asyncio.TimeoutError("timed out")]
    )

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        with caplog.at_level("ERROR"):
            result = await embed("hello", "http://localhost:11434", "", "ollama", model="nomic-embed-text")

    assert result is None
    assert mock_session.post.call_count == 2
    assert "Error generating embedding" in caplog.text
