import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.__main__ import _load_adapter_class, _run


def _make_mock_agent():
    mock_agent = MagicMock()
    mock_agent.load_history = AsyncMock()
    mock_agent.start = AsyncMock()
    mock_agent.shutdown = AsyncMock()
    mock_agent._cache = MagicMock()
    mock_agent._cache.close = AsyncMock()
    mock_agent._private_memory = MagicMock()
    mock_agent._private_memory.connect = AsyncMock()
    mock_agent._private_memory.close = AsyncMock()
    mock_agent._store = MagicMock()
    mock_agent._store.connect = AsyncMock()
    mock_agent._store.close = AsyncMock()
    return mock_agent


@pytest.mark.asyncio
async def test_run_starts_health_server():
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=SystemExit)
    mock_agent = _make_mock_agent()
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(SystemExit):
            await _run(mock_adapter, mock_agent, mock_settings)

    mock_health.assert_called_once_with(mock_settings)


@pytest.mark.asyncio
async def test_run_loads_history():
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=SystemExit)
    mock_agent = _make_mock_agent()
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(SystemExit):
            await _run(mock_adapter, mock_agent, mock_settings)

    mock_agent.load_history.assert_called_once()


@pytest.mark.asyncio
async def test_run_connects_adapter():
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=SystemExit)
    mock_agent = _make_mock_agent()
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(SystemExit):
            await _run(mock_adapter, mock_agent, mock_settings)

    mock_adapter.connect.assert_called_once()


@pytest.mark.asyncio
async def test_run_cleans_up_on_exit():
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=RuntimeError("stopped"))
    mock_agent = _make_mock_agent()
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(RuntimeError):
            await _run(mock_adapter, mock_agent, mock_settings)

    mock_agent._private_memory.close.assert_called_once()
    mock_agent._store.close.assert_called_once()
    mock_agent._cache.close.assert_called_once()
    mock_runner.cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_run_connects_private_memory():
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=SystemExit)
    mock_agent = _make_mock_agent()
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(SystemExit):
            await _run(mock_adapter, mock_agent, mock_settings)

    mock_agent._private_memory.connect.assert_called_once()
    mock_agent._store.connect.assert_called_once()


def test_main_parses_args():
    with (
        patch("pillywiggins.__main__.Settings") as mock_settings_cls,
        patch("pillywiggins.__main__.load_personality") as mock_load,
        patch("pillywiggins.__main__.ConversationCache") as mock_cache_cls,
        patch("pillywiggins.__main__.PrivateMemory") as mock_pm_cls,
        patch("pillywiggins.__main__.PillywigginAgent") as mock_agent_cls,
        patch("pillywiggins.__main__._load_adapter_class") as mock_load_adapter,
        patch("pillywiggins.__main__.asyncio") as mock_asyncio,
        patch("sys.argv", ["pillywiggins", "--channel", "telegram"]),
    ):
        mock_settings = MagicMock()
        mock_settings.telegram_bot_token = "fake-token"
        mock_settings_cls.return_value = mock_settings
        mock_adapter_cls = MagicMock()
        mock_load_adapter.return_value = mock_adapter_cls

        from pillywiggins.__main__ import main

        main()

    mock_settings_cls.assert_called_once()
    mock_agent_cls.assert_called_once()
    mock_adapter_cls.assert_called_once()
    mock_asyncio.run.assert_called_once()


def test_main_with_agent_id_calls_get_agent_config():
    mock_agent_cfg = MagicMock()
    mock_agent_cfg.id = "bramblethorn"
    mock_agent_cfg.personality = "/config/bramblethorn.yaml"
    mock_agent_cfg.channel = "telegram"
    mock_agent_cfg.allowed_user_ids = "all"
    mock_agent_cfg.environment = {}

    with (
        patch("pillywiggins.__main__.Settings") as mock_settings_cls,
        patch("pillywiggins.__main__.get_agent_config") as mock_get_cfg,
        patch("pillywiggins.__main__.apply_agent_env") as mock_apply_env,
        patch("pillywiggins.__main__.load_personality") as mock_load,
        patch("pillywiggins.__main__.ConversationCache") as mock_cache_cls,
        patch("pillywiggins.__main__.PrivateMemory") as mock_pm_cls,
        patch("pillywiggins.__main__.PillywigginAgent") as mock_agent_cls,
        patch("pillywiggins.__main__._load_adapter_class") as mock_load_adapter,
        patch("pillywiggins.__main__.SkillRegistry") as mock_skill_cls,
        patch("pillywiggins.__main__.asyncio") as mock_asyncio,
        patch("sys.argv", ["pillywiggins", "--agent-id", "bramblethorn"]),
    ):
        mock_settings = MagicMock()
        mock_settings.telegram_bot_token = "fake-token"
        mock_settings.agents_config_path = "agents.yaml"
        mock_settings_cls.return_value = mock_settings
        mock_get_cfg.return_value = mock_agent_cfg
        mock_adapter_cls = MagicMock()
        mock_load_adapter.return_value = mock_adapter_cls

        from pillywiggins.__main__ import main

        main()

    mock_get_cfg.assert_called_once_with("bramblethorn", path="agents.yaml")
    mock_apply_env.assert_called_once_with(mock_agent_cfg)


