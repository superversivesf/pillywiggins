import json
import logging
from typing import Optional

import asyncpg
from pgvector.asyncpg import register_vector

from pillywiggins.config import Settings
from pillywiggins.security.prompt_sanitizer import sanitize_or_default

logger = logging.getLogger(__name__)

# Default dimension — must match the pgvector column width defined in init-db.sql.
# Overridden by Settings.embedding_dimension when available.
_DEFAULT_VECTOR_DIMENSION = 768


class PrivateMemory:
    def __init__(self, database_url: str, agent_id: str, embedding_dimension: int | None = None):
        self._database_url = database_url
        self._agent_id = agent_id
        self._embedding_dimension = embedding_dimension or _DEFAULT_VECTOR_DIMENSION
        self._pool: Optional[asyncpg.Pool] = None

    async def _ensure_agent_id(self, conn: asyncpg.Connection) -> None:
        """Re-apply the agent_id GUC on every connection checkout.

        asyncpg's `init` callback only runs when a connection is first
        created inside the pool.  If a connection is returned to the pool
        and later re-used by a different coroutine, the GUC may have been
        reset.  Calling this before every operation guarantees RLS sees the
        correct agent_id.
        """
        await conn.execute(
            "SELECT set_config('app.agent_id', $1, false)",
            self._agent_id,
        )

    async def _migrate_embedding_dimension(self, conn: asyncpg.Connection) -> None:
        """Check and migrate embedding column dimension if it differs from runtime config."""
        row = await conn.fetchrow(
            """SELECT atttypmod
               FROM pg_attribute
               WHERE attrelid = 'private_memory'::regclass
               AND attname = 'embedding'"""
        )
        if row is None:
            # Table or column doesn't exist yet; nothing to migrate.
            return
        current_dim = row.get("atttypmod")
        if current_dim is None or current_dim == self._embedding_dimension:
            return
        logger.warning(
            "Migrating private_memory.embedding from vector(%s) to vector(%s) for agent %s",
            current_dim, self._embedding_dimension, self._agent_id,
        )
        await conn.execute(
            f"ALTER TABLE private_memory ALTER COLUMN embedding TYPE vector({self._embedding_dimension})"
        )

    async def connect(self) -> None:
        async def _init_connection(conn):
            await register_vector(conn)
            # Register JSONB codec so Python dicts are auto-encoded/decoded.
            await conn.set_type_codec(
                'jsonb',
                encoder=json.dumps,
                decoder=json.loads,
                schema='pg_catalog'
            )
            await conn.execute(
                "SELECT set_config('app.agent_id', $1, false)",
                self._agent_id,
            )

        self._pool = await asyncpg.create_pool(
            self._database_url,
            init=_init_connection,
            min_size=1,
            max_size=5,
        )
        # After pool creation, acquire an owning connection to run dimension migration.
        async with self._pool.acquire() as conn:
            await self._migrate_embedding_dimension(conn)
        logger.info("Private memory connected for agent %s", self._agent_id)

    async def save(
        self, content: str, embedding: list[float], metadata: Optional[dict] = None
    ) -> bool:
        """Save a memory row for this agent, returning True on success."""
        if self._pool is None:
            logger.error("Private memory not connected, cannot save")
            return False
        if len(embedding) != self._embedding_dimension:
            logger.error(
                "Private memory save rejected: embedding dimension %d does not match "
                "pgvector column dimension %d (agent=%s, content=%r)",
                len(embedding), self._embedding_dimension, self._agent_id, content[:100],
            )
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
            logger.error("Private memory not connected, cannot search")
            return []
        if len(query_embedding) != self._embedding_dimension:
            logger.error(
                "Private memory search rejected: query embedding dimension %d does not match "
                "pgvector column dimension %d (agent=%s)",
                len(query_embedding), self._embedding_dimension, self._agent_id,
            )
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

    async def delete(self, memory_id: str) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await self._ensure_agent_id(conn)
                result = await conn.execute(
                    "DELETE FROM private_memory WHERE id = $1::uuid",
                    memory_id,
                )
            return result.endswith("1")
        except Exception:
            logger.exception("Private memory delete failed for agent %s", self._agent_id)
            return False

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Private memory closed for agent %s", self._agent_id)
