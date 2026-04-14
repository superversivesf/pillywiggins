import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.adapters.models import ModelInfo, list_models


@pytest.fixture
def ollama_response():
    return {
        "data": [
            {"id": "qwen3.5:8b", "owned_by": "ollama"},
            {"id": "llama3:8b", "owned_by": "ollama"},
        ]
    }


@pytest.fixture
def openai_response():
    return {
        "data": [
            {"id": "gpt-4", "owned_by": "openai"},
        ]
    }


@pytest.mark.asyncio
async def test_list_models_ollama_url():
    response_data = {
        "data": [
            {"id": "qwen3.5:8b", "owned_by": "ollama"},
        ]
    }
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=response_data)
    mock_resp.text = AsyncMock(return_value=json.dumps(response_data))
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.adapters.models.aiohttp.ClientSession", return_value=mock_session):
        result = await list_models("http://localhost:11434", "", "ollama")

    assert len(result) == 1
    assert result[0] == ModelInfo(id="qwen3.5:8b", owned_by="ollama")
    mock_session.get.assert_called_once()
    call_args = mock_session.get.call_args
    assert "/v1/models" in call_args[0][0]


@pytest.mark.asyncio
async def test_list_models_openai_url():
    response_data = {
        "data": [
            {"id": "gpt-4", "owned_by": "openai"},
        ]
    }
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=response_data)
    mock_resp.text = AsyncMock(return_value=json.dumps(response_data))
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.adapters.models.aiohttp.ClientSession", return_value=mock_session):
        result = await list_models("https://api.openai.com", "sk-test-key", "openai")

    assert len(result) == 1
    assert result[0] == ModelInfo(id="gpt-4", owned_by="openai")
    call_args = mock_session.get.call_args
    assert "/models" in call_args[0][0]
    assert "/v1/models" not in call_args[0][0]


@pytest.mark.asyncio
async def test_list_models_non_200_returns_empty():
    mock_resp = AsyncMock()
    mock_resp.status = 500
    mock_resp.text = AsyncMock(return_value="Internal Server Error")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.adapters.models.aiohttp.ClientSession", return_value=mock_session):
        result = await list_models("http://localhost:11434", "", "ollama")

    assert result == []


@pytest.mark.asyncio
async def test_list_models_exception_returns_empty():
    mock_session = AsyncMock()
    mock_session.get = MagicMock(side_effect=Exception("connection refused"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.adapters.models.aiohttp.ClientSession", return_value=mock_session):
        result = await list_models("http://localhost:11434", "", "ollama")

    assert result == []


@pytest.mark.asyncio
async def test_list_models_empty_data():
    response_data = {"data": []}
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=response_data)
    mock_resp.text = AsyncMock(return_value=json.dumps(response_data))
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.adapters.models.aiohttp.ClientSession", return_value=mock_session):
        result = await list_models("http://localhost:11434", "", "ollama")

    assert result == []


@pytest.mark.asyncio
async def test_list_models_strips_trailing_slash():
    response_data = {"data": [{"id": "test-model", "owned_by": "ollama"}]}
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=response_data)
    mock_resp.text = AsyncMock(return_value=json.dumps(response_data))
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.adapters.models.aiohttp.ClientSession", return_value=mock_session):
        await list_models("http://localhost:11434/", "", "ollama")

    call_url = mock_session.get.call_args[0][0]
    assert "11434/v1/models" in call_url
    assert "11434//v1" not in call_url


@pytest.mark.asyncio
async def test_list_models_includes_auth_header():
    response_data = {"data": []}
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=response_data)
    mock_resp.text = AsyncMock(return_value=json.dumps(response_data))
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pillywiggins.adapters.models.aiohttp.ClientSession", return_value=mock_session):
        await list_models("https://api.openai.com", "sk-test", "openai")

    call_kwargs = mock_session.get.call_args
    headers = call_kwargs[1].get("headers") or call_kwargs.kwargs.get("headers")
    assert headers["Authorization"] == "Bearer sk-test"