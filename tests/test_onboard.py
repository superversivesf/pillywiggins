"""Comprehensive tests for pillywiggins.onboard module — core functions and main flow."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
import yaml

from pillywiggins.onboard import (
    discover_packs,
    discover_personalities,
    ensure_config_files,
    get_default_llm_config,
    get_first_agent_llm_config,
    load_existing_agents,
    load_yaml,
    read_text,
    save_yaml,
    validate_telegram_token,
    write_text,
    _host_url,
    agent_ids_in_use,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("docker_available"),
]

# ---------------------------------------------------------------------------
# Helpers: load_yaml / save_yaml / read_text / write_text
# ---------------------------------------------------------------------------


class TestLoadYaml:
    def test_load_valid_yaml(self, tmp_path):
        p = tmp_path / "test.yaml"
        p.write_text("key: value\nlist:\n  - a\n  - b\n")
        result = load_yaml(p)
        assert result == {"key": "value", "list": ["a", "b"]}

    def test_load_empty_file_returns_empty_dict(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("")
        result = load_yaml(p)
        assert result == {}

    def test_load_yaml_with_none_content(self, tmp_path):
        """yaml.safe_load of an empty or comment-only file returns None."""
        p = tmp_path / "comments.yaml"
        p.write_text("# just a comment\n")
        result = load_yaml(p)
        assert result == {}


class TestSaveYaml:
    def test_save_and_reload(self, tmp_path):
        p = tmp_path / "out.yaml"
        data = {"agents": [{"id": "puck", "channel": "telegram"}]}
        save_yaml(p, data)
        result = load_yaml(p)
        assert result == data

    def test_save_preserves_order(self, tmp_path):
        p = tmp_path / "ordered.yaml"
        data = {"z_key": 1, "a_key": 2, "m_key": 3}
        save_yaml(p, data)
        content = p.read_text()
        # sort_keys=False means insertion order is preserved
        lines = content.strip().splitlines()
        keys_in_file = [l.split(":")[0] for l in lines]
        assert keys_in_file == ["z_key", "a_key", "m_key"]


class TestReadText:
    def test_read_text_returns_content(self, tmp_path):
        p = tmp_path / "file.txt"
        p.write_text("hello world")
        assert read_text(p) == "hello world"


class TestWriteText:
    def test_write_text_creates_file(self, tmp_path):
        p = tmp_path / "out.txt"
        write_text(p, "hello")
        assert p.read_text() == "hello"

    def test_write_text_overwrites(self, tmp_path):
        p = tmp_path / "out.txt"
        p.write_text("old")
        write_text(p, "new")
        assert p.read_text() == "new"


class TestHostUrl:
    def test_translates_docker_host_to_localhost(self):
        assert _host_url("http://host.docker.internal:11434") == "http://localhost:11434"

    def test_leaves_localhost_unchanged(self):
        assert _host_url("http://localhost:11434") == "http://localhost:11434"

    def test_leaves_remote_urls_unchanged(self):
        assert _host_url("https://ollama.com/v1") == "https://ollama.com/v1"


class TestEnsureConfigFiles:
    def test_copies_agents_yaml_from_example(self, tmp_path):
        example = tmp_path / "agents.yaml.example"
        target = tmp_path / "agents.yaml"
        example.write_text("agents:\n- id: puck\n")
        with (
            patch("pillywiggins.onboard.AGENTS_YAML", target),
            patch("pillywiggins.onboard.AGENTS_YAML_EXAMPLE", example),
            patch("pillywiggins.onboard.DOCKER_COMPOSE", tmp_path / "dc.yaml"),
            patch("pillywiggins.onboard.DOCKER_COMPOSE_EXAMPLE", tmp_path / "dc.yaml.example"),
            patch("pillywiggins.onboard.ENV_FILE", tmp_path / ".env"),
            patch("pillywiggins.onboard.ENV_EXAMPLE", tmp_path / "env.example"),
        ):
            (tmp_path / "dc.yaml.example").write_text("services: {}")
            (tmp_path / "env.example").write_text("KEY=val\n")
            ensure_config_files()
        assert target.exists()
        assert target.read_text() == "agents:\n- id: puck\n"

    def test_does_not_overwrite_existing(self, tmp_path):
        target = tmp_path / "agents.yaml"
        target.write_text("agents: []\n")
        example = tmp_path / "agents.yaml.example"
        example.write_text("agents:\n- id: puck\n")
        with (
            patch("pillywiggins.onboard.AGENTS_YAML", target),
            patch("pillywiggins.onboard.AGENTS_YAML_EXAMPLE", example),
            patch("pillywiggins.onboard.DOCKER_COMPOSE", tmp_path / "dc.yaml"),
            patch("pillywiggins.onboard.DOCKER_COMPOSE_EXAMPLE", tmp_path / "dc.yaml.example"),
            patch("pillywiggins.onboard.ENV_FILE", tmp_path / ".env"),
            patch("pillywiggins.onboard.ENV_EXAMPLE", tmp_path / "env.example"),
        ):
            (tmp_path / "dc.yaml.example").write_text("services: {}")
            (tmp_path / "env.example").write_text("KEY=val\n")
            ensure_config_files()
        assert target.read_text() == "agents: []\n"

    def test_copies_docker_compose_from_example(self, tmp_path):
        example = tmp_path / "docker-compose.yaml.example"
        example.write_text("services:\n  postgres: {}\n")
        target = tmp_path / "docker-compose.yaml"
        with (
            patch("pillywiggins.onboard.AGENTS_YAML", tmp_path / "agents.yaml"),
            patch("pillywiggins.onboard.AGENTS_YAML_EXAMPLE", tmp_path / "agents.yaml.example"),
            patch("pillywiggins.onboard.DOCKER_COMPOSE", target),
            patch("pillywiggins.onboard.DOCKER_COMPOSE_EXAMPLE", example),
            patch("pillywiggins.onboard.ENV_FILE", tmp_path / ".env"),
            patch("pillywiggins.onboard.ENV_EXAMPLE", tmp_path / "env.example"),
        ):
            (tmp_path / "agents.yaml.example").write_text("agents: []\n")
            (tmp_path / "env.example").write_text("KEY=val\n")
            ensure_config_files()
        assert target.exists()

    def test_copies_env_from_example(self, tmp_path):
        example = tmp_path / "env.example"
        example.write_text("KEY=val\n")
        target = tmp_path / ".env"
        with (
            patch("pillywiggins.onboard.AGENTS_YAML", tmp_path / "agents.yaml"),
            patch("pillywiggins.onboard.AGENTS_YAML_EXAMPLE", tmp_path / "agents.yaml.example"),
            patch("pillywiggins.onboard.DOCKER_COMPOSE", tmp_path / "dc.yaml"),
            patch("pillywiggins.onboard.DOCKER_COMPOSE_EXAMPLE", tmp_path / "dc.yaml.example"),
            patch("pillywiggins.onboard.ENV_FILE", target),
            patch("pillywiggins.onboard.ENV_EXAMPLE", example),
        ):
            (tmp_path / "agents.yaml.example").write_text("agents: []\n")
            (tmp_path / "dc.yaml.example").write_text("services: {}")
            ensure_config_files()
        assert target.exists()
        assert target.read_text() == "KEY=val\n"


# ---------------------------------------------------------------------------
# discover_personalities
# ---------------------------------------------------------------------------


class TestDiscoverPersonalities:
    def test_returns_empty_when_dir_missing(self):
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", Path("/nonexistent")):
            result = discover_personalities()
            assert result == []

    def test_returns_empty_when_dir_empty(self, tmp_path):
        empty_dir = tmp_path / "personalities"
        empty_dir.mkdir()
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", empty_dir):
            result = discover_personalities()
            assert result == []

    def test_discovers_yaml_files(self, tmp_path):
        pdir = tmp_path / "personalities"
        pdir.mkdir()
        (pdir / "puck.yaml").write_text(
            yaml.dump(
                {
                    "name": "Puck",
                    "description": "A mischievous fairy",
                    "channel": "telegram",
                    "bot_chat_limit": 5,
                }
            )
        )
        (pdir / "ember.yaml").write_text(
            yaml.dump(
                {
                    "name": "Ember",
                    "description": "A fiery spirit",
                    "channel": "discord",
                }
            )
        )
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_personalities()
        assert len(result) == 2
        # Sorted by filename
        assert result[0]["name"] == "Ember"
        assert result[1]["name"] == "Puck"

    def test_includes_filename_and_stem(self, tmp_path):
        pdir = tmp_path / "personalities"
        pdir.mkdir()
        (pdir / "puck.yaml").write_text(yaml.dump({"name": "Puck", "description": "test"}))
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_personalities()
        assert result[0]["filename"] == "puck.yaml"
        assert result[0]["stem"] == "puck"
        assert result[0]["pack"] is None

    def test_defaults_channel_to_telegram(self, tmp_path):
        pdir = tmp_path / "personalities"
        pdir.mkdir()
        (pdir / "agent.yaml").write_text(yaml.dump({"name": "Agent", "description": "no channel"}))
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_personalities()
        assert result[0]["channel"] == "telegram"

    def test_defaults_bot_chat_limit_to_3(self, tmp_path):
        pdir = tmp_path / "personalities"
        pdir.mkdir()
        (pdir / "agent.yaml").write_text(yaml.dump({"name": "Agent", "description": "no limit"}))
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_personalities()
        assert result[0]["bot_chat_limit"] == 3

    def test_skips_yaml_without_name(self, tmp_path):
        pdir = tmp_path / "personalities"
        pdir.mkdir()
        (pdir / "noname.yaml").write_text(yaml.dump({"description": "no name"}))
        (pdir / "good.yaml").write_text(yaml.dump({"name": "Good"}))
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_personalities()
        assert len(result) == 1
        assert result[0]["name"] == "Good"

    def test_skips_non_yaml_files(self, tmp_path):
        pdir = tmp_path / "personalities"
        pdir.mkdir()
        (pdir / "puck.yaml").write_text(yaml.dump({"name": "Puck"}))
        (pdir / "notes.txt").write_text("not a personality")
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_personalities()
        assert len(result) == 1

    def test_skips_empty_yaml(self, tmp_path):
        pdir = tmp_path / "personalities"
        pdir.mkdir()
        (pdir / "empty.yaml").write_text("")
        (pdir / "good.yaml").write_text(yaml.dump({"name": "Good"}))
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_personalities()
        assert len(result) == 1

    def test_discovers_personalities_in_subdirectories(self, tmp_path):
        pdir = tmp_path / "personalities"
        pack_dir = pdir / "fey_court"
        pack_dir.mkdir(parents=True)
        (pack_dir / "puck.yaml").write_text(
            yaml.dump({"name": "Puck", "description": "A fairy", "channel": "telegram"})
        )
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_personalities()
        assert len(result) == 1
        assert result[0]["name"] == "Puck"
        assert result[0]["filename"] == "fey_court/puck.yaml"
        assert result[0]["pack"] == "fey_court"

    def test_discovers_flat_and_nested_personalities(self, tmp_path):
        pdir = tmp_path / "personalities"
        pdir.mkdir()
        pack_dir = pdir / "workshop"
        pack_dir.mkdir()
        (pdir / "standalone.yaml").write_text(yaml.dump({"name": "Standalone", "description": "top level"}))
        (pack_dir / "foreman.yaml").write_text(yaml.dump({"name": "Foreman", "description": "workshop"}))
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_personalities()
        assert len(result) == 2
        standalone = [r for r in result if r["name"] == "Standalone"][0]
        foreman = [r for r in result if r["name"] == "Foreman"][0]
        assert standalone["pack"] is None
        assert standalone["filename"] == "standalone.yaml"
        assert foreman["pack"] == "workshop"
        assert foreman["filename"] == "workshop/foreman.yaml"

    def test_skips_pack_yaml_in_subdirectories(self, tmp_path):
        pdir = tmp_path / "personalities"
        pack_dir = pdir / "fey_court"
        pack_dir.mkdir(parents=True)
        (pack_dir / "pack.yaml").write_text(yaml.dump({"name": "The Fey Court", "description": "test"}))
        (pack_dir / "puck.yaml").write_text(yaml.dump({"name": "Puck", "description": "fairy"}))
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_personalities()
        assert len(result) == 1
        assert result[0]["name"] == "Puck"


class TestDiscoverPacks:
    def test_returns_empty_when_dir_missing(self):
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", Path("/nonexistent")):
            result = discover_packs()
            assert result == []

    def test_returns_empty_when_no_subdirectories(self, tmp_path):
        pdir = tmp_path / "personalities"
        pdir.mkdir()
        (pdir / "puck.yaml").write_text(yaml.dump({"name": "Puck"}))
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_packs()
            assert result == []

    def test_discovers_packs_with_manifest(self, tmp_path):
        pdir = tmp_path / "personalities"
        pack_dir = pdir / "fey_court"
        pack_dir.mkdir(parents=True)
        (pack_dir / "pack.yaml").write_text(
            yaml.dump({"name": "The Fey Court", "description": "A council of fae", "category": "whimsical"})
        )
        (pack_dir / "puck.yaml").write_text(yaml.dump({"name": "Puck"}))
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_packs()
        assert len(result) == 1
        assert result[0]["name"] == "The Fey Court"
        assert result[0]["description"] == "A council of fae"
        assert result[0]["category"] == "whimsical"
        assert result[0]["path"] == "fey_court"
        assert result[0]["personality_count"] == 1

    def test_discovers_packs_without_manifest(self, tmp_path):
        pdir = tmp_path / "personalities"
        pack_dir = pdir / "my_pack"
        pack_dir.mkdir(parents=True)
        (pack_dir / "agent.yaml").write_text(yaml.dump({"name": "Agent"}))
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_packs()
        assert len(result) == 1
        assert result[0]["name"] == "My Pack"
        assert result[0]["personality_count"] == 1

    def test_skips_empty_directories(self, tmp_path):
        pdir = tmp_path / "personalities"
        pack_dir = pdir / "empty_pack"
        pack_dir.mkdir(parents=True)
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_packs()
            assert result == []

    def test_skips_underscore_prefixed_directories(self, tmp_path):
        pdir = tmp_path / "personalities"
        defaults_dir = pdir / "_defaults"
        defaults_dir.mkdir(parents=True)
        (defaults_dir / "telegram.yaml").write_text(yaml.dump({"name": "Robin"}))
        with patch("pillywiggins.onboard.PERSONALITIES_DIR", pdir):
            result = discover_packs()
            assert result == []


# ---------------------------------------------------------------------------
# load_existing_agents
# ---------------------------------------------------------------------------


class TestLoadExistingAgents:
    def test_returns_empty_when_file_missing(self):
        with patch("pillywiggins.onboard.AGENTS_YAML", Path("/nonexistent")):
            result = load_existing_agents()
            assert result == []

    def test_returns_agents_list(self, tmp_path):
        p = tmp_path / "agents.yaml"
        p.write_text(
            yaml.dump(
                {
                    "agents": [
                        {"id": "puck", "channel": "telegram"},
                        {"id": "ember", "channel": "discord"},
                    ]
                }
            )
        )
        with patch("pillywiggins.onboard.AGENTS_YAML", p):
            result = load_existing_agents()
        assert len(result) == 2
        assert result[0]["id"] == "puck"
        assert result[1]["id"] == "ember"

    def test_returns_empty_when_no_agents_key(self, tmp_path):
        p = tmp_path / "agents.yaml"
        p.write_text(yaml.dump({"other_key": "value"}))
        with patch("pillywiggins.onboard.AGENTS_YAML", p):
            result = load_existing_agents()
        assert result == []

    def test_returns_empty_when_agents_list_empty(self, tmp_path):
        p = tmp_path / "agents.yaml"
        p.write_text(yaml.dump({"agents": []}))
        with patch("pillywiggins.onboard.AGENTS_YAML", p):
            result = load_existing_agents()
        assert result == []


# ---------------------------------------------------------------------------
# agent_ids_in_use
# ---------------------------------------------------------------------------


class TestAgentIdsInUse:
    def test_returns_set_of_ids(self, tmp_path):
        p = tmp_path / "agents.yaml"
        p.write_text(yaml.dump({"agents": [{"id": "puck"}, {"id": "ember"}, {"id": "sage"}]}))
        with patch("pillywiggins.onboard.AGENTS_YAML", p):
            result = agent_ids_in_use()
        assert result == {"puck", "ember", "sage"}

    def test_returns_empty_set_when_no_agents(self):
        with patch("pillywiggins.onboard.AGENTS_YAML", Path("/nonexistent")):
            result = agent_ids_in_use()
        assert result == set()


# ---------------------------------------------------------------------------
# validate_telegram_token
# ---------------------------------------------------------------------------


class TestValidateTelegramToken:
    @pytest.mark.asyncio
    async def test_valid_token_returns_true(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"ok": True, "result": {"username": "testbot"}})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("pillywiggins.onboard.aiohttp.ClientSession", return_value=mock_session):
            valid, info = await validate_telegram_token("123456:ABC-DEF")

        assert valid is True
        assert info == "testbot"

    @pytest.mark.asyncio
    async def test_non_200_returns_false(self):
        mock_resp = AsyncMock()
        mock_resp.status = 401
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("pillywiggins.onboard.aiohttp.ClientSession", return_value=mock_session):
            valid, info = await validate_telegram_token("bad-token")

        assert valid is False
        assert "HTTP 401" in info

    @pytest.mark.asyncio
    async def test_ok_false_returns_description(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"ok": False, "description": "Token is invalid"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("pillywiggins.onboard.aiohttp.ClientSession", return_value=mock_session):
            valid, info = await validate_telegram_token("bad-token")

        assert valid is False
        assert "Token is invalid" in info

    @pytest.mark.asyncio
    async def test_missing_username_returns_false(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"ok": True, "result": {}})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("pillywiggins.onboard.aiohttp.ClientSession", return_value=mock_session):
            valid, info = await validate_telegram_token("tok")

        assert valid is False
        assert "Missing result.username" in info

    @pytest.mark.asyncio
    async def test_invalid_json_returns_false(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(side_effect=Exception("bad json"))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("pillywiggins.onboard.aiohttp.ClientSession", return_value=mock_session):
            valid, info = await validate_telegram_token("tok")

        assert valid is False
        assert "Invalid JSON" in info

    @pytest.mark.asyncio
    async def test_connection_error_returns_false(self):
        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=aiohttp.ClientError("refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("pillywiggins.onboard.aiohttp.ClientSession", return_value=mock_session):
            valid, info = await validate_telegram_token("tok")

        assert valid is False
        assert "Connection error" in info

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self):
        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=TimeoutError("timed out"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("pillywiggins.onboard.aiohttp.ClientSession", return_value=mock_session):
            valid, info = await validate_telegram_token("tok")

        assert valid is False
        assert "timed out" in info.lower()

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_false(self):
        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=RuntimeError("unexpected"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("pillywiggins.onboard.aiohttp.ClientSession", return_value=mock_session):
            valid, info = await validate_telegram_token("tok")

        assert valid is False
        assert "Unexpected error" in info


# ---------------------------------------------------------------------------
# get_default_llm_config
# ---------------------------------------------------------------------------


class TestGetDefaultLlmConfig:
    def test_returns_empty_values_when_no_env_file(self):
        with patch("pillywiggins.onboard.Path") as mock_path_cls:
            # Make Path(".env") return a non-existent path
            mock_env = MagicMock()
            mock_env.is_file.return_value = False
            mock_path_cls.return_value = mock_env
            result = get_default_llm_config()
        for key in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME"):
            assert result[key] == ""

    def test_reads_llm_vars_from_env(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "LLM_PROVIDER=ollama\n"
            "LLM_BASE_URL=http://host.docker.internal:11434\n"
            "LLM_API_KEY=\n"
            "MODEL_NAME=qwen3.5:8b\n"
            "SOME_OTHER_VAR=ignore\n"
        )
        with patch("pillywiggins.onboard.Path") as mock_path_cls:
            mock_env = MagicMock()
            mock_env.is_file.return_value = True
            mock_env.read_text.return_value = env_file.read_text()
            mock_path_cls.return_value = mock_env
            result = get_default_llm_config()
        assert result["LLM_PROVIDER"] == "ollama"
        assert result["LLM_BASE_URL"] == "http://host.docker.internal:11434"
        assert result["MODEL_NAME"] == "qwen3.5:8b"
        assert result["LLM_API_KEY"] == ""  # empty value preserved as empty
        assert "SOME_OTHER_VAR" not in result

    def test_skips_comments_and_blank_lines(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\n\nLLM_PROVIDER=openai\n# LLM_BASE_URL=skipped\n")
        with patch("pillywiggins.onboard.Path") as mock_path_cls:
            mock_env = MagicMock()
            mock_env.is_file.return_value = True
            mock_env.read_text.return_value = env_file.read_text()
            mock_path_cls.return_value = mock_env
            result = get_default_llm_config()
        assert result["LLM_PROVIDER"] == "openai"
        assert result["LLM_BASE_URL"] == ""  # commented line skipped

    def test_strips_whitespace_from_key_and_value(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(" LLM_PROVIDER = ollama \n")
        with patch("pillywiggins.onboard.Path") as mock_path_cls:
            mock_env = MagicMock()
            mock_env.is_file.return_value = True
            mock_env.read_text.return_value = env_file.read_text()
            mock_path_cls.return_value = mock_env
            result = get_default_llm_config()
        assert result["LLM_PROVIDER"] == "ollama"


class TestGetDefaultLlmConfigEdgeCases:
    def test_read_text_exception(self):
        mock_env = MagicMock()
        mock_env.is_file.return_value = True
        mock_env.read_text.side_effect = PermissionError("no access")
        with patch("pillywiggins.onboard.Path", return_value=mock_env):
            result = get_default_llm_config()
        for key in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME"):
            assert result[key] == ""

    def test_line_without_equals_sign(self):
        env_file = MagicMock()
        env_file.is_file.return_value = True
        env_file.read_text.return_value = "LLM_PROVIDER=ollama\nNO_EQUALS_HERE\nMODEL_NAME=qwen\n"
        with patch("pillywiggins.onboard.Path", return_value=env_file):
            result = get_default_llm_config()
        assert result["LLM_PROVIDER"] == "ollama"
        assert result["MODEL_NAME"] == "qwen"


# ---------------------------------------------------------------------------
# get_first_agent_llm_config
# ---------------------------------------------------------------------------


class TestGetFirstAgentLlmConfig:
    def test_returns_none_when_no_agents(self):
        with patch("pillywiggins.onboard.AGENTS_YAML", Path("/nonexistent")):
            result = get_first_agent_llm_config()
        assert result is None

    def test_returns_none_when_first_agent_has_no_env(self, tmp_path):
        p = tmp_path / "agents.yaml"
        p.write_text(yaml.dump({"agents": [{"id": "puck"}]}))
        with patch("pillywiggins.onboard.AGENTS_YAML", p):
            result = get_first_agent_llm_config()
        assert result is None

    def test_returns_llm_config_from_first_agent(self, tmp_path):
        p = tmp_path / "agents.yaml"
        p.write_text(
            yaml.dump(
                {
                    "agents": [
                        {
                            "id": "puck",
                            "environment": {
                                "LLM_PROVIDER": "ollama",
                                "LLM_BASE_URL": "http://localhost:11434",
                                "MODEL_NAME": "qwen3.5:8b",
                            },
                        }
                    ]
                }
            )
        )
        with patch("pillywiggins.onboard.AGENTS_YAML", p):
            result = get_first_agent_llm_config()
        assert result == {
            "LLM_PROVIDER": "ollama",
            "LLM_BASE_URL": "http://localhost:11434",
            "MODEL_NAME": "qwen3.5:8b",
        }

    def test_only_includes_llm_env_keys(self, tmp_path):
        p = tmp_path / "agents.yaml"
        p.write_text(
            yaml.dump(
                {
                    "agents": [
                        {
                            "id": "puck",
                            "environment": {
                                "LLM_PROVIDER": "ollama",
                                "TELEGRAM_BOT_TOKEN": "${PUCK_TELEGRAM_TOKEN}",
                                "OTHER_VAR": "ignore",
                            },
                        }
                    ]
                }
            )
        )
        with patch("pillywiggins.onboard.AGENTS_YAML", p):
            result = get_first_agent_llm_config()
        assert "TELEGRAM_BOT_TOKEN" not in result
        assert "OTHER_VAR" not in result
        assert result["LLM_PROVIDER"] == "ollama"


# ---------------------------------------------------------------------------
# Main onboard menu
# ---------------------------------------------------------------------------


class TestOnboard:
    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.questionary")
    async def test_exit(self, mock_q):
        mock_q.select.return_value.ask_async = AsyncMock(return_value="\U0001f44b Exit")
        with patch("pillywiggins.onboard.ensure_config_files"):
            from pillywiggins.onboard import onboard

            await onboard()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard._add_agent_flow", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_add_agent_menu(self, mock_q, mock_add):
        responses = iter(["✨ Add agent", "\U0001f44b Exit"])
        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(responses))
            )
        )
        with patch("pillywiggins.onboard.ensure_config_files"):
            from pillywiggins.onboard import onboard

            await onboard()
            mock_add.assert_called_once()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard._reconfigure_agent_flow", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_reconfigure_menu(self, mock_q, mock_reconfig):
        responses = iter(["\U0001f527 Reconfigure agent", "\U0001f44b Exit"])
        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(responses))
            )
        )
        with patch("pillywiggins.onboard.ensure_config_files"):
            from pillywiggins.onboard import onboard

            await onboard()
            mock_reconfig.assert_called_once()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard._remove_agent_flow", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_remove_menu(self, mock_q, mock_remove):
        responses = iter(["\U0001f5d1️  Remove agent", "\U0001f44b Exit"])
        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(responses))
            )
        )
        with patch("pillywiggins.onboard.ensure_config_files"):
            from pillywiggins.onboard import onboard

            await onboard()
            mock_remove.assert_called_once()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard._start_restart_flow", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_start_restart_menu(self, mock_q, mock_start):
        responses = iter(["\U0001f680 Start/restart agents", "\U0001f44b Exit"])
        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(responses))
            )
        )
        with patch("pillywiggins.onboard.ensure_config_files"):
            from pillywiggins.onboard import onboard

            await onboard()
            mock_start.assert_called_once()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.questionary")
    async def test_cancel_returns_none_exits(self, mock_q):
        mock_q.select.return_value.ask_async = AsyncMock(return_value=None)
        with patch("pillywiggins.onboard.ensure_config_files"):
            from pillywiggins.onboard import onboard

            await onboard()