#!/usr/bin/env bash
# Pillywiggins Database Setup
# Creates tables, indexes, and RLS policies for PostgreSQL + pgvector.
#
# Usage:
#   ./scripts/setup-db.sh [DATABASE_URL]
#
# If DATABASE_URL is not provided, reads from the environment variable.

set -euo pipefail

DB_URL="${1:-${DATABASE_URL:?DATABASE_URL is required. Set it as an env var or pass as argument.}}"

echo "Setting up Pillywiggins database schema..."

psql "$DB_URL" <<'SQL'
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- Private Memory (per-agent, RLS-protected)
-- ============================================================
CREATE TABLE IF NOT EXISTS private_memory (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(768),
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_private_memory_agent_id
    ON private_memory (agent_id);

CREATE INDEX IF NOT EXISTS idx_private_memory_embedding
    ON private_memory
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Row-Level Security: agents can only see their own memories
ALTER TABLE private_memory ENABLE ROW LEVEL SECURITY;

CREATE POLICY private_memory_isolation ON private_memory
    USING (agent_id = current_setting('app.agent_id')::text);

-- ============================================================
-- Council Memory (shared read, validated write)
-- ============================================================
CREATE TABLE IF NOT EXISTS council_memory (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contributing_agent TEXT NOT NULL,
    tags              TEXT[] DEFAULT '{}',
    content            TEXT NOT NULL,
    embedding          vector(768),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_council_memory_embedding
    ON council_memory
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ============================================================
-- Conversation Cache (Redis-primary; PG for persistence)
-- ============================================================
CREATE TABLE IF NOT EXISTS conversation_cache (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id         TEXT NOT NULL,
    channel          TEXT NOT NULL,
    conversation_key TEXT NOT NULL,
    messages         JSONB DEFAULT '[]',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (agent_id, channel, conversation_key)
);

CREATE INDEX IF NOT EXISTS idx_conversation_cache_agent_id
    ON conversation_cache (agent_id);

SQL

echo "Done. Schema created successfully."