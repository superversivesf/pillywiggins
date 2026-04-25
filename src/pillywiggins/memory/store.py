import logging
from typing import Optional

import asyncpg
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

logger = logging.getLogger(__name__)


class ConversationStore:
    def __init__(self, database_url: str, agent_id: str, channel: str):
        self._database_url = database_url
        self._agent_id = agent_id
        self._channel = channel
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        async def _init_connection(conn):
            # set_config is the only safe, parameterised way to
            # change a GUC variable via asyncpg.
            await conn.execute(
                "SELECT set_config('app.agent_id', $1, false)",
                self._agent_id,
            )

        self._pool = await asyncpg.create_pool(
            self._database_url,
            init=_init_connection,
            min_size=1,
            max_size=3,
        )
        logger.info("Conversation store connected for agent %s", self._agent_id)

    async def save(self, conversation_key: str, messages: list[ModelMessage]) -> None:
        if self._pool is None:
            return
        try:
            data = ModelMessagesTypeAdapter.dump_json(messages).decode()
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO conversation_cache (agent_id, channel, conversation_key, messages, updated_at)
                       VALUES ($1, $2, $3, $4::jsonb, now())
                       ON CONFLICT (agent_id, channel, conversation_key)
                       DO UPDATE SET messages = $4::jsonb, updated_at = now()""",
                    self._agent_id,
                    self._channel,
                    conversation_key,
                    data,
                )
        except Exception:
            logger.exception("Failed to persist conversation for %s/%s", self._agent_id, conversation_key)

    async def load(self, conversation_key: str) -> Optional[list[ModelMessage]]:
        if self._pool is None:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT messages FROM conversation_cache
                       WHERE agent_id = $1 AND channel = $2 AND conversation_key = $3""",
                    self._agent_id,
                    self._channel,
                    conversation_key,
                )
            if row is None or row["messages"] is None:
                return None
            return ModelMessagesTypeAdapter.validate_json(row["messages"].encode())
        except Exception:
            logger.exception("Failed to load conversation for %s/%s", self._agent_id, conversation_key)
            return None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Conversation store closed for agent %s", self._agent_id)