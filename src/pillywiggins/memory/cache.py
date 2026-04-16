import logging
from typing import Optional

import redis.asyncio as aioredis
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

logger = logging.getLogger(__name__)

_TTL_SECONDS = 1800
_KEY_PREFIX = "conversation:"


class ConversationCache:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=False)
        return self._redis

    async def save(self, agent_id: str, messages: list[ModelMessage], conversation_key: str = "") -> None:
        try:
            r = await self._get_redis()
            data = ModelMessagesTypeAdapter.dump_json(messages)
            key = f"{_KEY_PREFIX}{agent_id}:{conversation_key}" if conversation_key else f"{_KEY_PREFIX}{agent_id}"
            await r.set(key, data, ex=_TTL_SECONDS)
        except Exception:
            logger.exception("Failed to save conversation cache for %s/%s", agent_id, conversation_key)

    async def load(self, agent_id: str, conversation_key: str = "") -> Optional[list[ModelMessage]]:
        try:
            r = await self._get_redis()
            key = f"{_KEY_PREFIX}{agent_id}:{conversation_key}" if conversation_key else f"{_KEY_PREFIX}{agent_id}"
            data = await r.get(key)
            if data is None:
                return None
            return ModelMessagesTypeAdapter.validate_json(data)
        except Exception:
            logger.exception("Failed to load conversation cache for %s/%s", agent_id, conversation_key)
            return None

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()
            self._redis = None