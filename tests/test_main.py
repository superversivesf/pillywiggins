from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.__main__ import _run


def _make_mock_agent():
    mock_agent = MagicMock()
    mock_agent.load_history = AsyncMock()
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
    with patch("pillywiggins.__main__.Settings") as mock_settings_cls, \
         patch("pillywiggins.__main__.load_personality") as mock_load, \
         patch("pillywiggins.__main__.ConversationCache") as mock_cache_cls, \
         patch("pillywiggins.__main__.PrivateMemory") as mock_pm_cls, \
         patch("pillywiggins.__main__.PillywigginAgent") as mock_agent_cls, \
         patch("pillywiggins.__main__.TelegramAdapter") as mock_adapter_cls, \
         patch("pillywiggins.__main__.asyncio") as mock_asyncio, \
         patch("sys.argv", ["pillywiggins", "--channel", "telegram"]):

        mock_settings = MagicMock()
        mock_settings_cls.return_value = mock_settings

        from pillywiggins.__main__ import main
        main()

    mock_settings_cls.assert_called_once()
    mock_agent_cls.assert_called_once()
    mock_adapter_cls.assert_called_once()
    mock_asyncio.run.assert_called_once()


def test_main_rejects_unimplemented_channel():
    with patch("pillywiggins.__main__.Settings") as mock_settings_cls, \
         patch("pillywiggins.__main__.load_personality") as mock_load, \
         patch("pillywiggins.__main__.ConversationCache") as mock_cache_cls, \
         patch("pillywiggins.__main__.PrivateMemory") as mock_pm_cls, \
         patch("pillywiggins.__main__.PillywigginAgent") as mock_agent_cls, \
         patch("sys.argv", ["pillywiggins", "--channel", "discord"]):

        mock_settings = MagicMock()
        mock_settings_cls.return_value = mock_settings

        from pillywiggins.__main__ import main
        with pytest.raises(ValueError, match="not yet implemented"):
            main()