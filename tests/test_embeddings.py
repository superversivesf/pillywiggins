from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.memory.embeddings import embed, embed_texts


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
async def test_embed_ollama_single():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]})

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_session.post.return_value = mock_resp
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama")

    assert result == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_embed_openai_single():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"data": [{"embedding": [0.4, 0.5, 0.6], "index": 0}]})

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_session.post.return_value = mock_resp
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "https://api.example.com/v1", "sk-test", "openai")

    assert result == [0.4, 0.5, 0.6]


@pytest.mark.asyncio
async def test_embed_returns_none_on_error():
    mock_resp = AsyncMock()
    mock_resp.status = 500
    mock_resp.text = AsyncMock(return_value="internal server error")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama")

    assert result is None


@pytest.mark.asyncio
async def test_embed_returns_none_on_exception():
    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", side_effect=Exception("connection refused")):
        result = await embed("hello", "http://localhost:11434", "", "ollama")

    assert result is None


@pytest.mark.asyncio
async def test_embed_ollama_with_api_key():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "https://ollama.com", "sk-key123", "ollama")

    assert result == [0.1, 0.2, 0.3]
    call_kwargs = mock_session.post.call_args
    headers = call_kwargs[1].get("headers", {}) if len(call_kwargs) > 1 else {}
    assert headers.get("Authorization") == "Bearer sk-key123"


@pytest.mark.asyncio
async def test_embed_ollama_url_format():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434/", "", "ollama")

    assert result is not None
    call_args = mock_session.post.call_args
    assert call_args[1].get("url") or "api/embed" in str(call_args)


@pytest.mark.asyncio
async def test_embed_texts_ollama_batch():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "model": "nomic-embed-text",
        "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed_texts(["hello", "world"], "http://localhost:11434", "", "ollama")

    assert len(result) == 2
    assert result[0] == [0.1, 0.2, 0.3]
    assert result[1] == [0.4, 0.5, 0.6]


@pytest.mark.asyncio
async def test_embed_texts_openai_batch():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "data": [
            {"embedding": [0.1, 0.2, 0.3], "index": 0},
            {"embedding": [0.4, 0.5, 0.6], "index": 1},
        ],
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed_texts(["hello", "world"], "https://api.example.com/v1", "sk-test", "openai")

    assert len(result) == 2


@pytest.mark.asyncio
async def test_embed_texts_returns_none_on_error():
    mock_resp = AsyncMock()
    mock_resp.status = 500
    mock_resp.text = AsyncMock(return_value="error")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed_texts(["hello"], "http://localhost:11434", "", "ollama")

    assert result is None


@pytest.mark.asyncio
async def test_embed_ollama_empty_embeddings():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"model": "nomic-embed-text", "embeddings": []})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "http://localhost:11434", "", "ollama")

    assert result is None


@pytest.mark.asyncio
async def test_embed_openai_empty_data():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"data": []})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed("hello", "https://api.example.com/v1", "sk-test", "openai")

    assert result is None


@pytest.mark.asyncio
async def test_embed_texts_ollama_with_api_key():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "model": "nomic-embed-text",
        "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed_texts(["hello", "world"], "http://localhost:11434", "sk-key", "ollama")

    assert len(result) == 2
    call_kwargs = mock_session.post.call_args
    headers = call_kwargs[1].get("headers", {}) if len(call_kwargs) > 1 else {}
    assert headers.get("Authorization") == "Bearer sk-key"


@pytest.mark.asyncio
async def test_embed_texts_openai_with_auth_header():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "data": [
            {"embedding": [0.1, 0.2, 0.3], "index": 0},
            {"embedding": [0.4, 0.5, 0.6], "index": 1},
        ],
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed_texts(["hello", "world"], "https://api.example.com/v1", "sk-test", "openai")

    assert len(result) == 2
    call_kwargs = mock_session.post.call_args
    headers = call_kwargs[1].get("headers", {}) if len(call_kwargs) > 1 else {}
    assert headers.get("Authorization") == "Bearer sk-test"
    assert headers.get("Content-Type") == "application/json"


@pytest.mark.asyncio
async def test_embed_texts_exception_returns_none():
    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", side_effect=Exception("connection refused")):
        result = await embed_texts(["hello"], "http://localhost:11434", "", "ollama")

    assert result is None


@pytest.mark.asyncio
async def test_embed_texts_openai_empty_data():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"data": []})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed_texts(["hello"], "https://api.example.com/v1", "sk-test", "openai")

    assert result == []


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
    mock_resp.json = AsyncMock(return_value={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]]})
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


@pytest.mark.asyncio
async def test_embed_texts_ollama_empty_embeddings_returns_empty():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "model": "nomic-embed-text",
        "embeddings": [],
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.memory.embeddings.aiohttp.ClientSession", return_value=mock_session):
        result = await embed_texts(["hello"], "http://localhost:11434", "", "ollama")

    assert result == []