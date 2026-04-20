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
    add_llm_api_key_to_env,
    add_token_to_env,
    agent_ids_in_use,
    comment_token_in_env,
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
        for vol in ["pgdata", "redisdata", "searxng_data", "skills"]:
            assert vol in data["volumes"]


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
        env_path.write_text("# --- Telegram Bot Tokens ---\nEXISTING_TOKEN=x\n")
        add_token_to_env("puck", "12345:abcd", env_path)
        content = env_path.read_text()
        lines = content.split("\n")
        # New token should be inserted right after the header
        for i, line in enumerate(lines):
            if "Telegram Bot Token" in line:
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
        assert "# --- Telegram Bot Tokens ---" in content


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
            mock_env.assert_called_once_with("puck", "12345:abcd")
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
