import json
import logging
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class AgentLogger:
    """Structured logger for agent round-trips with per-step timing."""

    def __init__(self, agent_id: str, log_dir: str = "logs"):
        self.agent_id = agent_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger(f"agent.{agent_id}")
        self.logger.setLevel(logging.INFO)

        expected_path = str((self.log_dir / f"agent-{agent_id}.log").resolve())
        has_correct_file_handler = any(
            isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == expected_path
            for h in self.logger.handlers
        )

        # Avoid duplicate handlers if re-instantiated with same log_dir
        if has_correct_file_handler:
            return

        # Replace stale handlers that point to a different log_dir
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            if isinstance(handler, RotatingFileHandler):
                handler.close()

        file_handler = RotatingFileHandler(
            self.log_dir / f"agent-{agent_id}.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        formatter = logging.Formatter(
            "[%(asctime)s] %(agent_marker)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def _log(self, emoji: str, message: str, extra: dict | None = None) -> None:
        self.logger.info(
            message,
            extra={"agent_marker": f"{emoji} {self.agent_id}"},
        )

    def log_user_message(self, text: str) -> None:
        self._log("📥", f"received: {text[:200]!r}")

    def log_system_prompt(self, prompt: str) -> None:
        self._log("🧠", f"system prompt: {len(prompt)} chars")

    def log_tool_calls(self, calls: list[dict]) -> None:
        for call in calls:
            name = call.get("name", call.get("tool_name", "unknown"))
            args = call.get("args", call.get("arguments", {}))
            args_str = json.dumps(args, default=str)[:200]
            self._log("⚡", f"tool call: {name}({args_str})")

    def log_tool_result(self, name: str, result: Any, duration_ms: float) -> None:
        result_str = str(result)[:200]
        self._log(
            "✅", f"tool result: {name} → {result_str!r} ({duration_ms:.0f}ms)"
        )

    def log_tool_error(self, name: str, error: str, duration_ms: float) -> None:
        self._log("❌", f"tool error: {name} → {error!r} ({duration_ms:.0f}ms)")

    def log_llm_response(self, response_text: str, total_duration_ms: float) -> None:
        self._log(
            "💬",
            f"response: {response_text[:500]!r} ({total_duration_ms:.0f}ms total)",
        )

    def log_timing(self, step_name: str, duration_ms: float) -> None:
        self._log("⏱️", f"{step_name}: {duration_ms:.0f}ms")


@contextmanager
def log_timing_context(logger: AgentLogger, step_name: str):
    """Context manager for timing a block and logging the duration."""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.log_timing(step_name, duration_ms)
