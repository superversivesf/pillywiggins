"""Tests that init-db.sql defines all required spec columns."""

from pathlib import Path

import pytest

INITDB = Path(__file__).parents[1] / "scripts" / "init-db.sql"


@pytest.fixture(scope="module")
def initdb_content():
    return INITDB.read_text()


class TestPrivateMemorySchema:
    TABLE = "private_memory"

    @pytest.fixture(scope="module")
    def table_section(self, initdb_content):
        # Extract the lines for private_memory table
        lines = initdb_content.splitlines()
        start = end = None
        for i, line in enumerate(lines):
            if f"CREATE TABLE IF NOT EXISTS {self.TABLE}" in line:
                start = i
            if start is not None and line.strip() == ");":
                end = i
                break
        assert start is not None, f"Table {self.TABLE} not found"
        assert end is not None, f"Table {self.TABLE} not terminated"
        return "\n".join(lines[start : end + 1])

    def test_has_memory_type(self, table_section):
        assert "memory_type" in table_section, "Missing memory_type column"

    def test_memory_type_defaults_to_null(self, table_section):
        assert "DEFAULT NULL" in table_section, "memory_type should default to NULL (reserved for future use)"

    def test_has_importance(self, table_section):
        assert "importance" in table_section, "Missing importance column"

    def test_importance_defaults_to_null(self, table_section):
        assert "importance" in table_section and "DEFAULT NULL" in table_section, (
            "importance should default to NULL (reserved for future use)"
        )

    def test_has_access_count(self, table_section):
        assert "access_count" in table_section, "Missing access_count column"

    def test_has_last_accessed_at(self, table_section):
        assert "last_accessed_at" in table_section, "Missing last_accessed_at column"


class TestCouncilMemorySchema:
    TABLE = "council_memory"

    @pytest.fixture(scope="module")
    def table_section(self, initdb_content):
        lines = initdb_content.splitlines()
        start = end = None
        for i, line in enumerate(lines):
            if f"CREATE TABLE IF NOT EXISTS {self.TABLE}" in line:
                start = i
            if start is not None and line.strip() == ");":
                end = i
                break
        assert start is not None, f"Table {self.TABLE} not found"
        assert end is not None, f"Table {self.TABLE} not terminated"
        return "\n".join(lines[start : end + 1])

    def test_has_message_type(self, table_section):
        assert "message_type" in table_section, "Missing message_type column"

    def test_message_type_defaults_to_insight(self, table_section):
        assert "DEFAULT 'insight'" in table_section, "message_type should default to 'insight'"

    def test_has_confidence(self, table_section):
        assert "confidence" in table_section, "Missing confidence column"

    def test_confidence_defaults_to_one(self, table_section):
        assert "confidence" in table_section and "1.0" in table_section, (
            "confidence should default to 1.0"
        )

    def test_has_source_context(self, table_section):
        assert "source_context" in table_section, "Missing source_context column"

    def test_has_expires_at(self, table_section):
        assert "expires_at" in table_section, "Missing expires_at column"

    def test_has_superseded_by(self, table_section):
        assert "superseded_by" in table_section, "Missing superseded_by column"

    def test_superseded_by_foreign_key(self, table_section):
        assert "REFERENCES council_memory(id)" in table_section, (
            "superseded_by should reference council_memory(id)"
        )
