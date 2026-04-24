import logging
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


class PrivateMemory:
    def __init__(self, database_url: str, agent_id: str):
        self._database_url = database_url
        self._agent_id = agent_id
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        async def _init_connection(conn):
            await conn.execute("SET app.agent_id = $1", self._agent_id)

        self._pool = await asyncpg.create_pool(
            self._database_url,
            init=_init_connection,
            min_size=1,
            max_size=5,
        )
        logger.info("Private memory connected for agent %s", self._agent_id)

    async def save(
        self, content: str, embedding: list[float], metadata: Optional[dict] = None
    ) -> None:
        if self._pool is None:
            logger.error("Private memory not connected, cannot save")
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO private_memory (agent_id, content, embedding, metadata)
                   VALUES ($1, $2, $3::vector, $4)""",
                self._agent_id,
                content,
                embedding,
                metadata or {},
            )

    async def search(self, query_embedding: list[float], limit: int = 5) -> list[dict]:
        if self._pool is None:
            logger.error("Private memory not connected, cannot search")
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, content, metadata, created_at,
                          1 - (embedding <=> $1::vector) AS similarity
                   FROM private_memory
                   ORDER BY embedding <=> $1::vector
                   LIMIT $2""",
                query_embedding,
                limit,
            )
        return [
            {
                "id": str(row["id"]),
                "content": row["content"],
                "metadata": row["metadata"],
                "created_at": row["created_at"].isoformat(),
                "similarity": float(row["similarity"]),
            }
            for row in rows
        ]

    async def delete(self, memory_id: str) -> bool:
        if self._pool is None:
            return False
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM private_memory WHERE id = $1::uuid",
                memory_id,
            )
        return result.endswith("1")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Private memory closed for agent %s", self._agent_id)
