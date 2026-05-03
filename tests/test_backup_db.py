"""Tests for backup-db.sh script."""
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "backup-db.sh"


def test_backup_script_exists():
    assert SCRIPT.exists(), "backup-db.sh should exist"


def test_backup_script_is_executable():
    assert SCRIPT.stat().st_mode & 0o111, "backup-db.sh should be executable"


def test_backup_script_shebang():
    content = SCRIPT.read_text()
    assert content.startswith("#!/usr/bin/env bash"), "Should have bash shebang"


def test_backup_script_uses_docker_compose():
    content = SCRIPT.read_text()
    assert "docker compose" in content, "Should use docker compose"
    assert "pg_dump" in content, "Should call pg_dump"
    assert "gzip" in content, "Should compress output"


def test_backup_script_creates_timestamped_file():
    content = SCRIPT.read_text()
    assert "TIMESTAMP" in content, "Should generate timestamp"
    assert "pillywiggins_" in content, "Should use pillywiggins prefix"


def test_backup_script_symlinks_latest():
    content = SCRIPT.read_text()
    assert "pillywiggins_latest" in content, "Should create latest symlink"


def test_backup_script_cleans_old_backups():
    content = SCRIPT.read_text()
    assert "find" in content or "KEEP_DAYS" in content, "Should clean old backups"


def test_backup_script_checks_postgres_running():
    content = SCRIPT.read_text()
    assert "ps postgres" in content or "running" in content, "Should verify postgres is running"
