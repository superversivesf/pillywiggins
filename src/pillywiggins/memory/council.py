import json
import logging
import math
from typing import Optional

import asyncpg
from pgvector.asyncpg import register_vector

from pillywiggins.security.prompt_sanitizer import sanitize_or_default

logger = logging.getLogger(__name__)

VALID_MESSAGE_TYPES = {"insight", "skill_announcement", "question", "proposal", "skill_execution"}

TAG_WHITELIST = {
    "general",
    "idea",
    "observation",
    "question",
    "skill",
    "proposal",
    "announcement",
    "learning",
}

MAX_CONTENT_LENGTH = 2000
RATE_LIMIT_PER_HOUR = 10
DEDUP_SIMILARITY_THRESHOLD = 0.95


class CouncilMemory:
    def __init__(self, database_url: str, agent_id: str, embedding_dimension: int | None = None):
        self._database_url = database_url
        self._agent_id = agent_id
        self._embedding_dimension = embedding_dimension or 768
        self._pool: Optional[asyncpg.Pool] = None

    async def _ensure_agent_id(self, conn: asyncpg.Connection) -> None:
        """Re-apply the agent_id GUC on every connection checkout."""
        await conn.execute(
            "SELECT set_config('app.agent_id', $1, false)",
            self._agent_id,
        )

    async def _migrate_embedding_dimension(self, conn: asyncpg.Connection) -> None:
        """Check and migrate embedding column dimension if it differs from runtime config."""
        row = await conn.fetchrow(
            """SELECT atttypmod
               FROM pg_attribute
               WHERE attrelid = 'council_memory'::regclass
               AND attname = 'embedding'"""
        )
        if row is None:
            # Table or column doesn't exist yet; nothing to migrate.
            return
        current_dim = row.get("atttypmod")
        if current_dim is None or current_dim == self._embedding_dimension:
            return
        logger.warning(
            "Migrating council_memory.embedding from vector(%s) to vector(%s) for agent %s",
            current_dim, self._embedding_dimension, self._agent_id,
        )
        await conn.execute(
            f"ALTER TABLE council_memory ALTER COLUMN embedding TYPE vector({self._embedding_dimension})"
        )

    async def connect(self) -> None:
        async def _init_connection(conn):
            await register_vector(conn)
            # Register JSONB codec so Python dicts/lists are auto-encoded/decoded.
            await conn.set_type_codec(
                'jsonb',
                encoder=json.dumps,
                decoder=json.loads,
                schema='pg_catalog',
            )
            await self._ensure_agent_id(conn)

        self._pool = await asyncpg.create_pool(
            self._database_url,
            init=_init_connection,
            min_size=1,
            max_size=5,
        )
        # After pool creation, acquire an owning connection to run dimension migration.
        async with self._pool.acquire() as conn:
            await self._migrate_embedding_dimension(conn)
        logger.info("Council memory connected for agent %s", self._agent_id)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Council memory closed for agent %s", self._agent_id)

    async def write_entry(
        self,
        content: str,
        tags: list[str],
        embedding: Optional[list[float]],
        message_type: str = "insight",
        confidence: float = 1.0,
    ) -> dict:
        if len(content) > MAX_CONTENT_LENGTH:
            return {
                "success": False,
                "error": f"Content exceeds {MAX_CONTENT_LENGTH} characters",
                "id": None,
            }

        if message_type not in VALID_MESSAGE_TYPES:
            return {
                "success": False,
                "error": f"Invalid message_type: {message_type}",
                "id": None,
            }

        invalid_tags = set(tags) - TAG_WHITELIST
        if invalid_tags:
            return {
                "success": False,
                "error": f"Invalid tags: {invalid_tags}",
                "id": None,
            }

        if self._pool is None:
            return {"success": False, "error": "Not connected", "id": None}

        # Normalize: treat empty lists the same as None (no embedding).
        # This prevents callers that pass embedding=[] from hitting the
        # dimension-mismatch guard — they'll get a NULL-vector row instead.
        if embedding is not None and len(embedding) == 0:
            embedding = None

        # Validate embedding dimension when one is provided.
        # None is allowed — the row will store NULL for the vector column.
        if embedding is not None and len(embedding) != self._embedding_dimension:
            return {
                "success": False,
                "error": f"Embedding dimension {len(embedding)} does not match council_memory column dimension {self._embedding_dimension}",
                "id": None,
            }

        try:
            async with self._pool.acquire() as conn:
                await self._ensure_agent_id(conn)
                count = await conn.fetchval(
                    """SELECT COUNT(*) FROM council_memory
                       WHERE contributing_agent = $1
                       AND created_at >= now() - interval '1 hour'""",
                    self._agent_id,
                )
                if count >= RATE_LIMIT_PER_HOUR:
                    return {
                        "success": False,
                        "error": f"Rate limit exceeded: {RATE_LIMIT_PER_HOUR} writes/hour",
                        "id": None,
                    }

                # Dedup check: only run when we have an embedding to compare against.
                if embedding is not None:
                    recent = await conn.fetch(
                        """SELECT embedding FROM council_memory
                           WHERE contributing_agent = $1
                           AND created_at >= now() - interval '1 hour'
                           ORDER BY created_at DESC
                           LIMIT 50""",
                        self._agent_id,
                    )
                    for row in recent:
                        stored = row["embedding"]
                        sim = self._cosine_similarity(embedding, stored)
                        if sim > DEDUP_SIMILARITY_THRESHOLD:
                            return {
                                "success": False,
                                "error": "Duplicate entry: similarity exceeds threshold",
                                "id": None,
                            }

                if embedding is not None:
                    row = await conn.fetchrow(
                        """INSERT INTO council_memory
                               (contributing_agent, content, tags, embedding, message_type, confidence)
                           VALUES ($1, $2, $3, $4::vector, $5, $6)
                           RETURNING id""",
                        self._agent_id,
                        content,
                        tags,
                        embedding,
                        message_type,
                        confidence,
                    )
                else:
                    # Insert with NULL embedding — entry won't be searchable via
                    # vector similarity but will still be retrievable by tags.
                    row = await conn.fetchrow(
                        """INSERT INTO council_memory
                               (contributing_agent, content, tags, embedding, message_type, confidence)
                           VALUES ($1, $2, $3, NULL, $4, $5)
                           RETURNING id""",
                        self._agent_id,
                        content,
                        tags,
                        message_type,
                        confidence,
                    )
                return {"success": True, "error": None, "id": str(row["id"])}
        except Exception as exc:
            logger.exception("Council memory write_entry failed for agent %s", self._agent_id)
            return {"success": False, "error": str(exc), "id": None}

    async def search(
        self,
        query_embedding: list[float],
        tags: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[dict]:
        if self._pool is None:
            logger.error("Council memory not connected, cannot search")
            return []
        if len(query_embedding) != self._embedding_dimension:
            logger.error(
                "Council memory search rejected: query embedding dimension %d does not match "
                "pgvector column dimension %d (agent=%s)",
                len(query_embedding), self._embedding_dimension, self._agent_id,
            )
            return []
        try:
            async with self._pool.acquire() as conn:
                await self._ensure_agent_id(conn)
                if tags:
                    rows = await conn.fetch(
                        """SELECT id, contributing_agent, content, tags, message_type,
                                  confidence, created_at,
                                  1 - (embedding <=> $1::vector) AS similarity
                           FROM council_memory
                           WHERE embedding IS NOT NULL
                           AND tags && $2::text[]
                           ORDER BY embedding <=> $1::vector
                           LIMIT $3""",
                        query_embedding,
                        tags,
                        limit,
                    )
                else:
                    rows = await conn.fetch(
                        """SELECT id, contributing_agent, content, tags, message_type,
                                  confidence, created_at,
                                  1 - (embedding <=> $1::vector) AS similarity
                           FROM council_memory
                           WHERE embedding IS NOT NULL
                           ORDER BY embedding <=> $1::vector
                           LIMIT $2""",
                        query_embedding,
                        limit,
                    )

            return [
                {
                    "id": str(row["id"]),
                    "contributing_agent": row["contributing_agent"],
                    "content": sanitize_or_default(row["content"], default="[Blocked]"),
                    "tags": list(row["tags"]) if row["tags"] else [],
                    "message_type": row["message_type"],
                    "confidence": float(row["confidence"]),
                    "created_at": row["created_at"].isoformat(),
                    "similarity": float(row["similarity"]) if row["similarity"] is not None else 0.0,
                }
                for row in rows
            ]
        except Exception:
            logger.exception("Council memory search failed for agent %s", self._agent_id)
            return []

    async def delete_entry(self, entry_id: str) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await self._ensure_agent_id(conn)
                result = await conn.execute(
                    "DELETE FROM council_memory WHERE id = $1::uuid",
                    entry_id,
                )
            return result.endswith("1")
        except Exception:
            logger.exception("Council memory delete failed for agent %s", self._agent_id)
            return False

    async def get_entry(self, entry_id: str) -> Optional[dict]:
        if self._pool is None:
            return None
        try:
            async with self._pool.acquire() as conn:
                await self._ensure_agent_id(conn)
                row = await conn.fetchrow(
                    """SELECT id, contributing_agent, content, tags, message_type,
                              confidence, created_at
                       FROM council_memory
                       WHERE id = $1::uuid""",
                    entry_id,
                )
            if row is None:
                return None
            return {
                "id": str(row["id"]),
                "contributing_agent": row["contributing_agent"],
                "content": sanitize_or_default(row["content"], default="[Blocked]"),
                "tags": list(row["tags"]) if row["tags"] else [],
                "message_type": row["message_type"],
                "confidence": float(row["confidence"]),
                "created_at": row["created_at"].isoformat(),
            }
        except Exception:
            logger.exception("Council memory get_entry failed for agent %s", self._agent_id)
            return None

    async def list_entries(self, limit: int = 50, offset: int = 0) -> list[dict]:
        if self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                await self._ensure_agent_id(conn)
                rows = await conn.fetch(
                    """SELECT id, contributing_agent, content, tags, message_type,
                              confidence, created_at
                       FROM council_memory
                       ORDER BY created_at DESC
                       LIMIT $1 OFFSET $2""",
                    limit,
                    offset,
                )
            return [
                {
                    "id": str(row["id"]),
                    "contributing_agent": row["contributing_agent"],
                    "content": sanitize_or_default(row["content"], default="[Blocked]"),
                    "tags": list(row["tags"]) if row["tags"] else [],
                    "message_type": row["message_type"],
                    "confidence": float(row["confidence"]),
                    "created_at": row["created_at"].isoformat(),
                }
                for row in rows
            ]
        except Exception:
            logger.exception("Council memory list_entries failed for agent %s", self._agent_id)
            return []

    @staticmethod
    def _cosine_similarity(a: list[float], b) -> float:
        if not isinstance(b, (list, tuple)):
            raise TypeError(f"Expected list or tuple for vector b, got {type(b).__name__}")
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)