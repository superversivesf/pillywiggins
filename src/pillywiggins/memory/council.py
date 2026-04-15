import logging
import math
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

VALID_MESSAGE_TYPES = {"insight", "skill_announcement", "question", "proposal"}

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
    def __init__(self, database_url: str, agent_id: str):
        self._database_url = database_url
        self._agent_id = agent_id
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._database_url,
            min_size=1,
            max_size=5,
        )
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
        embedding: list[float],
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

        async with self._pool.acquire() as conn:
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

            row = await conn.fetchrow(
                """INSERT INTO council_memory
                       (contributing_agent, content, tags, embedding, message_type, confidence)
                   VALUES ($1, $2, $3, $4::vector, $5, $6)
                   RETURNING id""",
                self._agent_id,
                content,
                tags,
                str(embedding),
                message_type,
                confidence,
            )
            return {"success": True, "error": None, "id": str(row["id"])}

    async def search(
        self,
        query_embedding: list[float],
        tags: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[dict]:
        if self._pool is None:
            logger.error("Council memory not connected, cannot search")
            return []

        async with self._pool.acquire() as conn:
            if tags:
                rows = await conn.fetch(
                    """SELECT id, contributing_agent, content, tags, message_type,
                              confidence, created_at
                       FROM council_memory
                       WHERE tags && $1::text[]
                       ORDER BY embedding <=> $2::vector
                       LIMIT $3""",
                    tags,
                    str(query_embedding),
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT id, contributing_agent, content, tags, message_type,
                              confidence, created_at
                       FROM council_memory
                       ORDER BY embedding <=> $1::vector
                       LIMIT $2""",
                    str(query_embedding),
                    limit,
                )

        return [
            {
                "id": str(row["id"]),
                "contributing_agent": row["contributing_agent"],
                "content": row["content"],
                "tags": list(row["tags"]) if row["tags"] else [],
                "message_type": row["message_type"],
                "confidence": float(row["confidence"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    async def delete_entry(self, entry_id: str) -> bool:
        if self._pool is None:
            return False
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM council_memory WHERE id = $1::uuid",
                entry_id,
            )
        return result.endswith("1")

    async def get_entry(self, entry_id: str) -> Optional[dict]:
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
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
            "content": row["content"],
            "tags": list(row["tags"]) if row["tags"] else [],
            "message_type": row["message_type"],
            "confidence": float(row["confidence"]),
            "created_at": row["created_at"].isoformat(),
        }

    async def list_entries(self, limit: int = 50, offset: int = 0) -> list[dict]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
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
                "content": row["content"],
                "tags": list(row["tags"]) if row["tags"] else [],
                "message_type": row["message_type"],
                "confidence": float(row["confidence"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    @staticmethod
    def _cosine_similarity(a: list[float], b) -> float:
        if isinstance(b, str):
            b = [float(x) for x in b.strip("[]").split(",") if x.strip()]
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)