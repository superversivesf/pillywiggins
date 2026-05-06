"""Comprehensive tests for pillywiggins.onboard module."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
import yaml

from pillywiggins.onboard import (
    add_agent_to_agents_yaml,
    add_agent_to_configs,
    add_agent_to_docker_compose,
    add_brave_api_key_to_env,
    add_llm_api_key_to_env,
    add_token_to_env,
    agent_ids_in_use,
    comment_token_in_env,
    discover_packs,
    discover_personalities,
    ensure_config_files,
    get_default_llm_config,
    get_first_agent_llm_config,
    load_existing_agents,
    load_yaml,
    read_text,
    remove_agent_from_agents_yaml,
    remove_agent_from_configs,
    remove_agent_from_docker_compose,
    save_yaml,
    validate_telegram_token,
    write_text,
    _host_url,
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
# add_agent_to_agents_yaml
# ---------------------------------------------------------------------------


class TestAddAgentToAgentsYaml:
    def test_creates_file_if_missing(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            add_agent_to_agents_yaml(
                agent_id="puck",
                personality_filename="puck.yaml",
                channel="telegram",
                token_env="PUCK_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=None,
            )
        data = yaml.safe_load(config_path.read_text())
        assert len(data["agents"]) == 1
        assert data["agents"][0]["id"] == "puck"

    def test_appends_to_existing(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        config_path.write_text(
            yaml.dump({"agents": [{"id": "puck", "personality": "/config/puck.yaml"}]})
        )
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            add_agent_to_agents_yaml(
                agent_id="ember",
                personality_filename="ember.yaml",
                channel="telegram",
                token_env="EMBER_TELEGRAM_TOKEN",
                allowed_user_ids="123,456",
                bot_chat_limit=5,
                llm_config=None,
            )
        data = yaml.safe_load(config_path.read_text())
        assert len(data["agents"]) == 2
        assert data["agents"][1]["id"] == "ember"

    def test_skips_duplicate_agent_id(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        config_path.write_text(
            yaml.dump({"agents": [{"id": "puck", "personality": "/config/puck.yaml"}]})
        )
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            add_agent_to_agents_yaml(
                agent_id="puck",
                personality_filename="puck.yaml",
                channel="telegram",
                token_env="PUCK_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=None,
            )
        data = yaml.safe_load(config_path.read_text())
        assert len(data["agents"]) == 1  # Not duplicated

    def test_sets_personality_path_from_filename(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            add_agent_to_agents_yaml(
                agent_id="ember",
                personality_filename="ember.yaml",
                channel="telegram",
                token_env="EMBER_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=None,
            )
        data = yaml.safe_load(config_path.read_text())
        assert data["agents"][0]["personality"] == "/config/ember.yaml"

    def test_sets_personality_path_with_subdirectory(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            add_agent_to_agents_yaml(
                agent_id="puck",
                personality_filename="fey_court/puck.yaml",
                channel="telegram",
                token_env="PUCK_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=None,
            )
        data = yaml.safe_load(config_path.read_text())
        assert data["agents"][0]["personality"] == "/config/fey_court/puck.yaml"

    def test_sets_token_env_reference(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            add_agent_to_agents_yaml(
                agent_id="ember",
                personality_filename="ember.yaml",
                channel="telegram",
                token_env="EMBER_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=None,
            )
        data = yaml.safe_load(config_path.read_text())
        assert data["agents"][0]["environment"]["TELEGRAM_BOT_TOKEN"] == "${EMBER_TELEGRAM_TOKEN}"

    def test_includes_llm_config_when_provided(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        llm_config = {
            "LLM_PROVIDER": "openai",
            "LLM_BASE_URL": "https://api.openai.com/v1",
            "LLM_API_KEY": "sk-test123",
            "MODEL_NAME": "gpt-4",
        }
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            add_agent_to_agents_yaml(
                agent_id="sage",
                personality_filename="sage.yaml",
                channel="telegram",
                token_env="SAGE_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=llm_config,
            )
        data = yaml.safe_load(config_path.read_text())
        env = data["agents"][0]["environment"]
        assert env["LLM_PROVIDER"] == "openai"
        assert env["LLM_BASE_URL"] == "https://api.openai.com/v1"
        assert env["MODEL_NAME"] == "gpt-4"
        # API key uses per-agent env var reference
        assert env["LLM_API_KEY"] == "${SAGE_LLM_API_KEY}"

    def test_partial_llm_config_only_writes_present_keys(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        llm_config = {"LLM_PROVIDER": "ollama"}
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            add_agent_to_agents_yaml(
                agent_id="puck",
                personality_filename="puck.yaml",
                channel="telegram",
                token_env="PUCK_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=llm_config,
            )
        data = yaml.safe_load(config_path.read_text())
        env = data["agents"][0]["environment"]
        assert env["LLM_PROVIDER"] == "ollama"
        assert "LLM_BASE_URL" not in env
        assert "LLM_API_KEY" not in env
        assert "MODEL_NAME" not in env

    def test_handles_missing_agents_key_in_yaml(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        config_path.write_text(yaml.dump({"other_data": True}))
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            add_agent_to_agents_yaml(
                agent_id="newagent",
                personality_filename="newagent.yaml",
                channel="telegram",
                token_env="NEWAGENT_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=None,
            )
        data = yaml.safe_load(config_path.read_text())
        assert len(data["agents"]) == 1
        assert data["agents"][0]["id"] == "newagent"


# ---------------------------------------------------------------------------
# add_agent_to_docker_compose
# ---------------------------------------------------------------------------


class TestAddAgentToDockerCompose:
    def test_creates_file_if_missing(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )
        data = yaml.safe_load(compose_path.read_text())
        assert "puck" in data["services"]

    def test_adds_service_entry(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )
        data = yaml.safe_load(compose_path.read_text())
        svc = data["services"]["puck"]
        assert svc["command"] == "python -m pillywiggins --agent-id puck"
        assert svc["build"] == "."
        assert svc["env_file"] == ".env"

    def test_sets_environment(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )
        data = yaml.safe_load(compose_path.read_text())
        svc_env = data["services"]["puck"]["environment"]
        assert svc_env["AGENT_ID"] == "puck"
        assert svc_env["TELEGRAM_BOT_TOKEN"] == "${PUCK_TELEGRAM_TOKEN}"
        assert svc_env["PERSONALITY_FILE"] == "/config/puck.yaml"

    def test_sets_depends_on_and_volumes(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )
        data = yaml.safe_load(compose_path.read_text())
        svc = data["services"]["puck"]
        assert "postgres" in svc["depends_on"]
        assert "redis" in svc["depends_on"]
        assert isinstance(svc["volumes"], list)
        assert len(svc["volumes"]) > 0

    def test_skips_duplicate_service(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {"puck": {"build": "."}}, "volumes": {}}))
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )
        data = yaml.safe_load(compose_path.read_text())
        # Service should still be the original (not overwritten)
        assert data["services"]["puck"]["build"] == "."

    def test_includes_llm_config_in_environment(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))
        llm_config = {
            "LLM_PROVIDER": "openai",
            "LLM_BASE_URL": "https://api.openai.com/v1",
            "LLM_API_KEY": "sk-test",
            "MODEL_NAME": "gpt-4",
        }
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="sage",
                personality_filename="sage.yaml",
                token_env="SAGE_TELEGRAM_TOKEN",
                llm_config=llm_config,
            )
        data = yaml.safe_load(compose_path.read_text())
        svc_env = data["services"]["sage"]["environment"]
        assert svc_env["LLM_PROVIDER"] == "openai"
        assert svc_env["LLM_BASE_URL"] == "https://api.openai.com/v1"
        assert svc_env["MODEL_NAME"] == "gpt-4"
        assert svc_env["LLM_API_KEY"] == "${SAGE_LLM_API_KEY}"

    def test_ensures_named_volumes(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )
        data = yaml.safe_load(compose_path.read_text())
        for vol in ["pgdata", "redisdata", "searxng_data"]:
            assert vol in data["volumes"]
        # skills uses a bind mount (./skills:/app/skills), not a named volume


# ---------------------------------------------------------------------------
# add_token_to_env
# ---------------------------------------------------------------------------


class TestAddTokenToEnv:
    def test_creates_env_file_if_missing(self, tmp_path):
        env_path = tmp_path / ".env"
        add_token_to_env("puck", "12345:abcd", env_path)
        content = env_path.read_text()
        assert "PUCK_TELEGRAM_TOKEN=12345:abcd" in content

    def test_appends_to_existing_env(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("# --- Telegram Bot Tokens ---\nOLD_TOKEN=value\n")
        add_token_to_env("puck", "12345:abcd", env_path)
        content = env_path.read_text()
        assert "PUCK_TELEGRAM_TOKEN=12345:abcd" in content
        assert "OLD_TOKEN=value" in content

    def test_updates_existing_token(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("PUCK_TELEGRAM_TOKEN=old_value\n")
        add_token_to_env("puck", "new_value", env_path)
        content = env_path.read_text()
        assert "PUCK_TELEGRAM_TOKEN=new_value" in content
        assert "old_value" not in content

    def test_updates_commented_token(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("#PUCK_TELEGRAM_TOKEN=old_value\n")
        add_token_to_env("puck", "new_value", env_path)
        content = env_path.read_text()
        assert "PUCK_TELEGRAM_TOKEN=new_value" in content

    def test_inserts_after_telegram_section_header(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("# --- Agent Credentials ---\nEXISTING_TOKEN=x\n")
        add_token_to_env("puck", "12345:abcd", env_path)
        content = env_path.read_text()
        lines = content.split("\n")
        # New token should be inserted right after the header
        for i, line in enumerate(lines):
            if "Agent Credentials" in line:
                assert "PUCK_TELEGRAM_TOKEN" in lines[i + 1]
                break

    def test_inserts_after_existing_telegram_token(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("OTHER_TELEGRAM_TOKEN=xyz\n")
        add_token_to_env("puck", "12345:abcd", env_path)
        content = env_path.read_text()
        assert "PUCK_TELEGRAM_TOKEN=12345:abcd" in content

    def test_appends_at_end_if_no_section_found(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("SOME_VAR=value\n")
        add_token_to_env("puck", "12345:abcd", env_path)
        content = env_path.read_text()
        assert "PUCK_TELEGRAM_TOKEN=12345:abcd" in content
        assert "# --- Agent Credentials ---" in content


# ---------------------------------------------------------------------------
# add_llm_api_key_to_env
# ---------------------------------------------------------------------------


class TestAddLlmApiKeyToEnv:
    def test_skips_if_file_missing(self, tmp_path):
        env_path = tmp_path / ".env"
        # Doesn't exist — should not raise
        add_llm_api_key_to_env("sage", "sk-test", env_path)

    def test_updates_existing_key(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("SAGE_LLM_API_KEY=old-key\n")
        add_llm_api_key_to_env("sage", "sk-new-key", env_path)
        content = env_path.read_text()
        assert "SAGE_LLM_API_KEY=sk-new-key" in content
        assert "old-key" not in content

    def test_inserts_after_llm_provider_section(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("# --- LLM Provider ---\nLLM_PROVIDER=ollama\n")
        add_llm_api_key_to_env("sage", "sk-test", env_path)
        content = env_path.read_text()
        assert "SAGE_LLM_API_KEY=sk-test" in content

    def test_inserts_after_existing_llm_api_key(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("LLM_API_KEY=global-key\n")
        add_llm_api_key_to_env("sage", "sk-per-agent", env_path)
        content = env_path.read_text()
        assert "SAGE_LLM_API_KEY=sk-per-agent" in content

    def test_appends_with_section_header(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("UNRELATED=value\n")
        add_llm_api_key_to_env("sage", "sk-test", env_path)
        content = env_path.read_text()
        assert "SAGE_LLM_API_KEY=sk-test" in content
        assert "# --- Per-Agent LLM API Keys ---" in content


# ---------------------------------------------------------------------------
# add_brave_api_key_to_env
# ---------------------------------------------------------------------------


class TestAddBraveApiKeyToEnv:
    def test_skips_if_file_missing(self, tmp_path):
        env_path = tmp_path / ".env"
        from pillywiggins.onboard import add_brave_api_key_to_env
        # Doesn't exist — should not raise
        add_brave_api_key_to_env("brave-key", env_path)

    def test_updates_existing_key(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("BRAVE_API_KEY=old-key\n")
        from pillywiggins.onboard import add_brave_api_key_to_env
        add_brave_api_key_to_env("new-key", env_path)
        content = env_path.read_text()
        assert "BRAVE_API_KEY=new-key" in content
        assert "old-key" not in content

    def test_inserts_after_search_section(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("# --- Search Configuration ---\nSEARXNG_URL=http://searxng:8080\n")
        from pillywiggins.onboard import add_brave_api_key_to_env
        add_brave_api_key_to_env("brave-key", env_path)
        content = env_path.read_text()
        assert "BRAVE_API_KEY=brave-key" in content

    def test_appends_with_section_header(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("UNRELATED=value\n")
        from pillywiggins.onboard import add_brave_api_key_to_env
        add_brave_api_key_to_env("brave-key", env_path)
        content = env_path.read_text()
        assert "BRAVE_API_KEY=brave-key" in content
        assert "# --- Search Configuration ---" in content


# ---------------------------------------------------------------------------
# remove_agent_from_agents_yaml
# ---------------------------------------------------------------------------


class TestRemoveAgentFromAgentsYaml:
    def test_removes_agent(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "agents": [
                        {"id": "puck", "channel": "telegram"},
                        {"id": "ember", "channel": "discord"},
                    ]
                }
            )
        )
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            remove_agent_from_agents_yaml("puck")
        data = yaml.safe_load(config_path.read_text())
        assert len(data["agents"]) == 1
        assert data["agents"][0]["id"] == "ember"

    def test_noop_if_file_missing(self):
        with patch("pillywiggins.onboard.AGENTS_YAML", Path("/nonexistent")):
            # Should not raise
            remove_agent_from_agents_yaml("puck")

    def test_noop_if_agent_not_found(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        config_path.write_text(yaml.dump({"agents": [{"id": "puck"}]}))
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            remove_agent_from_agents_yaml("nonexistent")
        data = yaml.safe_load(config_path.read_text())
        assert len(data["agents"]) == 1

    def test_noop_if_no_agents_key(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        config_path.write_text(yaml.dump({"other_key": True}))
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            remove_agent_from_agents_yaml("puck")
        data = yaml.safe_load(config_path.read_text())
        assert "agents" not in data


# ---------------------------------------------------------------------------
# remove_agent_from_docker_compose
# ---------------------------------------------------------------------------


class TestRemoveAgentFromDockerCompose:
    def test_removes_service(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(
            yaml.dump(
                {
                    "services": {
                        "puck": {"build": "."},
                        "ember": {"build": "."},
                    },
                    "volumes": {},
                }
            )
        )
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            remove_agent_from_docker_compose("puck")
        data = yaml.safe_load(compose_path.read_text())
        assert "puck" not in data["services"]
        assert "ember" in data["services"]

    def test_noop_if_file_missing(self):
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", Path("/nonexistent")):
            remove_agent_from_docker_compose("puck")

    def test_noop_if_service_not_found(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {"ember": {"build": "."}}, "volumes": {}}))
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            remove_agent_from_docker_compose("nonexistent")
        data = yaml.safe_load(compose_path.read_text())
        assert "ember" in data["services"]

    def test_noop_if_no_services_key(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"volumes": {}}))
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            remove_agent_from_docker_compose("puck")


# ---------------------------------------------------------------------------
# comment_token_in_env
# ---------------------------------------------------------------------------


class TestCommentTokenInEnv:
    def test_comments_out_token(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("PUCK_TELEGRAM_TOKEN=12345:abcd\nOTHER_VAR=x\n")
        comment_token_in_env("puck", env_path)
        content = env_path.read_text()
        assert "#PUCK_TELEGRAM_TOKEN=12345:abcd" in content
        assert "OTHER_VAR=x" in content

    def test_noop_if_file_missing(self, tmp_path):
        env_path = tmp_path / ".env"
        # Should not raise
        comment_token_in_env("puck", env_path)

    def test_noop_if_token_not_found(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("OTHER_VAR=value\n")
        comment_token_in_env("puck", env_path)
        # File should be unchanged (no token to comment)
        content = env_path.read_text()
        assert content == "OTHER_VAR=value\n"

    def test_does_not_rewrite_if_no_changes(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("SOME_VAR=value\n")
        original = env_path.read_text()
        comment_token_in_env("nonexistent", env_path)
        # No token to comment, so file should not be rewritten
        # (the function only calls write_text if changed=True)


# ---------------------------------------------------------------------------
# remove_agent_from_configs (orchestrator)
# ---------------------------------------------------------------------------


class TestRemoveAgentFromConfigs:
    def test_calls_all_three_removal_functions(self):
        with (
            patch("pillywiggins.onboard.remove_agent_from_agents_yaml") as mock_yaml,
            patch("pillywiggins.onboard.remove_agent_from_docker_compose") as mock_compose,
            patch("pillywiggins.onboard.comment_token_in_env") as mock_env,
        ):
            remove_agent_from_configs("puck")
            mock_yaml.assert_called_once_with("puck")
            mock_compose.assert_called_once_with("puck")
            mock_env.assert_called_once_with("puck")


# ---------------------------------------------------------------------------
# add_agent_to_configs (orchestrator)
# ---------------------------------------------------------------------------


class TestAddAgentToConfigs:
    def test_calls_all_functions_with_token(self):
        llm_config = {
            "LLM_PROVIDER": "ollama",
            "LLM_API_KEY": "sk-test",
        }
        with (
            patch("pillywiggins.onboard.add_agent_to_agents_yaml") as mock_yaml,
            patch("pillywiggins.onboard.add_agent_to_docker_compose") as mock_compose,
            patch("pillywiggins.onboard.add_token_to_env") as mock_env,
            patch("pillywiggins.onboard.add_llm_api_key_to_env") as mock_llm_env,
        ):
            add_agent_to_configs(
                agent_id="puck",
                personality_filename="puck.yaml",
                channel="telegram",
                token_env="PUCK_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=llm_config,
                token_value="12345:abcd",
            )
            mock_yaml.assert_called_once()
            mock_compose.assert_called_once()
            mock_env.assert_called_once_with("puck", "12345:abcd", channel="telegram")
            mock_llm_env.assert_called_once_with("puck", "sk-test")

    def test_skips_token_when_empty(self):
        with (
            patch("pillywiggins.onboard.add_agent_to_agents_yaml"),
            patch("pillywiggins.onboard.add_agent_to_docker_compose"),
            patch("pillywiggins.onboard.add_token_to_env") as mock_env,
            patch("pillywiggins.onboard.add_llm_api_key_to_env"),
        ):
            add_agent_to_configs(
                agent_id="puck",
                personality_filename="puck.yaml",
                channel="telegram",
                token_env="PUCK_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=None,
                token_value="",
            )
            mock_env.assert_not_called()

    def test_skips_llm_api_key_when_not_in_config(self):
        llm_config = {"LLM_PROVIDER": "ollama"}
        with (
            patch("pillywiggins.onboard.add_agent_to_agents_yaml"),
            patch("pillywiggins.onboard.add_agent_to_docker_compose"),
            patch("pillywiggins.onboard.add_token_to_env"),
            patch("pillywiggins.onboard.add_llm_api_key_to_env") as mock_llm_env,
        ):
            add_agent_to_configs(
                agent_id="puck",
                personality_filename="puck.yaml",
                channel="telegram",
                token_env="PUCK_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=llm_config,
                token_value="12345:abcd",
            )
            mock_llm_env.assert_not_called()


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


class TestAddAgentFlow:
    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.add_agent_to_configs")
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_full_add_flow(self, mock_q, mock_list_models, mock_validate, mock_add_configs):
        mock_validate.return_value = (True, "testbot")
        mock_list_models.return_value = []

        select_responses = iter(
            [
                "__all__",  # pack choice
                "Puck — mischievous",
                "telegram",
                "ollama",
                "UTC",
            ]
        )
        text_responses = iter(
            [
                "puck",
                "123456:ABC-DEF1234",
                "",
                "http://host.docker.internal:11434/v1",
                "qwen3.5:8b",
                "all",
                "3",
            ]
        )
        confirm_responses = iter(
            [
                True,
                False,
            ]
        )

        def make_select(*args, **kwargs):
            m = MagicMock()
            m.ask_async = AsyncMock(return_value=next(select_responses))
            return m

        def make_text(*args, **kwargs):
            m = MagicMock()
            m.ask_async = AsyncMock(return_value=next(text_responses))
            return m

        def make_confirm(*args, **kwargs):
            m = MagicMock()
            m.ask_async = AsyncMock(return_value=next(confirm_responses))
            return m

        mock_q.select = MagicMock(side_effect=make_select)
        mock_q.text = MagicMock(side_effect=make_text)
        mock_q.confirm = MagicMock(side_effect=make_confirm)
        mock_q.Choice = MagicMock

        with (
            patch("pillywiggins.onboard.discover_personalities") as mock_disc,
            patch("pillywiggins.onboard.agent_ids_in_use", return_value=set()),
            patch("pillywiggins.onboard.get_first_agent_llm_config", return_value=None),
            patch(
                "pillywiggins.onboard.get_default_llm_config",
                return_value={
                    k: "" for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")
                },
            ),
            patch("pillywiggins.onboard.load_existing_agents", return_value=[]),
        ):
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                },
            ]
            from pillywiggins.onboard import _add_agent_flow

            await _add_agent_flow()

        mock_add_configs.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_personalities(self):
        with patch("pillywiggins.onboard.discover_personalities", return_value=[]):
            from pillywiggins.onboard import _add_agent_flow

            await _add_agent_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_cancel_at_personality(self, mock_q, mock_list_models, mock_validate):
        mock_q.select.return_value.ask_async = AsyncMock(return_value=None)
        with patch("pillywiggins.onboard.discover_personalities") as mock_disc:
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                },
            ]
            from pillywiggins.onboard import _add_agent_flow

            await _add_agent_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_cancel_at_channel(self, mock_q, mock_list_models, mock_validate):
        responses = iter(["Puck — mischievous", None])
        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(ask_async=AsyncMock(return_value="x"))
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(ask_async=AsyncMock(return_value=True))
        )
        mock_q.Choice = MagicMock
        with patch("pillywiggins.onboard.discover_personalities") as mock_disc:
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                },
            ]
            from pillywiggins.onboard import _add_agent_flow

            await _add_agent_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    @patch("pillywiggins.onboard.agent_ids_in_use", return_value={"puck"})
    @patch("pillywiggins.onboard.remove_agent_from_configs")
    async def test_overwrite_existing_agent(
        self, mock_remove, mock_ids, mock_q, mock_list_models, mock_validate
    ):
        mock_validate.return_value = (True, "testbot")
        mock_list_models.return_value = []

        select_responses = iter(["__all__", "Puck — mischievous", "telegram", "ollama", "UTC"])
        text_responses = iter(
            [
                "puck",
                "123456:ABC-DEF1234",
                "",
                "http://host.docker.internal:11434/v1",
                "qwen3.5:8b",
                "all",
                "3",
            ]
        )
        confirm_responses = iter([True, True, False])

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_responses))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_responses))
            )
        )
        mock_q.Choice = MagicMock

        with (
            patch("pillywiggins.onboard.discover_personalities") as mock_disc,
            patch("pillywiggins.onboard.add_agent_to_configs"),
            patch("pillywiggins.onboard.get_first_agent_llm_config", return_value=None),
            patch(
                "pillywiggins.onboard.get_default_llm_config",
                return_value={
                    k: "" for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")
                },
            ),
            patch("pillywiggins.onboard.load_existing_agents", return_value=[]),
        ):
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                },
            ]
            from pillywiggins.onboard import _add_agent_flow

            await _add_agent_flow()
            mock_remove.assert_called_once_with("puck")

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.add_agent_to_configs")
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_invalid_token_continue(
        self, mock_q, mock_list_models, mock_validate, mock_add_configs
    ):
        mock_validate.return_value = (False, "Invalid token")
        mock_list_models.return_value = []

        select_responses = iter(["__all__","Puck — mischievous", "telegram", "ollama", "UTC"])
        text_responses = iter(
            [
                "puck",
                "badtoken1234567890",
                "",
                "http://host.docker.internal:11434/v1",
                "qwen3.5:8b",
                "all",
                "3",
            ]
        )
        confirm_responses = iter([True, True, False])

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_responses))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_responses))
            )
        )
        mock_q.Choice = MagicMock

        with (
            patch("pillywiggins.onboard.discover_personalities") as mock_disc,
            patch("pillywiggins.onboard.agent_ids_in_use", return_value=set()),
            patch("pillywiggins.onboard.get_first_agent_llm_config", return_value=None),
            patch(
                "pillywiggins.onboard.get_default_llm_config",
                return_value={
                    k: "" for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")
                },
            ),
            patch("pillywiggins.onboard.load_existing_agents", return_value=[]),
        ):
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                },
            ]
            from pillywiggins.onboard import _add_agent_flow

            await _add_agent_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.add_agent_to_configs")
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_with_models_available(
        self, mock_q, mock_list_models, mock_validate, mock_add_configs
    ):
        from pillywiggins.adapters.models import ModelInfo

        mock_validate.return_value = (True, "testbot")
        mock_list_models.return_value = [ModelInfo(id="qwen3.5:8b"), ModelInfo(id="llama3:8b")]

        select_responses = iter(["__all__","Puck — mischievous", "telegram", "ollama", "qwen3.5:8b", "UTC"])
        text_responses = iter(
            ["puck", "123456:ABC-DEF1234", "", "http://host.docker.internal:11434/v1", "all", "3"]
        )
        confirm_responses = iter([True, False])

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_responses))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_responses))
            )
        )
        mock_q.Choice = MagicMock

        with (
            patch("pillywiggins.onboard.discover_personalities") as mock_disc,
            patch("pillywiggins.onboard.agent_ids_in_use", return_value=set()),
            patch("pillywiggins.onboard.get_first_agent_llm_config", return_value=None),
            patch(
                "pillywiggins.onboard.get_default_llm_config",
                return_value={
                    k: "" for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")
                },
            ),
            patch("pillywiggins.onboard.load_existing_agents", return_value=[]),
        ):
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                },
            ]
            from pillywiggins.onboard import _add_agent_flow

            await _add_agent_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_openai_provider_prompts_api_key(self, mock_q, mock_list_models, mock_validate):
        mock_validate.return_value = (True, "testbot")
        mock_list_models.return_value = []

        select_responses = iter(["__all__","Puck — mischievous", "telegram", "openai", "UTC"])
        text_responses = iter(
            [
                "puck",
                "123456:ABC-DEF1234",
                "",
                "https://api.openai.com/v1",
                "sk-testkey",
                "gpt-4o",
                "all",
                "3",
            ]
        )
        confirm_responses = iter([True, False])

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_responses))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_responses))
            )
        )
        mock_q.Choice = MagicMock

        with (
            patch("pillywiggins.onboard.add_agent_to_configs"),
            patch("pillywiggins.onboard.discover_personalities") as mock_disc,
            patch("pillywiggins.onboard.agent_ids_in_use", return_value=set()),
            patch("pillywiggins.onboard.get_first_agent_llm_config", return_value=None),
            patch(
                "pillywiggins.onboard.get_default_llm_config",
                return_value={
                    k: "" for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")
                },
            ),
            patch("pillywiggins.onboard.load_existing_agents", return_value=[]),
        ):
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                },
            ]
            from pillywiggins.onboard import _add_agent_flow

            await _add_agent_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_invalid_bot_chat_limit_defaults_to_3(
        self, mock_q, mock_list_models, mock_validate
    ):
        mock_validate.return_value = (True, "testbot")
        mock_list_models.return_value = []

        select_responses = iter(["__all__","Puck — mischievous", "telegram", "ollama", "UTC"])
        text_responses = iter(
            [
                "puck",
                "123456:ABC-DEF1234",
                "",
                "http://host.docker.internal:11434/v1",
                "qwen3.5:8b",
                "all",
                "notanumber",
            ]
        )
        confirm_responses = iter([True, False])

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_responses))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_responses))
            )
        )
        mock_q.Choice = MagicMock

        with (
            patch("pillywiggins.onboard.add_agent_to_configs") as mock_add,
            patch("pillywiggins.onboard.discover_personalities") as mock_disc,
            patch("pillywiggins.onboard.agent_ids_in_use", return_value=set()),
            patch("pillywiggins.onboard.get_first_agent_llm_config", return_value=None),
            patch(
                "pillywiggins.onboard.get_default_llm_config",
                return_value={
                    k: "" for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")
                },
            ),
            patch("pillywiggins.onboard.load_existing_agents", return_value=[]),
        ):
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                },
            ]
            from pillywiggins.onboard import _add_agent_flow

            await _add_agent_flow()
            call_args = mock_add.call_args
            assert call_args.kwargs["bot_chat_limit"] == 3


class TestReconfigureAgentFlow:
    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_reconfigure_flow(self, mock_q, mock_list_models):
        mock_list_models.return_value = []

        select_responses = iter(["puck", "UTC", "ollama"])
        text_responses = iter(["all", "", "http://localhost:11434/v1", "qwen3.5:8b"])
        confirm_responses = iter([False])

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_responses))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_responses))
            )
        )

        agents = [
            {
                "id": "puck",
                "personality": "/config/puck.yaml",
                "allowed_user_ids": "all",
                "channel": "telegram",
                "environment": {
                    "TELEGRAM_BOT_TOKEN": "${PUCK_TELEGRAM_TOKEN}",
                    "LLM_PROVIDER": "ollama",
                    "LLM_BASE_URL": "http://localhost:11434/v1",
                    "MODEL_NAME": "qwen3.5:8b",
                },
            }
        ]

        with (
            patch("pillywiggins.onboard.load_existing_agents", return_value=agents),
            patch("pillywiggins.onboard.load_yaml", return_value={"agents": agents}),
            patch("pillywiggins.onboard.save_yaml"),
            patch(
                "pillywiggins.onboard.get_default_llm_config",
                return_value={
                    k: "" for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")
                },
            ),
            patch("pillywiggins.onboard.DOCKER_COMPOSE", Path("/tmp/nonexistent-dc.yaml")),
            patch("pillywiggins.onboard.subprocess.run") as mock_sub,
        ):
            from pillywiggins.onboard import _reconfigure_agent_flow

            await _reconfigure_agent_flow()
            mock_sub.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_agents(self):
        with patch("pillywiggins.onboard.load_existing_agents", return_value=[]):
            from pillywiggins.onboard import _reconfigure_agent_flow

            await _reconfigure_agent_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_cancel_at_agent_select(self, mock_q, mock_list_models):
        mock_q.select.return_value.ask_async = AsyncMock(return_value=None)
        with patch("pillywiggins.onboard.load_existing_agents", return_value=[{"id": "puck"}]):
            from pillywiggins.onboard import _reconfigure_agent_flow

            await _reconfigure_agent_flow()


class TestRemoveAgentFlow:
    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.remove_agent_from_configs")
    @patch("pillywiggins.onboard.questionary")
    async def test_remove_confirmed(self, mock_q, mock_remove):
        confirm_responses = iter([True])
        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(ask_async=AsyncMock(return_value="puck"))
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_responses))
            )
        )

        with (
            patch("pillywiggins.onboard.load_existing_agents", return_value=[{"id": "puck"}]),
            patch("pillywiggins.onboard.subprocess") as mock_sub,
        ):
            mock_sub.run.return_value = MagicMock(returncode=0)
            from pillywiggins.onboard import _remove_agent_flow

            await _remove_agent_flow()
            mock_remove.assert_called_once_with("puck")

    @pytest.mark.asyncio
    async def test_no_agents(self):
        with patch("pillywiggins.onboard.load_existing_agents", return_value=[]):
            from pillywiggins.onboard import _remove_agent_flow

            await _remove_agent_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.questionary")
    async def test_cancel_at_select(self, mock_q):
        mock_q.select.return_value.ask_async = AsyncMock(return_value=None)
        with patch("pillywiggins.onboard.load_existing_agents", return_value=[{"id": "puck"}]):
            from pillywiggins.onboard import _remove_agent_flow

            await _remove_agent_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.remove_agent_from_configs")
    @patch("pillywiggins.onboard.questionary")
    async def test_cancel_at_confirm(self, mock_q, mock_remove):
        select_responses = iter(["puck"])
        confirm_responses = iter([False])
        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_responses))
            )
        )

        with patch("pillywiggins.onboard.load_existing_agents", return_value=[{"id": "puck"}]):
            from pillywiggins.onboard import _remove_agent_flow

            await _remove_agent_flow()
            mock_remove.assert_not_called()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.remove_agent_from_configs")
    @patch("pillywiggins.onboard.questionary")
    async def test_docker_not_found(self, mock_q, mock_remove):
        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(ask_async=AsyncMock(return_value="puck"))
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(ask_async=AsyncMock(return_value=True))
        )

        with (
            patch("pillywiggins.onboard.load_existing_agents", return_value=[{"id": "puck"}]),
            patch("pillywiggins.onboard.subprocess") as mock_sub,
        ):
            mock_sub.run.side_effect = FileNotFoundError("docker not found")
            from pillywiggins.onboard import _remove_agent_flow

            await _remove_agent_flow()
            mock_remove.assert_called_once()


class TestStartRestartFlow:
    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.questionary")
    async def test_no_agents(self, mock_q):
        with patch("pillywiggins.onboard.load_existing_agents", return_value=[]):
            from pillywiggins.onboard import _start_restart_flow

            await _start_restart_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.questionary")
    async def test_start_all_agents(self, mock_q):
        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(ask_async=AsyncMock(return_value="All agents"))
        )

        with (
            patch("pillywiggins.onboard.load_existing_agents", return_value=[{"id": "puck"}]),
            patch("pillywiggins.onboard.subprocess") as mock_sub,
        ):
            mock_sub.run.return_value = MagicMock(returncode=0)
            from pillywiggins.onboard import _start_restart_flow

            await _start_restart_flow()
            mock_sub.run.assert_called()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.questionary")
    async def test_start_specific_agent(self, mock_q):
        select_responses = iter(["__all__","Select specific agent", "puck"])
        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )

        with (
            patch("pillywiggins.onboard.load_existing_agents", return_value=[{"id": "puck"}]),
            patch("pillywiggins.onboard.subprocess") as mock_sub,
        ):
            mock_sub.run.return_value = MagicMock(returncode=0)
            from pillywiggins.onboard import _start_restart_flow

            await _start_restart_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.questionary")
    async def test_cancel_at_action(self, mock_q):
        mock_q.select.return_value.ask_async = AsyncMock(return_value=None)
        with patch("pillywiggins.onboard.load_existing_agents", return_value=[{"id": "puck"}]):
            from pillywiggins.onboard import _start_restart_flow

            await _start_restart_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.questionary")
    async def test_docker_not_found(self, mock_q):
        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(ask_async=AsyncMock(return_value="All agents"))
        )

        with (
            patch("pillywiggins.onboard.load_existing_agents", return_value=[{"id": "puck"}]),
            patch("pillywiggins.onboard.subprocess") as mock_sub,
        ):
            mock_sub.run.side_effect = FileNotFoundError("docker not found")
            from pillywiggins.onboard import _start_restart_flow

            await _start_restart_flow()


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
        responses = iter(["🔧 Reconfigure agent", "\U0001f44b Exit"])
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
        responses = iter(["🗑️  Remove agent", "\U0001f44b Exit"])
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
        responses = iter(["🚀 Start/restart agents", "\U0001f44b Exit"])
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


class TestAddAgentFlowCancellations:
    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_cancel_at_agent_id(self, mock_q, mock_list_models, mock_validate):
        from pillywiggins.onboard import _add_agent_flow

        select_responses = iter(["__all__","Puck — mischievous", "telegram"])
        text_iter = iter(["puck", None])
        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_iter))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(ask_async=AsyncMock(return_value=True))
        )
        mock_q.Choice = MagicMock

        with (
            patch("pillywiggins.onboard.discover_personalities") as mock_disc,
            patch("pillywiggins.onboard.agent_ids_in_use", return_value=set()),
        ):
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                }
            ]
            await _add_agent_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    @patch("pillywiggins.onboard.agent_ids_in_use", return_value={"puck"})
    async def test_overwrite_declined(self, mock_ids, mock_q, mock_list_models, mock_validate):
        from pillywiggins.onboard import _add_agent_flow

        select_responses = iter(["__all__","Puck — mischievous", "telegram"])
        text_iter = iter(["puck"])
        confirm_iter = iter([False])

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_iter))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_iter))
            )
        )
        mock_q.Choice = MagicMock

        with patch("pillywiggins.onboard.discover_personalities") as mock_disc:
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                }
            ]
            await _add_agent_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_invalid_token_declined(self, mock_q, mock_list_models, mock_validate):
        from pillywiggins.onboard import _add_agent_flow

        mock_validate.return_value = (False, "Bad token")
        select_responses = iter(["__all__","Puck — mischievous", "telegram"])
        text_iter = iter(["puck", "badtoken1234567890"])
        confirm_iter = iter([False])

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_iter))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_iter))
            )
        )
        mock_q.Choice = MagicMock

        with (
            patch("pillywiggins.onboard.discover_personalities") as mock_disc,
            patch("pillywiggins.onboard.agent_ids_in_use", return_value=set()),
        ):
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                }
            ]
            await _add_agent_flow()

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.add_agent_to_configs")
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_docker_up_confirmed(
        self, mock_q, mock_list_models, mock_validate, mock_add_configs
    ):
        from pillywiggins.onboard import _add_agent_flow

        mock_validate.return_value = (True, "testbot")
        mock_list_models.return_value = []

        select_responses = iter(["__all__","Puck — mischievous", "telegram", "ollama", "UTC"])
        text_iter = iter(
            [
                "puck",
                "123456:ABC-DEF1234",
                "",
                "http://host.docker.internal:11434/v1",
                "qwen3.5:8b",
                "all",
                "3",
            ]
        )
        confirm_iter = iter([True, True])

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_iter))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_iter))
            )
        )
        mock_q.Choice = MagicMock

        with (
            patch("pillywiggins.onboard.discover_personalities") as mock_disc,
            patch("pillywiggins.onboard.agent_ids_in_use", return_value=set()),
            patch("pillywiggins.onboard.get_first_agent_llm_config", return_value=None),
            patch(
                "pillywiggins.onboard.get_default_llm_config",
                return_value={
                    k: "" for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")
                },
            ),
            patch("pillywiggins.onboard.load_existing_agents", return_value=[]),
            patch("pillywiggins.onboard.subprocess") as mock_sub,
        ):
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                }
            ]
            mock_sub.run.return_value = MagicMock(returncode=0)
            await _add_agent_flow()
            mock_sub.run.assert_called()


class TestAddAgentToDockerComposeEdgeCases:
    def test_creates_services_key_if_missing(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"volumes": {}}))
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )
        data = yaml.safe_load(compose_path.read_text())
        assert "puck" in data["services"]

    def test_creates_volumes_key_if_missing(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {}}))
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )
        data = yaml.safe_load(compose_path.read_text())
        assert "pgdata" in data["volumes"]

    def test_noop_if_no_services_key(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"volumes": {}}))
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            remove_agent_from_docker_compose("puck")


from pillywiggins.onboard import CUSTOM_TIMEZONE_OPTION


class TestTimezoneInAddAgentToAgentsYaml:
    def test_default_timezone_is_utc(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            add_agent_to_agents_yaml(
                agent_id="puck",
                personality_filename="puck.yaml",
                channel="telegram",
                token_env="PUCK_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=None,
            )
        data = yaml.safe_load(config_path.read_text())
        assert data["agents"][0]["timezone"] == "UTC"

    def test_custom_timezone(self, tmp_path):
        config_path = tmp_path / "agents.yaml"
        with patch("pillywiggins.onboard.AGENTS_YAML", config_path):
            add_agent_to_agents_yaml(
                agent_id="puck",
                personality_filename="puck.yaml",
                channel="telegram",
                token_env="PUCK_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=None,
                timezone="America/Los_Angeles",
            )
        data = yaml.safe_load(config_path.read_text())
        assert data["agents"][0]["timezone"] == "America/Los_Angeles"


class TestTimezoneInAddAgentToDockerCompose:
    def test_default_timezone_in_environment(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
            )
        data = yaml.safe_load(compose_path.read_text())
        svc_env = data["services"]["puck"]["environment"]
        assert svc_env["TIMEZONE"] == "UTC"
        assert svc_env["TZ"] == "UTC"

    def test_custom_timezone_in_environment(self, tmp_path):
        compose_path = tmp_path / "docker-compose.yaml"
        compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))
        with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
            add_agent_to_docker_compose(
                agent_id="puck",
                personality_filename="puck.yaml",
                token_env="PUCK_TELEGRAM_TOKEN",
                timezone="Asia/Tokyo",
            )
        data = yaml.safe_load(compose_path.read_text())
        svc_env = data["services"]["puck"]["environment"]
        assert svc_env["TIMEZONE"] == "Asia/Tokyo"
        assert svc_env["TZ"] == "Asia/Tokyo"


class TestTimezoneInAddAgentToConfigs:
    def test_timezone_passed_through(self):
        with (
            patch("pillywiggins.onboard.add_agent_to_agents_yaml") as mock_yaml,
            patch("pillywiggins.onboard.add_agent_to_docker_compose") as mock_compose,
            patch("pillywiggins.onboard.add_token_to_env"),
            patch("pillywiggins.onboard.add_llm_api_key_to_env"),
        ):
            add_agent_to_configs(
                agent_id="puck",
                personality_filename="puck.yaml",
                channel="telegram",
                token_env="PUCK_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=None,
                token_value="",
                timezone="Europe/Berlin",
            )
            _, kwargs = mock_yaml.call_args
            assert kwargs["timezone"] == "Europe/Berlin"
            _, kwargs = mock_compose.call_args
            assert kwargs["timezone"] == "Europe/Berlin"

    def test_default_timezone_is_utc(self):
        with (
            patch("pillywiggins.onboard.add_agent_to_agents_yaml") as mock_yaml,
            patch("pillywiggins.onboard.add_agent_to_docker_compose") as mock_compose,
            patch("pillywiggins.onboard.add_token_to_env"),
            patch("pillywiggins.onboard.add_llm_api_key_to_env"),
        ):
            add_agent_to_configs(
                agent_id="puck",
                personality_filename="puck.yaml",
                channel="telegram",
                token_env="PUCK_TELEGRAM_TOKEN",
                allowed_user_ids="all",
                bot_chat_limit=3,
                llm_config=None,
                token_value="",
            )
            _, kwargs = mock_yaml.call_args
            assert kwargs["timezone"] == "UTC"


class TestTimezoneInAddAgentFlow:
    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.add_agent_to_configs")
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_timezone_default_utc(
        self, mock_q, mock_list_models, mock_validate, mock_add_configs
    ):
        mock_validate.return_value = (True, "testbot")
        mock_list_models.return_value = []

        select_responses = iter(
            [
                "__all__",
                "Puck — mischievous",
                "telegram",
                "ollama",
                "UTC",
            ]
        )
        text_responses = iter(
            [
                "puck",
                "123456:ABC-DEF1234",
                "",
                "http://host.docker.internal:11434/v1",
                "qwen3.5:8b",
                "all",
                "3",
            ]
        )
        confirm_responses = iter([True, False])

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_responses))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_responses))
            )
        )
        mock_q.Choice = MagicMock

        with (
            patch("pillywiggins.onboard.discover_personalities") as mock_disc,
            patch("pillywiggins.onboard.agent_ids_in_use", return_value=set()),
            patch("pillywiggins.onboard.get_first_agent_llm_config", return_value=None),
            patch(
                "pillywiggins.onboard.get_default_llm_config",
                return_value={
                    k: "" for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")
                },
            ),
            patch("pillywiggins.onboard.load_existing_agents", return_value=[]),
        ):
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                },
            ]
            from pillywiggins.onboard import _add_agent_flow

            await _add_agent_flow()

        _, kwargs = mock_add_configs.call_args
        assert kwargs["timezone"] == "UTC"

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.add_agent_to_configs")
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_timezone_custom_via_custom_option(
        self, mock_q, mock_list_models, mock_validate, mock_add_configs
    ):
        mock_validate.return_value = (True, "testbot")
        mock_list_models.return_value = []

        select_responses = iter(
            [
                "__all__",
                "Puck — mischievous",
                "telegram",
                "ollama",
                CUSTOM_TIMEZONE_OPTION,
            ]
        )
        text_responses = iter(
            [
                "puck",
                "123456:ABC-DEF1234",
                "",
                "http://host.docker.internal:11434/v1",
                "qwen3.5:8b",
                "all",
                "3",
                "Europe/Moscow",
            ]
        )
        confirm_responses = iter([True, False])

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_responses))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_responses))
            )
        )
        mock_q.Choice = MagicMock

        with (
            patch("pillywiggins.onboard.discover_personalities") as mock_disc,
            patch("pillywiggins.onboard.agent_ids_in_use", return_value=set()),
            patch("pillywiggins.onboard.get_first_agent_llm_config", return_value=None),
            patch(
                "pillywiggins.onboard.get_default_llm_config",
                return_value={
                    k: "" for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")
                },
            ),
            patch("pillywiggins.onboard.load_existing_agents", return_value=[]),
        ):
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                },
            ]
            from pillywiggins.onboard import _add_agent_flow

            await _add_agent_flow()

        _, kwargs = mock_add_configs.call_args
        assert kwargs["timezone"] == "Europe/Moscow"

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.validate_telegram_token", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_cancel_at_timezone(self, mock_q, mock_list_models, mock_validate):
        mock_validate.return_value = (True, "testbot")
        mock_list_models.return_value = []

        select_responses = iter(
            [
                "__all__",
                "Puck — mischievous",
                "telegram",
                "ollama",
                None,
            ]
        )
        text_responses = iter(
            [
                "puck",
                "123456:ABC-DEF1234",
                "",
                "http://host.docker.internal:11434/v1",
                "qwen3.5:8b",
                "all",
                "3",
            ]
        )

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_responses))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(ask_async=AsyncMock(return_value=True))
        )
        mock_q.Choice = MagicMock

        with (
            patch("pillywiggins.onboard.discover_personalities") as mock_disc,
            patch("pillywiggins.onboard.agent_ids_in_use", return_value=set()),
            patch("pillywiggins.onboard.get_first_agent_llm_config", return_value=None),
            patch(
                "pillywiggins.onboard.get_default_llm_config",
                return_value={
                    k: "" for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")
                },
            ),
            patch("pillywiggins.onboard.load_existing_agents", return_value=[]),
        ):
            mock_disc.return_value = [
                {
                    "name": "Puck",
                    "description": "mischievous",
                    "filename": "puck.yaml",
                    "stem": "puck",
                    "channel": "telegram",
                    "bot_chat_limit": 3,
                },
            ]
            from pillywiggins.onboard import _add_agent_flow

            await _add_agent_flow()


class TestTimezoneInReconfigureAgentFlow:
    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_reconfigure_timezone(self, mock_q, mock_list_models):
        mock_list_models.return_value = []

        select_responses = iter(["puck", "America/Chicago", "ollama"])
        text_responses = iter(["all", "", "http://localhost:11434/v1", "qwen3.5:8b"])
        confirm_responses = iter([False])

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_responses))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_responses))
            )
        )

        agents = [
            {
                "id": "puck",
                "personality": "/config/puck.yaml",
                "allowed_user_ids": "all",
                "timezone": "UTC",
                "channel": "telegram",
                "environment": {
                    "TELEGRAM_BOT_TOKEN": "${PUCK_TELEGRAM_TOKEN}",
                    "LLM_PROVIDER": "ollama",
                    "LLM_BASE_URL": "http://localhost:11434/v1",
                    "MODEL_NAME": "qwen3.5:8b",
                },
            }
        ]

        with (
            patch("pillywiggins.onboard.load_existing_agents", return_value=agents),
            patch("pillywiggins.onboard.load_yaml", return_value={"agents": agents}),
            patch("pillywiggins.onboard.save_yaml") as mock_save,
            patch(
                "pillywiggins.onboard.get_default_llm_config",
                return_value={
                    k: "" for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")
                },
            ),
            patch("pillywiggins.onboard.DOCKER_COMPOSE", Path("/tmp/nonexistent-dc.yaml")),
            patch("pillywiggins.onboard.subprocess.run") as mock_sub,
        ):
            from pillywiggins.onboard import _reconfigure_agent_flow

            await _reconfigure_agent_flow()
            mock_sub.assert_not_called()

            saved_data = mock_save.call_args[0][1]
            saved_agent = saved_data["agents"][0]
            assert saved_agent["timezone"] == "America/Chicago"

    @pytest.mark.asyncio
    @patch("pillywiggins.onboard.list_models", new_callable=AsyncMock)
    @patch("pillywiggins.onboard.questionary")
    async def test_reconfigure_custom_timezone(self, mock_q, mock_list_models):
        mock_list_models.return_value = []

        select_responses = iter(["puck", CUSTOM_TIMEZONE_OPTION, "ollama"])
        text_responses = iter(
            ["all", "Europe/Helsinki", "", "http://localhost:11434/v1", "qwen3.5:8b"]
        )
        confirm_responses = iter([False])

        mock_q.select = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(select_responses))
            )
        )
        mock_q.text = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(text_responses))
            )
        )
        mock_q.confirm = MagicMock(
            side_effect=lambda *a, **kw: MagicMock(
                ask_async=AsyncMock(return_value=next(confirm_responses))
            )
        )

        agents = [
            {
                "id": "puck",
                "personality": "/config/puck.yaml",
                "allowed_user_ids": "all",
                "timezone": "UTC",
                "channel": "telegram",
                "environment": {
                    "TELEGRAM_BOT_TOKEN": "${PUCK_TELEGRAM_TOKEN}",
                    "LLM_PROVIDER": "ollama",
                    "LLM_BASE_URL": "http://localhost:11434/v1",
                    "MODEL_NAME": "qwen3.5:8b",
                },
            }
        ]

        with (
            patch("pillywiggins.onboard.load_existing_agents", return_value=agents),
            patch("pillywiggins.onboard.load_yaml", return_value={"agents": agents}),
            patch("pillywiggins.onboard.save_yaml") as mock_save,
            patch(
                "pillywiggins.onboard.get_default_llm_config",
                return_value={
                    k: "" for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")
                },
            ),
            patch("pillywiggins.onboard.DOCKER_COMPOSE", Path("/tmp/nonexistent-dc.yaml")),
            patch("pillywiggins.onboard.subprocess.run") as mock_sub,
        ):
            from pillywiggins.onboard import _reconfigure_agent_flow

            await _reconfigure_agent_flow()
            mock_sub.assert_not_called()

            saved_data = mock_save.call_args[0][1]
            saved_agent = saved_data["agents"][0]
            assert saved_agent["timezone"] == "Europe/Helsinki"
