import json
import os
from pathlib import Path
from dataclasses import dataclass, field

CONFIG_PATH = Path(".blackbox_config.json")


@dataclass
class BlackboxConfig:
    ai_endpoint_url: str = "http://localhost:11434/v1"
    ai_model: str = "qwen3.5:8b"
    test_telegram_token: str = ""
    agent_tokens: dict[str, str] = field(default_factory=dict)
    personality_mapping: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | str = CONFIG_PATH) -> "BlackboxConfig":
        path = Path(path)
        if path.exists():
            data = json.loads(path.read_text())
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        return cls()

    def save(self, path: Path | str = CONFIG_PATH) -> None:
        path = Path(path)
        path.write_text(json.dumps(self.__dict__, indent=2))

    @classmethod
    def from_env(cls) -> "BlackboxConfig":
        cfg = cls()
        if os.getenv("BB_AI_ENDPOINT"):
            cfg.ai_endpoint_url = os.getenv("BB_AI_ENDPOINT", "")
        if os.getenv("BB_AI_MODEL"):
            cfg.ai_model = os.getenv("BB_AI_MODEL", "")
        if os.getenv("BB_TG_TOKEN"):
            cfg.test_telegram_token = os.getenv("BB_TG_TOKEN", "")
        return cfg