def test_main_agent_id_or_channel_required():
    with patch("sys.argv", ["pillywiggins"]):
        from pillywiggins.__main__ import main

        with pytest.raises(SystemExit):
            main()


def test_main_agent_id_sets_channel_from_config():
    mock_agent_cfg = MagicMock()
    mock_agent_cfg.id = "bramblethorn"
    mock_agent_cfg.personality = "/config/bramblethorn.yaml"
    mock_agent_cfg.channel = "telegram"
    mock_agent_cfg.allowed_user_ids = "all"
    mock_agent_cfg.environment = {}

    with (
        patch("pillywiggins.__main__.Settings") as mock_settings_cls,
        patch("pillywiggins.__main__.get_agent_config") as mock_get_cfg,
        patch("pillywiggins.__main__.apply_agent_env") as mock_apply_env,
        patch("pillywiggins.__main__.load_personality") as mock_load,
        patch("pillywiggins.__main__.ConversationCache") as mock_cache_cls,
        patch("pillywiggins.__main__.PrivateMemory") as mock_pm_cls,
        patch("pillywiggins.__main__.PillywigginAgent") as mock_agent_cls,
        patch("pillywiggins.__main__._load_adapter_class") as mock_load_adapter,
        patch("pillywiggins.__main__.SkillRegistry") as mock_skill_cls,
        patch("pillywiggins.__main__.asyncio") as mock_asyncio,
        patch("sys.argv", ["pillywiggins", "--agent-id", "bramblethorn"]),
    ):
        mock_settings = MagicMock()
        mock_settings.telegram_bot_token = "fake-token"
        mock_settings.agents_config_path = "agents.yaml"
        mock_settings_cls.return_value = mock_settings
        mock_get_cfg.return_value = mock_agent_cfg
        mock_adapter_cls = MagicMock()
        mock_load_adapter.return_value = mock_adapter_cls

        from pillywiggins.__main__ import main

        main()

    mock_agent_cls.assert_called_once()
    call_kwargs = (
        mock_agent_cls.call_args[1]
        if mock_agent_cls.call_args[1]
        else mock_agent_cls.call_args[0] and {}
    )
    if "agent_id" in (mock_agent_cls.call_args[1] or {}):
        assert mock_agent_cls.call_args[1]["agent_id"] == "bramblethorn"


def test_load_adapter_class_telegram():
    cls = _load_adapter_class("telegram")
    from pillywiggins.adapters.telegram_adapter import TelegramAdapter

    assert cls is TelegramAdapter


def test_load_adapter_class_raises_for_missing_adapter():
    with pytest.raises(ImportError):
        _load_adapter_class("irc")


def test_main_routes_telegram_via_dynamic_load():
    with (
        patch("pillywiggins.__main__.Settings") as mock_settings_cls,
        patch("pillywiggins.__main__.load_personality") as mock_load,
        patch("pillywiggins.__main__.ConversationCache") as mock_cache_cls,
        patch("pillywiggins.__main__.PrivateMemory") as mock_pm_cls,
        patch("pillywiggins.__main__.PillywigginAgent") as mock_agent_cls,
        patch("pillywiggins.__main__._load_adapter_class") as mock_load_adapter,
        patch("pillywiggins.__main__.asyncio") as mock_asyncio,
        patch("sys.argv", ["pillywiggins", "--channel", "telegram"]),
    ):
        mock_settings = MagicMock()
        mock_settings.telegram_bot_token = "fake-token"
        mock_settings_cls.return_value = mock_settings
        mock_adapter_cls = MagicMock()
        mock_load_adapter.return_value = mock_adapter_cls

        from pillywiggins.__main__ import main

        main()

    mock_load_adapter.assert_called_once_with("telegram")
    mock_adapter_cls.assert_called_once_with(
        agent=mock_agent_cls.return_value,
        token="fake-token",
        settings=mock_settings,
    )


