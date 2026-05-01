# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Memory consistency (Phase 2)** — Dimension validation for pgvector embeddings; native list vector binding for `asyncpg`; NULL-embedding filter to skip un-vectorized rows; similarity scores returned with search results; composite index on `(agent_id, created_at)` for faster private-memory pagination.
- **NATS reliability (Phase 3)** — Consumer-level retry limit (`ConsumerConfig(max_deliver=3)`); JSON serialization now handles non-serializable types via `json.dumps(default=str)`; broadcast failures are logged with NATS status codes; direct-message replies are routed back to the originating agent.
- **Skills robustness (Phase 4)** — Hot-reload file watcher for the shared `skills/` volume; atomic `registry.json` writes via temp-file + rename; disk reconciliation to keep the in-memory registry in sync with the volume; coroutine validation on `SkillRegistry.run()`; `load_errors` surfaced in health/metadata endpoints; new skills are published with `chmod 644` so all agents can read them.
- **Polish (Phase 5)** — `ivfflat` index upgraded to `hnsw` for better recall/performance; `HEALTH_PORT` configurable from environment; Docker healthchecks use `start_period: 30s`; exposed ports restricted to `127.0.0.1` in Compose template.

### Changed

- **Enable subsystems (Phase 1)** — Skills volume changed from Docker named volume to bind mount so local edits are reflected immediately; `PillywigginAgent` now accepts `database_url` and `nats_url` explicitly instead of relying on global defaults.
- **Memory consistency (Phase 2)** — Error contracts aligned between `private.py` and `council.py` so callers see consistent exception types; RLS policies now use explicit `WITH CHECK` clauses in addition to `USING`.
- **NATS reliability (Phase 3)** — Stream existence is checked via `stream_info()` before creation to avoid duplicate-declaration races.
- **Polish (Phase 5)** — Unused pgvector columns now default to `DEFAULT NULL` to avoid schema-drift issues during rolling restarts.

### Fixed

- **Enable subsystems (Phase 1)** — Fixed `PillywigginAgent` missing `database_url`/`nats_url` arguments; removed SearXNG hard-dependency so the agent starts cleanly without a search backend; fixed stale `is_connected` flag that could stick to `True` after a disconnect; brain tools are refreshed automatically when a `skill_published` event is received.
- **NATS reliability (Phase 3)** — Removed duplicate `subs.clear()` that could drop legitimate subscriptions during reconnection.
- **Skills robustness (Phase 4)** — `SkillRegistry.run()` now validates that the target coroutine is still importable before execution.
- **Polish (Phase 5)** — Removed brittle string-parsing fallback in `cosine_similarity` that produced incorrect scores when embeddings were stored as text.

### Removed

- **Enable subsystems (Phase 1)** — SearXNG hard-dependency removed from agent startup path.
- **Polish (Phase 5)** — `extra_hosts` removed from Docker Compose template (no longer needed with bind-mount networking).

### Breaking Changes

- **Database schema:** The pgvector index type changed from `ivfflat` to `hnsw`. Existing installations must drop the old index and recreate it. See Migration Steps below.

### Migration Steps for Operators

1. Back up your PostgreSQL data.
2. Connect to the database and run:
   ```sql
   DROP INDEX IF EXISTS idx_private_memory_embedding_ivfflat;
   DROP INDEX IF EXISTS idx_council_memory_embedding_ivfflat;
   ```
3. Recreate the indexes with the new type:
   ```sql
   CREATE INDEX idx_private_memory_embedding_hnsw
     ON private_memory USING hnsw (embedding vector_cosine_ops);

   CREATE INDEX idx_council_memory_embedding_hnsw
     ON council_memory USING hnsw (embedding vector_cosine_ops);
   ```
4. Restart the agent containers (`docker compose restart`) so they pick up the new `HEALTH_PORT` and bind-mount paths.
5. Verify health via `curl http://127.0.0.1:${HEALTH_PORT}/health` on each agent host.

### Stats

- **Files changed:** 15
- **Lines added:** +574
- **Lines removed:** −193

## [0.1.0] - 2026-05-01

### Added

- Initial release of Pillywiggins — a council of AI agents with per-channel adapters, shared skills, private/council memory, and NATS-based inter-agent messaging.
