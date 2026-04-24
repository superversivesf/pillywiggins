CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS private_memory (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id          TEXT NOT NULL,
    content           TEXT NOT NULL,
    memory_type       VARCHAR(32) NOT NULL DEFAULT 'episodic',
    embedding         vector(768),
    metadata          JSONB DEFAULT '{}',
    importance        FLOAT DEFAULT 0.5,
    access_count      INTEGER DEFAULT 0,
    last_accessed_at  TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_private_memory_agent_id
    ON private_memory (agent_id);

CREATE INDEX IF NOT EXISTS idx_private_memory_embedding
    ON private_memory
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

ALTER TABLE private_memory ENABLE ROW LEVEL SECURITY;

CREATE POLICY private_memory_isolation ON private_memory
    USING (agent_id = current_setting('app.agent_id')::text);

CREATE TABLE IF NOT EXISTS council_memory (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contributing_agent TEXT NOT NULL,
    tags               TEXT[] DEFAULT '{}',
    content            TEXT NOT NULL,
    embedding          vector(768),
    message_type       VARCHAR(32) NOT NULL DEFAULT 'insight',
    confidence         FLOAT DEFAULT 1.0,
    source_context     JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at         TIMESTAMPTZ,
    superseded_by      UUID REFERENCES council_memory(id)
);

CREATE INDEX IF NOT EXISTS idx_council_memory_embedding
    ON council_memory
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

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