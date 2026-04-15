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
        "skills/check_website.py",
        skills_dir / "check_website.py",
    )
    spec = importlib.util.spec_from_file_location(
        "check_website",
        str(skills_dir / "check_website.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCheckWebsiteMeta:
    def test_meta_has_name(self, skill_module):
        assert skill_module.SKILL_META["name"] == "check_website"

    def test_meta_has_description(self, skill_module):
        assert "reachable" in skill_module.SKILL_META["description"].lower()

    def test_meta_parameters_url(self, skill_module):
        assert "url" in skill_module.SKILL_META["parameters"]

    def test_meta_parameters_timeout(self, skill_module):
        assert "timeout" in skill_module.SKILL_META["parameters"]

    def test_meta_returns_includes_body(self, skill_module):
        assert "body" in skill_module.SKILL_META["returns"]

    def test_meta_permissions_network(self, skill_module):
        assert skill_module.SKILL_META["permissions"]["network"] is True


class TestCheckWebsiteRun:
    @pytest.mark.asyncio
    async def test_returns_body_on_success(self, skill_module):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="<html>Hello</html>")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_client_timeout = MagicMock()

        with patch.object(skill_module.aiohttp, "ClientSession", return_value=mock_session), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=mock_client_timeout):
            result = await skill_module.run("https://example.com")

        assert result["reachable"] is True
        assert result["status_code"] == 200
        assert result["body"] == "<html>Hello</html>"
        assert "response_time_ms" in result

    @pytest.mark.asyncio
    async def test_returns_unreachable_on_error(self, skill_module):
        mock_client_timeout = MagicMock()
        with patch.object(skill_module.aiohttp, "ClientSession", side_effect=Exception("connection refused")), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=mock_client_timeout):
            result = await skill_module.run("https://down.example.com")

        assert result["reachable"] is False
        assert result["status_code"] is None
        assert "connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_truncates_large_body(self, skill_module):
        large_body = "x" * 60000
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value=large_body)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_client_timeout = MagicMock()

        with patch.object(skill_module.aiohttp, "ClientSession", return_value=mock_session), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=mock_client_timeout):
            result = await skill_module.run("https://example.com")

        assert result["reachable"] is True
        assert len(result["body"]) < 60000
        assert "truncated" in result["body"]

    @pytest.mark.asyncio
    async def test_does_not_truncate_small_body(self, skill_module):
        small_body = "<html>small</html>"
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value=small_body)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_client_timeout = MagicMock()

        with patch.object(skill_module.aiohttp, "ClientSession", return_value=mock_session), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=mock_client_timeout):
            result = await skill_module.run("https://example.com")

        assert result["body"] == small_body
        assert "truncated" not in result["body"]

    @pytest.mark.asyncio
    async def test_custom_timeout_passed(self, skill_module):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="ok")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_client_timeout = MagicMock()

        with patch.object(skill_module.aiohttp, "ClientSession", return_value=mock_session), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=mock_client_timeout) as mock_timeout:
            await skill_module.run("https://example.com", timeout=5)

        mock_timeout.assert_called_once_with(total=5)

    @pytest.mark.asyncio
    async def test_returns_404_with_body(self, skill_module):
        mock_resp = AsyncMock()
        mock_resp.status = 404
        mock_resp.text = AsyncMock(return_value="<h1>Not Found</h1>")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_client_timeout = MagicMock()

        with patch.object(skill_module.aiohttp, "ClientSession", return_value=mock_session), \
             patch.object(skill_module.aiohttp, "ClientTimeout", return_value=mock_client_timeout):
            result = await skill_module.run("https://example.com/missing")

        assert result["reachable"] is True
        assert result["status_code"] == 404
        assert result["body"] == "<h1>Not Found</h1>"