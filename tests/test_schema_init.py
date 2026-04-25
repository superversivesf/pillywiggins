"""Integration test: apply DB schema against a real PostgreSQL instance and verify structure."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

INIT_SQL = Path(__file__).parents[1] / "scripts" / "init-db.sql"
SETUP_SH = Path(__file__).parents[1] / "scripts" / "setup-db.sh"

# Tables defined in the canonical schema (scripts/init-db.sql)
EXPECTED_TABLES = {
    "private_memory",
    "council_memory",
    "conversation_cache",
}

# Tables that must have RLS enabled
RLS_TABLES = {
    "private_memory",
    "conversation_cache",
}

# RLS policy names that must exist
EXPECTED_POLICIES = {
    "private_memory_isolation",
    "conversation_cache_isolation",
}

# Indexes that must exist
EXPECTED_INDEXES = {
    "idx_private_memory_agent_id",
    "idx_private_memory_embedding",
    "idx_council_memory_embedding",
    "idx_conversation_cache_agent_id",
}


@pytest.fixture(scope="session")
def schema_sql():
    """Load the canonical schema from scripts/init-db.sql."""
    if not INIT_SQL.exists():
        pytest.skip(f"Schema file not found: {INIT_SQL}")
    return INIT_SQL.read_text()


@pytest.fixture(scope="function")
def fresh_db(postgresql, schema_sql):
    """
    Apply the schema to the test database.
    pytest-postgresql provides the `postgresql` fixture which yields a
    live PostgreSQL client connected to a temporary database.
    """
    conn: psycopg.Connection = postgresql
    with conn.cursor() as cur:
        cur.execute(schema_sql)
    conn.commit()
    return conn


class TestSchemaInit:
    """Verify that applying scripts/init-db.sql creates the expected structure."""

    def test_vector_extension_installed(self, fresh_db):
        with fresh_db.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = %s", ("vector",))
            assert cur.fetchone() is not None, "pgvector extension is not installed"

    def test_expected_tables_exist(self, fresh_db):
        with fresh_db.cursor() as cur:
            cur.execute(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                """
            )
            tables = {row[0] for row in cur.fetchall()}
        missing = EXPECTED_TABLES - tables
        assert not missing, f"Missing tables: {missing}"

    def test_rls_enabled(self, fresh_db):
        with fresh_db.cursor() as cur:
            cur.execute(
                """
                SELECT relname
                FROM pg_class
                WHERE relrowsecurity = true
                  AND relnamespace = 'public'::regnamespace;
                """
            )
            rls_tables = {row[0] for row in cur.fetchall()}
        missing = RLS_TABLES - rls_tables
        assert not missing, f"RLS not enabled for tables: {missing}"

    def test_rls_policies_exist(self, fresh_db):
        with fresh_db.cursor() as cur:
            cur.execute(
                """
                SELECT policyname
                FROM pg_policies
                WHERE schemaname = 'public';
                """
            )
            policies = {row[0] for row in cur.fetchall()}
        missing = EXPECTED_POLICIES - policies
        assert not missing, f"Missing RLS policies: {missing}"

    def test_isolation_policies_contain_agent_check(self, fresh_db):
        with fresh_db.cursor() as cur:
            cur.execute(
                """
                SELECT policyname, qual::text
                FROM pg_policies
                WHERE schemaname = 'public'
                  AND policyname LIKE '%isolation%';
                """
            )
            rows = cur.fetchall()
        assert len(rows) >= 2, f"Expected at least 2 isolation policies, got {len(rows)}"
        for policy_name, qual in rows:
            assert (
                "current_setting" in qual and "app.agent_id" in qual
            ), f"Policy {policy_name} does not reference current_setting('app.agent_id')"

    def test_expected_indexes_exist(self, fresh_db):
        with fresh_db.cursor() as cur:
            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public';
                """
            )
            indexes = {row[0] for row in cur.fetchall()}
        missing = EXPECTED_INDEXES - indexes
        assert not missing, f"Missing indexes: {missing}"

    def test_private_memory_columns(self, fresh_db):
        with fresh_db.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'private_memory';
                """
            )
            cols = {row[0] for row in cur.fetchall()}
        expected = {
            "id",
            "agent_id",
            "content",
            "memory_type",
            "embedding",
            "metadata",
            "importance",
            "access_count",
            "last_accessed_at",
            "created_at",
            "updated_at",
        }
        missing = expected - cols
        assert not missing, f"Missing columns in private_memory: {missing}"

    def test_council_memory_columns(self, fresh_db):
        with fresh_db.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'council_memory';
                """
            )
            cols = {row[0] for row in cur.fetchall()}
        expected = {
            "id",
            "contributing_agent",
            "tags",
            "content",
            "embedding",
            "message_type",
            "confidence",
            "source_context",
            "created_at",
            "expires_at",
            "superseded_by",
        }
        missing = expected - cols
        assert not missing, f"Missing columns in council_memory: {missing}"

    def test_conversation_cache_columns(self, fresh_db):
        with fresh_db.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'conversation_cache';
                """
            )
            cols = {row[0] for row in cur.fetchall()}
        expected = {
            "id",
            "agent_id",
            "channel",
            "conversation_key",
            "messages",
            "updated_at",
        }
        missing = expected - cols
        assert not missing, f"Missing columns in conversation_cache: {missing}"


