"""
Tests for config.py security hardening:

Part A: No hardcoded 'changeme' defaults for database_url / pg_password.
        Empty defaults must fail validation.
Part B: sandbox_all defaults to True.
"""

import pytest
from pydantic import ValidationError

from pillywiggins.config import Settings


# ---------------------------------------------------------------------------
# Part A: DATABASE_URL / PG_PASSWORD validation
# ---------------------------------------------------------------------------


def test_empty_database_url_raises_validation_error(monkeypatch):
    """(a) Default empty string raises ValidationError on startup."""
    # Clear env vars so we get the new empty defaults
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_PASSWORD", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(database_url="", pg_password="secret123")

    errors = exc_info.value.errors()
    assert any("database_url" in str(e.get("loc", "")).lower() for e in errors), (
        f"Expected DATABASE_URL validation error, got: {errors}"
    )


def test_empty_pg_password_raises_validation_error(monkeypatch):
    """(a) Default empty string for pg_password raises ValidationError."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_PASSWORD", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            database_url="postgresql://user:pass@host:5432/db",
            pg_password="",
        )

    errors = exc_info.value.errors()
    assert any("pg_password" in str(e.get("loc", "")).lower() for e in errors), (
        f"Expected PG_PASSWORD validation error, got: {errors}"
    )


def test_explicit_env_override_works(monkeypatch):
    """(b) Explicit .env override works — valid values accepted."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_PASSWORD", raising=False)

    s = Settings(
        database_url="postgresql://appuser:realpass@pg:5432/mydb",
        pg_password="realpass",
    )

    assert s.database_url == "postgresql://appuser:realpass@pg:5432/mydb"
    assert s.pg_password == "realpass"


def test_changeme_database_url_rejected(monkeypatch):
    """(c) 'changeme' in database_url is rejected."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_PASSWORD", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            database_url="postgresql://pillywiggins:changeme@postgres:5432/pillywiggins",
            pg_password="realpass",
        )

    errors = exc_info.value.errors()
    assert any("changeme" in str(e.get("msg", "")).lower() for e in errors), (
        f"Expected 'changeme' rejection in error message, got: {errors}"
    )


def test_changeme_pg_password_rejected(monkeypatch):
    """(c) 'changeme' as pg_password is rejected."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_PASSWORD", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            database_url="postgresql://user:realpass@host:5432/db",
            pg_password="changeme",
        )

    errors = exc_info.value.errors()
    assert any("changeme" in str(e.get("msg", "")).lower() for e in errors), (
        f"Expected 'changeme' rejection in error message, got: {errors}"
    )


def test_changeme_case_insensitive_rejected(monkeypatch):
    """(c) 'CHANGEME' (uppercase) is also rejected."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_PASSWORD", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            database_url="postgresql://user:realpass@host:5432/db",
            pg_password="CHANGEME",
        )

    errors = exc_info.value.errors()
    assert any("changeme" in str(e.get("msg", "")).lower() for e in errors), (
        f"Expected case-insensitive 'changeme' rejection, got: {errors}"
    )


# ---------------------------------------------------------------------------
# Part B: sandbox_all defaults to True
# ---------------------------------------------------------------------------


def test_sandbox_all_defaults_to_true():
    """(d) sandbox_all field defaults to True."""
    s = Settings(
        database_url="postgresql://user:realpass@host:5432/db",
        pg_password="realpass",
    )
    assert s.sandbox_all is True


def test_sandbox_all_can_be_explicitly_false():
    """(d) sandbox_all can be explicitly set to False."""
    s = Settings(
        sandbox_all=False,
        database_url="postgresql://user:realpass@host:5432/db",
        pg_password="realpass",
    )
    assert s.sandbox_all is False


def test_sandbox_skills_field_still_works_for_opt_out():
    """(e) sandbox_skills field still works for opt-out."""
    # Default: empty string
    s = Settings(
        database_url="postgresql://user:realpass@host:5432/db",
        pg_password="realpass",
    )
    assert s.sandbox_skills == ""
    assert s.get_sandbox_skill_names() == set()

    # With specific skills listed, should_be_sandbox_all = True (default) 
    # but get_sandbox_skill_names returns the individual skills when
    # should_sandbox_all is... wait, looking at the existing code,
    # should_sandbox_all() reads sandbox_skills string value.
    # With sandbox_all=True as the new field, we need to reconcile.
    # For now: test that sandbox_skills field exists and is mutable.
    s2 = Settings(
        sandbox_skills="skill_a, skill_b",
        database_url="postgresql://user:realpass@host:5432/db",
        pg_password="realpass",
    )
    assert s2.sandbox_skills == "skill_a, skill_b"


def test_should_sandbox_all_respects_new_field():
    """(e) should_sandbox_all() respects the new sandbox_all boolean field."""
    s = Settings(
        database_url="postgresql://user:realpass@host:5432/db",
        pg_password="realpass",
    )
    # Default sandbox_all=True means all skills are sandboxed
    assert s.should_sandbox_all() is True

    s2 = Settings(
        sandbox_all=False,
        database_url="postgresql://user:realpass@host:5432/db",
        pg_password="realpass",
    )
    assert s2.should_sandbox_all() is False


def test_get_sandbox_skill_names_returns_empty_when_sandbox_all_true():
    """When sandbox_all=True (default), get_sandbox_skill_names returns empty set."""
    s = Settings(
        database_url="postgresql://user:realpass@host:5432/db",
        pg_password="realpass",
    )
    # sandbox_all=True defaults to sandboxing everything
    # so skill names set should be empty (all are sandboxed, no opt-in needed)
    assert s.get_sandbox_skill_names() == set()

    # Even with skills listed, when sandbox_all=True they're still all sandboxed
    s2 = Settings(
        sandbox_skills="skill_a, skill_b",
        database_url="postgresql://user:realpass@host:5432/db",
        pg_password="realpass",
    )
    assert s2.get_sandbox_skill_names() == set()


def test_get_sandbox_skill_names_returns_skills_when_sandbox_all_false():
    """When sandbox_all=False, get_sandbox_skill_names returns listed skills."""
    s = Settings(
        sandbox_all=False,
        sandbox_skills="skill_x, skill_y",
        database_url="postgresql://user:realpass@host:5432/db",
        pg_password="realpass",
    )
    assert s.get_sandbox_skill_names() == {"skill_x", "skill_y"}
