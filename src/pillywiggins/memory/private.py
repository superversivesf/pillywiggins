from __future__ import annotations

import logging

from pillywiggins.memory.base import PgVectorMemoryBase
from pillywiggins.security.prompt_sanitizer import sanitize_or_default

logger = logging.getLogger(__name__)


class PrivateMemory(PgVectorMemoryBase):
    _table_name = "private_memory"

    async def save(
        self, content: str, embedding: list[float], metadata: dict | None = None
    ) -> bool:
        """Save a memory row for this agent, returning True on success."""
        if self._pool is None:
            logger.warning("Private memory not connected, cannot save")
            return False
        if not await self._validate_dimension(embedding):
            return False
        try:
            async with self._pool.acquire() as conn:
                await self._ensure_agent_id(conn)
                await conn.execute(
                    """INSERT INTO private_memory (agent_id, content, embedding, metadata)
                       VALUES ($1, $2, $3::vector, $4::jsonb)""",
                    self._agent_id,
                    content,
                    embedding,
                    metadata or {},
                )
            return True
        except Exception:
            logger.exception("Private memory save failed for agent %s", self._agent_id)
            return False

    async def search(self, query_embedding: list[float], limit: int = 5) -> list[dict]:
        if self._pool is None:
            logger.warning("Private memory not connected, cannot search")
            return []
        if not await self._validate_dimension(query_embedding):
            return []
        try:
            async with self._pool.acquire() as conn:
                await self._ensure_agent_id(conn)
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
                    "content": sanitize_or_default(row["content"], default="[Blocked]"),
                    "metadata": row["metadata"],
                    "created_at": row["created_at"].isoformat(),
                    "similarity": float(row["similarity"]) if row["similarity"] is not None else 0.0,
                }
                for row in rows
            ]
        except Exception:
            logger.exception("Private memory search failed for agent %s", self._agent_id)
            return []

    async def prune_by_age(self, retention_days: int) -> int:
        """Delete entries older than retention_days. Returns count deleted."""
        if self._pool is None:
            return 0
        async with self._pool.acquire() as conn:
            await self._ensure_agent_id(conn)
            result = await conn.execute(
                f"DELETE FROM {self._table_name} WHERE created_at < NOW() - INTERVAL '{retention_days} days'"
            )
            deleted = int(result.split("DELETE ")[-1]) if "DELETE" in result else 0
            if deleted:
                logger.info("Pruned %d old memories for agent %s", deleted, self._agent_id)
            return deleted

    async def prune_to_max(self, max_rows: int) -> int:
        """Keep only the most recent max_rows entries. Returns count deleted."""
        if self._pool is None:
            return 0
        async with self._pool.acquire() as conn:
            await self._ensure_agent_id(conn)
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {self._table_name}")
            if count <= max_rows:
                return 0
            result = await conn.execute(
                f"DELETE FROM {self._table_name} WHERE id IN ("
                f"  SELECT id FROM {self._table_name} ORDER BY created_at ASC "
                f"  LIMIT GREATEST(0, (SELECT COUNT(*) FROM {self._table_name}) - {max_rows})"
                f")"
            )
            deleted = int(result.split("DELETE ")[-1]) if "DELETE" in result else 0
            if deleted:
                logger.info("Pruned %d memories to stay under limit of %d for agent %s", deleted, max_rows, self._agent_id)
            return deleted