class TestSetupDbScript:
    """
    Verify that scripts/setup-db.sh executes without error and produces
    the same structural result as init-db.sql.
    
    We run the SQL embedded in setup-db.sh (lines between the heredoc markers)
    against a fresh database so the test is deterministic without relying on
    shell execution.
    """

    @pytest.fixture(scope="module")
    def setup_db_sql(self):
        if not SETUP_SH.exists():
            pytest.skip(f"setup-db.sh not found: {SETUP_SH}")
        text = SETUP_SH.read_text()
        start = text.find("<<'SQL'")
        end = text.rfind("SQL")
        if start == -1 or end == -1 or end <= start:
            pytest.skip("Could not locate SQL heredoc in setup-db.sh")
        # Extract SQL between heredoc start and final closing SQL marker
        sql = text[start + len("<<'SQL'") : end].strip()
        return sql

    @pytest.fixture(scope="function")
    def fresh_db_from_setup(self, postgresql, setup_db_sql):
        conn: psycopg.Connection = postgresql
        with conn.cursor() as cur:
            cur.execute(setup_db_sql)
        conn.commit()
        return conn

    def test_vector_extension_installed(self, fresh_db_from_setup):
        with fresh_db_from_setup.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = %s", ("vector",))
            assert cur.fetchone() is not None

    def test_tables_exist(self, fresh_db_from_setup):
        with fresh_db_from_setup.cursor() as cur:
            cur.execute(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                """
            )
            tables = {row[0] for row in cur.fetchall()}
        missing = EXPECTED_TABLES - tables
        assert not missing, f"Missing tables from setup-db.sh: {missing}"

    def test_rls_enabled(self, fresh_db_from_setup):
        with fresh_db_from_setup.cursor() as cur:
            cur.execute(
                """
                SELECT relname
                FROM pg_class
                WHERE relrowsecurity = true
                  AND relnamespace = 'public'::regnamespace;
                """
            )
            rls_tables = {row[0] for row in cur.fetchall()}
        missing = RLS_TABLES - rls_tables
        assert not missing, f"RLS not enabled after setup-db.sh: {missing}"

    def test_policies_exist(self, fresh_db_from_setup):
        with fresh_db_from_setup.cursor() as cur:
            cur.execute(
                """
                SELECT policyname
                FROM pg_policies
                WHERE schemaname = 'public';
                """
            )
            policies = {row[0] for row in cur.fetchall()}
        missing = EXPECTED_POLICIES - policies
        assert not missing, f"Missing policies after setup-db.sh: {missing}"
