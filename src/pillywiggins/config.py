from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    agent_id: str = "puck"
    channel: str = "telegram"
    personality_file: str = "/config/telegram.yaml"
    database_url: str = "postgresql://pillywiggins:changeme@postgres:5432/pillywiggins"
    pg_password: str = "changeme"
    redis_url: str = "redis://redis:6379/0"
    nats_url: str = "nats://nats:4222"
    llm_provider: str = "ollama"
    llm_base_url: str = "http://localhost:11434"
    llm_api_key: str = ""
    model_name: str = "qwen3.5:8b"
    embedding_model: str = "nomic-embed-text"
    telegram_bot_token: str = ""
    compact_keep_messages: int = 6
    compact_truncate_message_chars: int = 2000
    allowed_user_ids: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def get_allowed_user_ids(self) -> set[int]:
        if not self.allowed_user_ids:
            return set()
        return {int(uid.strip()) for uid in self.allowed_user_ids.split(",") if uid.strip()}