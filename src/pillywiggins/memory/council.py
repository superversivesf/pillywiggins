from __future__ import annotations

import logging

from pillywiggins.memory.base import PgVectorMemoryBase
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


class CouncilMemory(PgVectorMemoryBase):
    _table_name = "council_memory"

    async def write_entry(
        self,
        content: str,
        tags: list[str],
        embedding: list[float] | None,
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
            logger.warning("Council memory not connected, cannot write entry")
            return {"success": False, "error": "Not connected", "id": None}

        # Normalize: treat empty lists the same as None (no embedding).
        # This prevents callers that pass embedding=[] from hitting the
        # dimension-mismatch guard — they'll get a NULL-vector row instead.
        if embedding is not None and len(embedding) == 0:
            embedding = None

        # Validate embedding dimension when one is provided.
        # None is allowed — the row will store NULL for the vector column.
        if embedding is not None and not await self._validate_dimension(embedding):
            return {
                "success": False,
                "error": f"Embedding dimension {len(embedding)} does not match {self._table_name} column dimension {self._embedding_dimension}",
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

                # Dedup check: use pgvector's cosine distance operator (<=>)
                # to push similarity comparison into the database.
                # cosine similarity > 0.95  <=>  cosine distance < 0.05
                if embedding is not None:
                    dup_distance = await conn.fetchval(
                        """SELECT MIN(embedding <=> $1::vector)
                           FROM council_memory
                           WHERE contributing_agent = $2
                           AND created_at >= now() - interval '1 hour'
                           AND embedding IS NOT NULL""",
                        embedding,
                        self._agent_id,
                    )
                    if dup_distance is not None and dup_distance < (1 - DEDUP_SIMILARITY_THRESHOLD):
                        return {
                            "success": False,
                            "error": "Duplicate entry: similarity exceeds threshold",
                            "id": None,
                        }

                # Single INSERT: asyncpg passes Python None as SQL NULL, and
                # NULL::vector is valid in PostgreSQL, so both the with-embedding
                # and without-embedding branches collapse into one parameterised
                # statement.
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
                return {"success": True, "error": None, "id": str(row["id"])}
        except Exception as exc:
            logger.exception("Council memory write_entry failed for agent %s", self._agent_id)
            return {"success": False, "error": str(exc), "id": None}

    async def search(
        self,
        query_embedding: list[float],
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        if self._pool is None:
            logger.warning("Council memory not connected, cannot search")
            return []
        if not await self._validate_dimension(query_embedding):
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
        """Delete a council memory entry by ID. Alias for :meth:`delete`."""
        return await self.delete(entry_id)

    async def get_entry(self, entry_id: str) -> dict | None:
        if self._pool is None:
            logger.warning("Council memory not connected, cannot get entry")
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
            logger.warning("Council memory not connected, cannot list entries")
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