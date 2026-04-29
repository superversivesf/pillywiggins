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

    async def _get_redis(self) -> Optional[aioredis.Redis]:
        if self._redis is not None:
            try:
                await self._redis.ping()
            except Exception as exc:
                logger.warning("Redis ping failed, resetting connection: %s", exc)
                self._redis = None
        if self._redis is None:
            try:
                self._redis = aioredis.from_url(self._redis_url, decode_responses=False)
            except Exception as exc:
                logger.error("Failed to connect to Redis: %s", exc)
                self._redis = None
        return self._redis

    async def save(self, agent_id: str, messages: list[ModelMessage], conversation_key: str = "") -> None:
        r = await self._get_redis()
        if r is None:
            logger.warning(
                "Conversation cache unavailable; skipping save for %s/%s",
                agent_id,
                conversation_key,
            )
            return
        try:
            data = ModelMessagesTypeAdapter.dump_json(messages)
            key = f"{_KEY_PREFIX}{agent_id}:{conversation_key}" if conversation_key else f"{_KEY_PREFIX}{agent_id}"
            await r.set(key, data, ex=_TTL_SECONDS)
        except Exception:
            logger.exception("Failed to save conversation cache for %s/%s", agent_id, conversation_key)
            self._redis = None

    async def load(self, agent_id: str, conversation_key: str = "") -> Optional[list[ModelMessage]]:
        r = await self._get_redis()
        if r is None:
            logger.debug(
                "Conversation cache unavailable; falling back for %s/%s",
                agent_id,
                conversation_key,
            )
            return None
        try:
            key = f"{_KEY_PREFIX}{agent_id}:{conversation_key}" if conversation_key else f"{_KEY_PREFIX}{agent_id}"
            data = await r.get(key)
            if data is None:
                return None
            return ModelMessagesTypeAdapter.validate_json(data)
        except Exception:
            logger.exception("Failed to load conversation cache for %s/%s", agent_id, conversation_key)
            self._redis = None
            return None

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
