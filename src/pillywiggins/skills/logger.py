import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SENSITIVE_KEYS = {
    "token",
    "api_key",
    "password",
    "secret",
    "auth",
    "credential",
    "private_key",
    "apikey",
    "passwd",
    "key",
    "authorization",
}

DEFAULT_LOG_DIR = Path(os.environ.get("PILLYWIGGINS_LOG_DIR", "logs"))
SKILL_LOG_FILE = DEFAULT_LOG_DIR / "skill_exec.log"

_skill_logger: Optional[logging.Logger] = None


def _get_skill_logger() -> logging.Logger:
    global _skill_logger
    if _skill_logger is not None:
        return _skill_logger

    logger = logging.getLogger("pillywiggins.skill_exec")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers):
        DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            SKILL_LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        formatter = logging.Formatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    _skill_logger = logger
    return _skill_logger


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for k, v in value.items():
            lower = k.lower()
            if any(s in lower for s in SENSITIVE_KEYS):
                redacted[k] = "<REDACTED>"
            else:
                redacted[k] = _redact(v)
        return redacted
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _result_summary(result: Any, max_len: int = 200) -> str:
    try:
        text = json.dumps(result, default=str)
    except (TypeError, ValueError):
        text = str(result)
    return text[:max_len] if len(text) <= max_len else text[: max_len - 3] + "..."


def log_skill_execution(
    agent_id: str,
    channel: str,
    skill_name: str,
    args: dict[str, Any],
    result: Any = None,
    error: Optional[str] = None,
    council_memory: Any = None,
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    redacted_args = _redact(args)
    summary = _result_summary(result) if error is None else ""

    record = {
        "timestamp": timestamp,
        "agent_id": agent_id,
        "channel": channel,
        "skill_name": skill_name,
        "args": redacted_args,
        "result_summary": summary,
        "error": error,
    }

    logger = _get_skill_logger()
    logger.info(json.dumps(record, default=str))

    if council_memory is not None:
        try:
            import asyncio

            content = f"Skill '{skill_name}' executed by {agent_id} on {channel}."
            if error:
                content += f" Error: {error}"
            else:
                content += f" Result: {summary}"

            async def _write():
                try:
                    # Generate a real embedding so the entry is searchable
                    # via vector similarity.  Fall back to None if embedding
                    # generation fails (write_entry will store NULL).
                    embedding: list[float] | None = None
                    try:
                        from pillywiggins.memory.embeddings import embed
                        from pillywiggins.config import Settings

                        settings = Settings()
                        embedding = await embed(
                            content,
                            base_url=settings.llm_base_url,
                            api_key=settings.llm_api_key,
                            provider=settings.llm_provider,
                            model=settings.embedding_model,
                            expected_dimension=settings.embedding_dimension,
                        )
                    except Exception:
                        # Embedding generation failed — write with NULL
                        pass

                    await council_memory.write_entry(
                        content=content,
                        tags=["skill"],
                        embedding=embedding,
                        message_type="skill_execution",
                        confidence=1.0,
                    )
                except Exception:
                    pass

            asyncio.create_task(_write())
        except Exception:
            pass