def test_main_raises_import_error_for_missing_adapter():
    with (
        patch("pillywiggins.__main__.Settings") as mock_settings_cls,
        patch("pillywiggins.__main__.load_personality") as mock_load,
        patch("pillywiggins.__main__.ConversationCache") as mock_cache_cls,
        patch("pillywiggins.__main__.PrivateMemory") as mock_pm_cls,
        patch("pillywiggins.__main__.PillywigginAgent") as mock_agent_cls,
        patch("pillywiggins.__main__._load_adapter_class") as mock_load_adapter,
        patch("sys.argv", ["pillywiggins", "--channel", "discord"]),
    ):
        mock_settings = MagicMock()
        mock_settings.telegram_bot_token = "fake-token"
        mock_settings_cls.return_value = mock_settings
        mock_load_adapter.side_effect = ImportError("No module named 'discord_adapter'")

        from pillywiggins.__main__ import main

        with pytest.raises(ImportError, match="discord"):
            main()


@pytest.mark.asyncio
async def test_run_private_memory_failure_sets_none():
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=SystemExit)
    mock_agent = _make_mock_agent()
    mock_agent._private_memory.connect = AsyncMock(side_effect=Exception("pg down"))
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(SystemExit):
            await _run(mock_adapter, mock_agent, mock_settings)

    assert mock_agent._private_memory is None


@pytest.mark.asyncio
async def test_run_store_failure_sets_none():
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=SystemExit)
    mock_agent = _make_mock_agent()
    mock_agent._store.connect = AsyncMock(side_effect=Exception("store down"))
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(SystemExit):
            await _run(mock_adapter, mock_agent, mock_settings)

    assert mock_agent._store is None


@pytest.mark.asyncio
async def test_run_skips_private_memory_close_when_none():
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=SystemExit)
    mock_agent = _make_mock_agent()
    mock_agent._private_memory = None
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(SystemExit):
            await _run(mock_adapter, mock_agent, mock_settings)


@pytest.mark.asyncio
async def test_run_skips_store_close_when_none():
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=SystemExit)
    mock_agent = _make_mock_agent()
    mock_agent._store = None
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(SystemExit):
            await _run(mock_adapter, mock_agent, mock_settings)


@pytest.mark.asyncio
async def test_run_cleans_up_adapter_disconnect():
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=RuntimeError("stopped"))
    mock_agent = _make_mock_agent()
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(RuntimeError):
            await _run(mock_adapter, mock_agent, mock_settings)

    mock_agent._cache.close.assert_called_once()


def test_main_rejects_invalid_channel():
    with patch("sys.argv", ["pillywiggins", "--channel", "irc"]):
        from pillywiggins.__main__ import main

        with pytest.raises(SystemExit):
            main()


def test_main_requires_channel_arg():
    with patch("sys.argv", ["pillywiggins"]):
        from pillywiggins.__main__ import main

        with pytest.raises(SystemExit):
            main()


@pytest.mark.asyncio
async def test_run_both_memory_and_store_fail():
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=SystemExit)
    mock_agent = _make_mock_agent()
    mock_agent._private_memory.connect = AsyncMock(side_effect=Exception("pg down"))
    mock_agent._store.connect = AsyncMock(side_effect=Exception("store down"))
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(SystemExit):
            await _run(mock_adapter, mock_agent, mock_settings)

    assert mock_agent._private_memory is None
    assert mock_agent._store is None


@pytest.mark.asyncio
async def test_run_calls_agent_start():
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=SystemExit)
    mock_agent = _make_mock_agent()
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(SystemExit):
            await _run(mock_adapter, mock_agent, mock_settings)

    mock_agent.start.assert_called_once()


@pytest.mark.asyncio
async def test_run_calls_agent_start_after_load_history():
    """Verify start() is called after load_history(), not before."""
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=SystemExit)
    mock_agent = _make_mock_agent()
    mock_settings = MagicMock()

    call_order = []
    mock_agent.load_history = AsyncMock(side_effect=lambda: call_order.append("load_history"))
    mock_agent.start = AsyncMock(side_effect=lambda: call_order.append("start"))

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(SystemExit):
            await _run(mock_adapter, mock_agent, mock_settings)

    assert call_order == ["load_history", "start"]


@pytest.mark.asyncio
async def test_run_calls_shutdown_on_exit():
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock(side_effect=RuntimeError("stopped"))
    mock_agent = _make_mock_agent()
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        with pytest.raises(RuntimeError):
            await _run(mock_adapter, mock_agent, mock_settings)

    mock_agent.shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_run_calls_shutdown_on_success():
    """shutdown() should be called even when adapter.listen() completes normally."""
    mock_adapter = MagicMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.listen = AsyncMock()  # no error
    mock_agent = _make_mock_agent()
    mock_settings = MagicMock()

    with patch("pillywiggins.__main__.start_health_server") as mock_health:
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_health.return_value = mock_runner

        await _run(mock_adapter, mock_agent, mock_settings)

    mock_agent.shutdown.assert_called_once()
