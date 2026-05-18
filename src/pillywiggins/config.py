import asyncio
import logging

from pydantic import field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    agent_id: str = ""
    channel: str = "telegram"
    personality_file: str = ""
    database_url: str = ""
    pg_password: str = ""
    redis_url: str = "redis://redis:6379/0"  # Used for ConversationCache; scheduler uses MemoryJobStore (see note below)
    nats_url: str = "nats://nats:4222"
    nats_connect_timeout: float = 5.0
    nats_reconnect_attempts: int = 5
    llm_provider: str = "ollama"
    llm_base_url: str = "http://host.docker.internal:11434/v1"
    llm_api_key: str = ""
    model_name: str = "qwen3.5:8b"
    embedding_model: str = "nomic-embed-text"  # default for Ollama embedding
    embedding_dimension: int = 768  # updated at startup by resolve_embedding_config
    telegram_bot_token: str = ""
    discord_bot_token: str = ""
    compact_keep_messages: int = 6
    compact_truncate_message_chars: int = 2000
    allowed_user_ids: str = ""
    memory_retention_days: int = 90
    memory_max_entries: int = 1000
    skills_dir: str = "/app/skills"
    sandbox_all: bool = True
    sandbox_skills: str = ""
    scheduler_enabled: bool = True
    searxng_url: str = "http://searxng:8080"
    searxng_categories: str = "general"
    searxng_max_results: int = 5
    agents_config_path: str = "agents.yaml"
    timezone: str = "UTC"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # ------------------------------------------------------------------
    # Security validators: refuse empty or 'changeme' DB credentials
    # ------------------------------------------------------------------

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "DATABASE_URL must be explicitly set in .env — "
                "no default value is provided."
            )
        if "changeme" in v.lower():
            raise ValueError(
                "DATABASE_URL must not contain 'changeme' — "
                "set a real password in .env."
            )
        return v

    @field_validator("pg_password")
    @classmethod
    def validate_pg_password(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "PG_PASSWORD must be explicitly set in .env — "
                "no default value is provided."
            )
        if "changeme" in v.lower():
            raise ValueError(
                "PG_PASSWORD must not be 'changeme' — "
                "set a real password in .env."
            )
        return v

    def get_searxng_categories(self) -> list[str]:
        if not self.searxng_categories or self.searxng_categories.strip().lower() == "all":
            return []
        return [c.strip() for c in self.searxng_categories.split(",") if c.strip()]

    def should_sandbox_all(self) -> bool:
        """Return True if all skills should be sandboxed (default: True)."""
        return self.sandbox_all

    def get_sandbox_skill_names(self) -> set[str]:
        """Return the set of specific skill names to sandbox.

        When sandbox_all is True, returns an empty set (all skills
        are sandboxed, so no individual listing is needed).
        When sandbox_all is False, returns the comma-separated skills
        from sandbox_skills as a set of trimmed strings.
        """
        if self.should_sandbox_all():
            return set()
        if not self.sandbox_skills or not self.sandbox_skills.strip():
            return set()
        return {s.strip() for s in self.sandbox_skills.split(",") if s.strip()}

    def get_allowed_user_ids(self) -> set[str]:
        if not self.allowed_user_ids or self.allowed_user_ids.strip().lower() == "all":
            return set()
        return {uid.strip() for uid in self.allowed_user_ids.split(",") if uid.strip()}

    def resolve_embedding_config(self) -> None:
        """Discover the best available embedding model and update settings in-place.

        This is a one-time startup call.  If ``embedding_model`` is ``"auto"`` we
        query Ollama for a local embedding model.  If none is found (or Ollama is
        unreachable) we fall back to the sentence-transformers Hugging Face
        provider and clear ``embedding_model`` (empty string signals HF).

        Resolved values are also written back to ``os.environ`` so that any
        subsequent ``Settings()`` instance (e.g. in agent tools) inherits the
        correct model name and dimension without needing to be passed around.
        """
        import os
        from pillywiggins.embeddings.resolver import (
            DEFAULT_HF_MODEL,
            discover_ollama_embedding_model,
        )
        from pillywiggins.memory.embeddings import (
            KNOWN_EMBEDDING_DIMENSIONS,
        )

        import logging
        logger = logging.getLogger(__name__)

        if self.embedding_model != "auto":
            # Already explicit — just make sure the dimension is set.
            dim = KNOWN_EMBEDDING_DIMENSIONS.get(self.embedding_model)
            if dim is not None:
                self.embedding_dimension = dim
                os.environ["EMBEDDING_DIMENSION"] = str(dim)
            if self.embedding_model:
                os.environ["EMBEDDING_MODEL"] = self.embedding_model
            if dim is not None:
                logger.info("Explicit embedding model '%s' with dimension %d", self.embedding_model, dim)
            else:
                logger.warning(
                    "Explicit embedding model '%s' has unknown dimension; using default %d",
                    self.embedding_model,
                    self.embedding_dimension,
                )
            return

        # Strip the /v1 suffix from llm_base_url so the Ollama native endpoint works
        base = self.llm_base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        base = base.rstrip("/")

        discovered = None
        try:
            discovered = asyncio.get_event_loop().run_until_complete(
                discover_ollama_embedding_model(ollama_base_url=base)
            )
        except Exception as exc:
            logger.warning("Embedding discovery failed: %s", exc)

        if discovered:
            self.embedding_model = discovered
            os.environ["EMBEDDING_MODEL"] = discovered
            dim = KNOWN_EMBEDDING_DIMENSIONS.get(discovered)
            if dim is not None:
                self.embedding_dimension = dim
                os.environ["EMBEDDING_DIMENSION"] = str(dim)
                logger.info("Discovered Ollama embedding model '%s' (%d-dim)", discovered, dim)
            else:
                logger.info("Discovered Ollama embedding model '%s' (dimension unknown)", discovered)
        else:
            self.embedding_model = ""
            os.environ["EMBEDDING_MODEL"] = ""
            dim = KNOWN_EMBEDDING_DIMENSIONS.get(DEFAULT_HF_MODEL)
            if dim is not None:
                self.embedding_dimension = dim
                os.environ["EMBEDDING_DIMENSION"] = str(dim)
            logger.info(
                "No Ollama embedding model found; falling back to HuggingFace '%s' (%d-dim)",
                DEFAULT_HF_MODEL,
                dim or self.embedding_dimension,
            )


# Top-level settings singleton — constructed lazily so config.py can
# be imported without a valid .env file (e.g. during testing).
# Raises ValidationError on first call if DATABASE_URL / PG_PASSWORD
# not explicitly set in .env.
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
