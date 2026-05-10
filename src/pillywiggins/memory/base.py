from __future__ import annotations

import json
import logging

import asyncpg
from pgvector.asyncpg import register_vector

logger = logging.getLogger(__name__)

_DEFAULT_VECTOR_DIMENSION = 768


class PgVectorMemoryBase:
    """Base class for pgvector-backed memory stores.

    Provides the common lifecycle (connect/close), per-connection setup
    (agent_id GUC, vector/JSONB codecs), dimension validation, and a
    delete-by-ID helper.  Subclasses set ``_table_name`` and implement
    their own ``save``/``search``/``write_entry`` methods.
    """

    _table_name: str = ""
    _default_vector_dimension: int = _DEFAULT_VECTOR_DIMENSION

    def __init__(
        self,
        database_url: str,
        agent_id: str,
        embedding_dimension: int | None = None,
    ):
        self._database_url = database_url
        self._agent_id = agent_id
        self._embedding_dimension = embedding_dimension or self._default_vector_dimension
        self._pool: asyncpg.Pool | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def _ensure_agent_id(self, conn: asyncpg.Connection) -> None:
        """Re-apply the agent_id GUC on every connection checkout.

        asyncpg's ``init`` callback only runs when a connection is first
        created inside the pool.  If a connection is returned to the pool
        and later re-used by a different coroutine, the GUC may have been
        reset.  Calling this before every operation guarantees RLS sees the
        correct agent_id.
        """
        await conn.execute(
            "SELECT set_config('app.agent_id', $1, false)",
            self._agent_id,
        )

    async def _on_connect(self, conn: asyncpg.Connection) -> None:
        """Hook for subclasses to run extra per-connection setup.

        Called inside the pool init callback, after vector and JSONB codecs
        are registered and the agent_id GUC is set.  Default is a no-op.
        """

    async def _migrate_embedding_dimension(self, conn: asyncpg.Connection) -> None:
        """Check and migrate embedding column dimension if it differs from runtime config."""
        row = await conn.fetchrow(
            """SELECT atttypmod
               FROM pg_attribute
               WHERE attrelid = $1::regclass
               AND attname = 'embedding'""",
            self._table_name,
        )
        if row is None:
            # Table or column doesn't exist yet; nothing to migrate.
            return
        current_dim = row.get("atttypmod")
        if current_dim is None or current_dim == self._embedding_dimension:
            return
        logger.warning(
            "Migrating %s.embedding from vector(%s) to vector(%s) for agent %s",
            self._table_name, current_dim, self._embedding_dimension, self._agent_id,
        )
        await conn.execute(
            f"ALTER TABLE {self._table_name} ALTER COLUMN embedding TYPE vector({self._embedding_dimension})"
        )

    async def connect(self) -> None:
        async def _init_connection(conn):
            await register_vector(conn)
            # Register JSONB codec so Python dicts are auto-encoded/decoded.
            await conn.set_type_codec(
                'jsonb',
                encoder=json.dumps,
                decoder=json.loads,
                schema='pg_catalog',
            )
            await conn.execute(
                "SELECT set_config('app.agent_id', $1, false)",
                self._agent_id,
            )
            await self._on_connect(conn)

        self._pool = await asyncpg.create_pool(
            self._database_url,
            init=_init_connection,
            min_size=1,
            max_size=5,
        )
        # After pool creation, acquire an owning connection to run dimension migration.
        async with self._pool.acquire() as conn:
            await self._migrate_embedding_dimension(conn)
        logger.info(
            "%s connected for agent %s",
            self.__class__.__name__,
            self._agent_id,
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info(
                "%s closed for agent %s",
                self.__class__.__name__,
                self._agent_id,
            )

    # ------------------------------------------------------------------
    # Dimension validation
    # ------------------------------------------------------------------

    async def _validate_dimension(self, embedding: list[float]) -> bool:
        """Return True if *embedding* matches the expected dimension, False otherwise."""
        if len(embedding) != self._embedding_dimension:
            logger.error(
                "Embedding dimension %d does not match expected dimension %d (agent=%s)",
                len(embedding),
                self._embedding_dimension,
                self._agent_id,
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Delete by ID
    # ------------------------------------------------------------------

    async def delete(self, memory_id: str) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await self._ensure_agent_id(conn)
                result = await conn.execute(
                    f"DELETE FROM {self._table_name} WHERE id = $1::uuid",
                    memory_id,
                )
            return result.endswith("1")
        except Exception:
            logger.exception(
                "%s delete failed for agent %s",
                self.__class__.__name__,
                self._agent_id,
            )
            return False