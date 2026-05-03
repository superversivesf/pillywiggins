"""Tests for brave_search skill."""
import importlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def skill_module(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    import shutil

    shutil.copy2(
        "skills/brave_search.py",
        skills_dir / "brave_search.py",
    )
    if "brave_search" in sys.modules:
        del sys.modules["brave_search"]
    spec = importlib.util.spec_from_file_location(
        "brave_search",
        str(skills_dir / "brave_search.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_brave_search_no_api_key(skill_module):
    """Without BRAVE_API_KEY, returns helpful error."""
    with patch.dict("os.environ", {}, clear=True):
        result = await skill_module.run("hello world")

    assert result["results"] == []
    assert "error" in result
    assert "BRAVE_API_KEY" in result["error"]


@pytest.mark.asyncio
async def test_brave_search_success(skill_module):
    """Happy path returns parsed results."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "web": {
                "results": [
                    {
                        "title": "Hello World Example",
                        "url": "https://example.com/hello",
                        "description": "A hello world tutorial",
                        "score": 0.95,
                        "extra_snippets": ["Snippet 1", "Snippet 2"],
                    }
                ]
            }
        }
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}),
        patch("aiohttp.ClientSession", return_value=mock_session),
    ):
        result = await skill_module.run("hello world", count=5)

    assert result.get("error") is None
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Hello World Example"
    assert result["results"][0]["url"] == "https://example.com/hello"
    assert result["results"][0]["score"] == 0.95
    assert "extra_snippets" in result["results"][0]


@pytest.mark.asyncio
async def test_brave_search_rate_limit(skill_module):
    """429 returns rate limit error."""
    mock_resp = AsyncMock()
    mock_resp.status = 429
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}),
        patch("aiohttp.ClientSession", return_value=mock_session),
    ):
        result = await skill_module.run("hello world")

    assert "rate limit" in result["error"].lower()


@pytest.mark.asyncio
async def test_brave_search_401_invalid_key(skill_module):
    """401 returns invalid key error immediately (no retry)."""
    mock_resp = AsyncMock()
    mock_resp.status = 401
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", {"BRAVE_API_KEY": "bad-key"}),
        patch("aiohttp.ClientSession", return_value=mock_session),
    ):
        result = await skill_module.run("hello world")

    assert "invalid" in result["error"].lower()
    assert mock_session.get.call_count == 1  # no retries


@pytest.mark.asyncio
async def test_brave_search_empty_results(skill_module):
    """Empty results from API returns friendly error."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"web": {"results": []}})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}),
        patch("aiohttp.ClientSession", return_value=mock_session),
    ):
        result = await skill_module.run("xyzxyzxyz")

    assert "No results" in result["error"]


def test_brave_search_skill_meta(skill_module):
    """SKILL_META is valid."""
    assert skill_module.SKILL_META["name"] == "brave_search"
    assert skill_module.SKILL_META["permissions"]["network"] is True
    assert "query" in skill_module.SKILL_META["parameters"]
