from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ChannelType(str, Enum):
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    MATRIX = "matrix"
    EMAIL = "email"


@dataclass
class UnifiedMessage:
    channel: ChannelType
    channel_user_id: str
    content: str
    conversation_key: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)