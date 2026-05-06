"""Tests for onboard interactive flows: _add_agent_flow, _reconfigure_agent_flow,
_remove_agent_flow, _start_restart_flow."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from pillywiggins.onboard import CUSTOM_TIMEZONE_OPTION

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("docker_available"),
]


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