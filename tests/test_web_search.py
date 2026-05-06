import importlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.helpers import make_mock_aiohttp_response, make_mock_aiohttp_session


@pytest.fixture
def skill_module(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    import shutil

    shutil.copy2(
        "skills/web_search.py",
        skills_dir / "web_search.py",
    )
    if "web_search" in sys.modules:
        del sys.modules["web_search"]
    spec = importlib.util.spec_from_file_location(
        "web_search",
        str(skills_dir / "web_search.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOCK_SEARCH_RESPONSE = {
    "results": [
        {
            "title": "Python async await",
            "url": "https://docs.python.org/3/library/asyncio.html",
            "content": "Async IO in Python",
            "engine": "google",
        },
        {
            "title": "aiohttp documentation",
            "url": "https://docs.aiohttp.org/",
            "content": "Async HTTP client/server",
            "engine": "duckduckgo",
        },
        {
            "title": "",
            "url": "",
            "content": "skip me",
            "engine": "broken",
        },
    ],
    "query": "python async",
}


class TestWebSearchMeta:
    def test_meta_has_name(self, skill_module):
        assert skill_module.SKILL_META["name"] == "web_search"

    def test_meta_has_description(self, skill_module):
        desc = skill_module.SKILL_META["description"].lower()
        assert "search" in desc and ("searxng" in desc or "local" in desc)

    def test_meta_parameters_query(self, skill_module):
        assert "query" in skill_module.SKILL_META["parameters"]

    def test_meta_parameters_categories(self, skill_module):
        params = skill_module.SKILL_META["parameters"]
        assert "categories" in params
        assert "description" in params["categories"]

    def test_meta_parameters_max_results(self, skill_module):
        params = skill_module.SKILL_META["parameters"]
        assert "max_results" in params

    def test_meta_parameters_engines(self, skill_module):
        params = skill_module.SKILL_META["parameters"]
        assert "engines" in params

    def test_meta_returns_includes_results(self, skill_module):
        assert "results" in skill_module.SKILL_META["returns"]

    def test_meta_permissions_network(self, skill_module):
        assert skill_module.SKILL_META["permissions"]["network"] is True


class TestWebSearchRun:
    @pytest.mark.asyncio
    async def test_returns_results_on_success(self, skill_module):
        mock_resp = make_mock_aiohttp_response(status=200, json_data=MOCK_SEARCH_RESPONSE)
        mock_session = make_mock_aiohttp_session(method="get", response=mock_resp)

        mock_timeout = MagicMock()

        mock_settings = MagicMock()
        mock_settings.searxng_url = "http://searxng:8080"
        mock_settings.searxng_max_results = 5
        mock_settings.get_searxng_categories.return_value = ["general"]

        with patch.object(skill_module.aiohttp, "ClientSession", return_value=mock_session), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=mock_timeout), \
             patch("pillywiggins.config.Settings", return_value=mock_settings):
            result = await skill_module.run("python async")

        assert result["query"] == "python async"
        assert len(result["results"]) == 2
        assert result["results"][0]["title"] == "Python async await"
        assert result["results"][0]["url"] == "https://docs.python.org/3/library/asyncio.html"
        assert result["results"][0]["snippet"] == "Async IO in Python"
        assert result["total_available"] == 3

    @pytest.mark.asyncio
    async def test_skips_empty_results(self, skill_module):
        data_with_empty = {
            "results": [
                {"title": "Good", "url": "https://example.com", "content": "ok", "engine": "google"},
                {"title": "", "url": "", "content": "skip", "engine": "broken"},
            ],
            "query": "test",
        }
        mock_resp = make_mock_aiohttp_response(status=200, json_data=data_with_empty)
        mock_session = make_mock_aiohttp_session(method="get", response=mock_resp)

        mock_timeout = MagicMock()

        mock_settings = MagicMock()
        mock_settings.searxng_url = "http://searxng:8080"
        mock_settings.searxng_max_results = 5
        mock_settings.get_searxng_categories.return_value = ["general"]

        with patch.object(skill_module.aiohttp, "ClientSession", return_value=mock_session), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=mock_timeout), \
             patch("pillywiggins.config.Settings", return_value=mock_settings):
            result = await skill_module.run("test")

        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Good"

    @pytest.mark.asyncio
    async def test_connection_error(self, skill_module):
        mock_settings = MagicMock()
        mock_settings.searxng_url = "http://searxng:8080"
        mock_settings.searxng_max_results = 5
        mock_settings.get_searxng_categories.return_value = ["general"]

        with patch.object(skill_module.aiohttp, "ClientSession", side_effect=Exception("connection refused")), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=MagicMock()), \
             patch("pillywiggins.config.Settings", return_value=mock_settings):
            result = await skill_module.run("test")

        assert result["results"] == []
        assert "error" in result

    @pytest.mark.asyncio
    async def test_connector_error_specific(self, skill_module):
        import aiohttp as real_aiohttp

        mock_settings = MagicMock()
        mock_settings.searxng_url = "http://searxng:8080"
        mock_settings.searxng_max_results = 5
        mock_settings.get_searxng_categories.return_value = ["general"]

        with patch.object(skill_module.aiohttp, "ClientSession", side_effect=real_aiohttp.ClientConnectorError(MockConnectionError(), MagicMock())), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=MagicMock()), \
             patch("pillywiggins.config.Settings", return_value=mock_settings):
            result = await skill_module.run("test")

        assert result["results"] == []
        assert "Cannot connect to SearXNG" in result["error"]

    @pytest.mark.asyncio
    async def test_non_200_status(self, skill_module):
        mock_resp = make_mock_aiohttp_response(status=500)
        mock_session = make_mock_aiohttp_session(method="get", response=mock_resp)

        mock_timeout = MagicMock()

        mock_settings = MagicMock()
        mock_settings.searxng_url = "http://searxng:8080"
        mock_settings.searxng_max_results = 5
        mock_settings.get_searxng_categories.return_value = ["general"]

        with patch.object(skill_module.aiohttp, "ClientSession", return_value=mock_session), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=mock_timeout), \
             patch("pillywiggins.config.Settings", return_value=mock_settings):
            result = await skill_module.run("test")

        assert result["results"] == []
        assert "500" in result["error"]

    @pytest.mark.asyncio
    async def test_custom_categories_override_env(self, skill_module):
        mock_resp = make_mock_aiohttp_response(status=200, json_data={"results": [], "query": "test"})

        call_args = {}

        mock_session = AsyncMock()

        def capture_get(url, params=None):
            call_args.update(params or {})
            return mock_resp

        mock_session.get = MagicMock(side_effect=capture_get)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_timeout = MagicMock()

        mock_settings = MagicMock()
        mock_settings.searxng_url = "http://searxng:8080"
        mock_settings.searxng_max_results = 5
        mock_settings.get_searxng_categories.return_value = ["general"]

        with patch.object(skill_module.aiohttp, "ClientSession", return_value=mock_session), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=mock_timeout), \
             patch("pillywiggins.config.Settings", return_value=mock_settings):
            await skill_module.run("test", categories="news,it")

        assert call_args.get("categories") == "news,it"

    @pytest.mark.asyncio
    async def test_custom_engines_passed(self, skill_module):
        mock_resp = make_mock_aiohttp_response(status=200, json_data={"results": [], "query": "test"})

        call_args = {}

        mock_session = AsyncMock()

        def capture_get(url, params=None):
            call_args.update(params or {})
            return mock_resp

        mock_session.get = MagicMock(side_effect=capture_get)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_timeout = MagicMock()

        mock_settings = MagicMock()
        mock_settings.searxng_url = "http://searxng:8080"
        mock_settings.searxng_max_results = 5
        mock_settings.get_searxng_categories.return_value = ["general"]

        with patch.object(skill_module.aiohttp, "ClientSession", return_value=mock_session), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=mock_timeout), \
             patch("pillywiggins.config.Settings", return_value=mock_settings):
            await skill_module.run("test", engines="google,duckduckgo")

        assert call_args.get("engines") == "google,duckduckgo"

    @pytest.mark.asyncio
    async def test_max_results_limits_output(self, skill_module):
        lots = [
            {"title": f"Result {i}", "url": f"https://example.com/{i}", "content": f"desc {i}", "engine": "google"}
            for i in range(20)
        ]
        mock_resp = make_mock_aiohttp_response(status=200, json_data={"results": lots, "query": "test"})
        mock_session = make_mock_aiohttp_session(method="get", response=mock_resp)

        mock_timeout = MagicMock()

        mock_settings = MagicMock()
        mock_settings.searxng_url = "http://searxng:8080"
        mock_settings.searxng_max_results = 5
        mock_settings.get_searxng_categories.return_value = ["general"]

        with patch.object(skill_module.aiohttp, "ClientSession", return_value=mock_session), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=mock_timeout), \
             patch("pillywiggins.config.Settings", return_value=mock_settings):
            result = await skill_module.run("test")

        assert len(result["results"]) == 5
        assert result["total_available"] == 20


class MockConnectionError(Exception):
    pass


class TestSearXNGConfig:
    def test_default_url(self):
        from pillywiggins.config import Settings

        s = Settings(searxng_url="http://searxng:8080")
        assert s.searxng_url == "http://searxng:8080"

    def test_default_categories(self):
        from pillywiggins.config import Settings

        s = Settings()
        assert s.get_searxng_categories() == ["general"]

    def test_all_categories(self):
        from pillywiggins.config import Settings

        s = Settings(searxng_categories="all")
        assert s.get_searxng_categories() == []

    def test_custom_categories(self):
        from pillywiggins.config import Settings

        s = Settings(searxng_categories="news,it,science")
        assert s.get_searxng_categories() == ["news", "it", "science"]

    def test_default_max_results(self):
        from pillywiggins.config import Settings

        s = Settings()
        assert s.searxng_max_results == 5