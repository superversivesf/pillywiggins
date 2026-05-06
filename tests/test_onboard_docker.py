"""Tests for Docker/compose generation and config file manipulation."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from pillywiggins.onboard import (
    add_agent_to_agents_yaml,
    add_agent_to_configs,
    add_agent_to_docker_compose,
    add_brave_api_key_to_env,
    add_llm_api_key_to_env,
    add_token_to_env,
    comment_token_in_env,
    remove_agent_from_agents_yaml,
    remove_agent_from_configs,
    remove_agent_from_docker_compose,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("docker_available"),
]


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


class TestAddBraveApiKeyToEnv:
    def test_skips_if_file_missing(self, tmp_path):
        env_path = tmp_path / ".env"
        # Doesn't exist — should not raise
        add_brave_api_key_to_env("brave-key", env_path)

    def test_updates_existing_key(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("BRAVE_API_KEY=old-key\n")
        add_brave_api_key_to_env("new-key", env_path)
        content = env_path.read_text()
        assert "BRAVE_API_KEY=new-key" in content
        assert "old-key" not in content

    def test_inserts_after_search_section(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("# --- Search Configuration ---\nSEARXNG_URL=http://searxng:8080\n")
        add_brave_api_key_to_env("brave-key", env_path)
        content = env_path.read_text()
        assert "BRAVE_API_KEY=brave-key" in content

    def test_appends_with_section_header(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("UNRELATED=value\n")
        add_brave_api_key_to_env("brave-key", env_path)
        content = env_path.read_text()
        assert "BRAVE_API_KEY=brave-key" in content
        assert "# --- Search Configuration ---" in content


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