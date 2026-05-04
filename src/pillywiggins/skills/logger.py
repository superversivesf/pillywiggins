import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LOG_DIR = Path(os.environ.get("PILLYWIGGINS_LOG_DIR", "logs"))
SKILL_LOG_FILE = DEFAULT_LOG_DIR / "skill_exec.log"

_skill_logger = None


def _get_skill_logger() -> logging.Logger:
    global _skill_logger
    if _skill_logger is not None:
        return _skill_logger

    logger = logging.getLogger("pillywiggins.skill_exec")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not any(
        isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers
    ):
        DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            SKILL_LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    _skill_logger = logger
    return _skill_logger


def _result_summary(result: Any, max_len: int = 200) -> str:
    try:
        text = json.dumps(result, default=str)
    except (TypeError, ValueError):
        text = str(result)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def log_skill_execution(agent_id, channel, skill_name, args, result, exception=None):
    """Write a structured JSON log line for every skill execution.

    Log fields:
        - timestamp_iso: UTC ISO-8601 timestamp
        - agent_id
        - channel
        - skill_name
        - args
        - result_status: "success" or "error"
        - result_summary: serialised result (None on error)
        - error: exception string if any
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    record = {
        "timestamp_iso": timestamp,
        "agent_id": agent_id,
        "channel": channel,
        "skill_name": skill_name,
        "args": args,
        "result_status": "error" if exception is not None else "success",
        "result_summary": _result_summary(result) if exception is None else None,
        "error": exception,
    }
    logger = _get_skill_logger()
    logger.info(json.dumps(record, default=str))
