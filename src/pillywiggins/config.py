from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    agent_id: str = "puck"
    channel: str = "telegram"
    personality_file: str = "/config/puck.yaml"
    database_url: str = "postgresql://pillywiggins:changeme@postgres:5432/pillywiggins"
    pg_password: str = "changeme"
    redis_url: str = "redis://redis:6379/0"
    nats_url: str = "nats://nats:4222"
    llm_provider: str = "ollama"
    llm_base_url: str = "http://host.docker.internal:11434/v1"
    llm_api_key: str = ""
    model_name: str = "qwen3.5:8b"
    embedding_model: str = "nomic-embed-text"
    telegram_bot_token: str = ""
    discord_bot_token: str = ""
    compact_keep_messages: int = 6
    compact_truncate_message_chars: int = 2000
    allowed_user_ids: str = ""
    skills_dir: str = "/app/skills"
    sandbox_skills: str = ""
    scheduler_enabled: bool = True
    searxng_url: str = "http://searxng:8080"
    searxng_categories: str = "general"
    searxng_max_results: int = 5
    agents_config_path: str = "agents.yaml"
    timezone: str = "UTC"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    def get_searxng_categories(self) -> list[str]:
        if not self.searxng_categories or self.searxng_categories.strip().lower() == "all":
            return []
        return [c.strip() for c in self.searxng_categories.split(",") if c.strip()]

    def should_sandbox_all(self) -> bool:
        val = self.sandbox_skills.strip().lower() if self.sandbox_skills else ""
        return val in ("true", "1", "yes", "all")

    def get_sandbox_skill_names(self) -> set[str]:
        if not self.sandbox_skills or not self.sandbox_skills.strip():
            return set()
        if self.should_sandbox_all():
            return set()
        return {s.strip() for s in self.sandbox_skills.split(",") if s.strip()}

    def get_allowed_user_ids(self) -> set[int]:
        if not self.allowed_user_ids or self.allowed_user_ids.strip().lower() == "all":
            return set()
        return {int(uid.strip()) for uid in self.allowed_user_ids.split(",") if uid.strip()}
