import logging
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pillywiggins.logging_utils import AgentLogger, log_timing_context


@pytest.fixture
def temp_log_dir(tmp_path):
    return str(tmp_path / "logs")


class TestAgentLogger:
    def test_init_creates_log_dir(self, temp_log_dir):
        logger = AgentLogger("puck", log_dir=temp_log_dir)
        assert Path(temp_log_dir).exists()

    def test_handlers_attached(self, temp_log_dir):
        logger = AgentLogger("puck", log_dir=temp_log_dir)
        assert len(logger.logger.handlers) == 2

    def test_log_user_message(self, temp_log_dir, caplog):
        agent_logger = AgentLogger("puck", log_dir=temp_log_dir)
        with caplog.at_level(logging.INFO, logger="agent.puck"):
            agent_logger.log_user_message("hello world")
        assert "received" in caplog.text
        assert "hello world" in caplog.text

    def test_log_system_prompt(self, temp_log_dir, caplog):
        agent_logger = AgentLogger("puck", log_dir=temp_log_dir)
        with caplog.at_level(logging.INFO, logger="agent.puck"):
            agent_logger.log_system_prompt("You are helpful." * 100)
        assert "system prompt" in caplog.text
        assert "1600 chars" in caplog.text

    def test_log_tool_calls(self, temp_log_dir, caplog):
        agent_logger = AgentLogger("puck", log_dir=temp_log_dir)
        calls = [
            {"name": "get_weather", "args": {"city": "London"}},
            {"tool_name": "search", "arguments": {"q": "test"}},
        ]
        with caplog.at_level(logging.INFO, logger="agent.puck"):
            agent_logger.log_tool_calls(calls)
        assert "get_weather" in caplog.text
        assert "search" in caplog.text
        assert "tool call" in caplog.text

    def test_log_tool_result(self, temp_log_dir, caplog):
        agent_logger = AgentLogger("puck", log_dir=temp_log_dir)
        with caplog.at_level(logging.INFO, logger="agent.puck"):
            agent_logger.log_tool_result("calc", 42, 15.2)
        assert "tool result" in caplog.text
        assert "42" in caplog.text
        assert "15ms" in caplog.text

    def test_log_tool_error(self, temp_log_dir, caplog):
        agent_logger = AgentLogger("puck", log_dir=temp_log_dir)
        with caplog.at_level(logging.INFO, logger="agent.puck"):
            agent_logger.log_tool_error("calc", "division by zero", 5.0)
        assert "tool error" in caplog.text
        assert "division by zero" in caplog.text

    def test_log_llm_response(self, temp_log_dir, caplog):
        agent_logger = AgentLogger("puck", log_dir=temp_log_dir)
        with caplog.at_level(logging.INFO, logger="agent.puck"):
            agent_logger.log_llm_response("Hello there!", 250.5)
        assert "response" in caplog.text
        assert "Hello there!" in caplog.text
        assert "250ms total" in caplog.text

    def test_log_timing(self, temp_log_dir, caplog):
        agent_logger = AgentLogger("puck", log_dir=temp_log_dir)
        with caplog.at_level(logging.INFO, logger="agent.puck"):
            agent_logger.log_timing("embedding", 12.3)
        assert "embedding" in caplog.text
        assert "12ms" in caplog.text

    def test_different_agents_have_separate_loggers(self, temp_log_dir):
        logger_a = AgentLogger("puck", log_dir=temp_log_dir)
        logger_b = AgentLogger("oberon", log_dir=temp_log_dir)
        assert logger_a.logger is not logger_b.logger
        assert len(logger_a.logger.handlers) == 2
        assert len(logger_b.logger.handlers) == 2

    def test_duplicate_init_does_not_add_handlers(self, temp_log_dir):
        logger1 = AgentLogger("puck", log_dir=temp_log_dir)
        logger2 = AgentLogger("puck", log_dir=temp_log_dir)
        # Handlers should not double because logger.name is same
        assert len(logger1.logger.handlers) == 2
        assert len(logger2.logger.handlers) == 2

    def test_log_file_created(self, temp_log_dir):
        # Ensure logger is fresh for this temp dir
        name = "agent_test_log_file"
        log_dir = Path(temp_log_dir)
        existing = logging.getLogger(f"agent.{name}")
        for h in list(existing.handlers):
            existing.removeHandler(h)
            if isinstance(h, logging.handlers.RotatingFileHandler):
                h.close()
        agent_logger = AgentLogger(name, log_dir=temp_log_dir)
        agent_logger.log_user_message("hello")
        log_file = log_dir / f"agent-{name}.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "hello" in content

    def test_rotating_file_handler_settings(self, temp_log_dir):
        agent_logger = AgentLogger("puck", log_dir=temp_log_dir)
        file_handler = agent_logger.logger.handlers[0]
        # First handler should be RotatingFileHandler
        from logging.handlers import RotatingFileHandler

        assert isinstance(file_handler, RotatingFileHandler)
        assert file_handler.maxBytes == 5 * 1024 * 1024
        assert file_handler.backupCount == 3


class TestLogTimingContext:
    def test_logs_timing(self, temp_log_dir, caplog):
        agent_logger = AgentLogger("puck", log_dir=temp_log_dir)
        with caplog.at_level(logging.INFO, logger="agent.puck"):
            with log_timing_context(agent_logger, "test_step"):
                time.sleep(0.01)
        assert "test_step" in caplog.text
        assert "ms" in caplog.text

    def test_logs_timing_even_on_exception(self, temp_log_dir, caplog):
        agent_logger = AgentLogger("puck", log_dir=temp_log_dir)
        with caplog.at_level(logging.INFO, logger="agent.puck"):
            with pytest.raises(RuntimeError):
                with log_timing_context(agent_logger, "fail_step"):
                    raise RuntimeError("boom")
        assert "fail_step" in caplog.text
