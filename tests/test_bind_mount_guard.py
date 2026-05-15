"""Tests for bind-mount directory crash guard.

Verifies that the pre-startup guard in __main__.py detects when Docker Compose
bind mounts create a directory at ``agents.yaml`` instead of a file.
"""

import tempfile
from pathlib import Path

import pytest

from pillywiggins.__main__ import _check_agents_config_directory


class TestBindMountGuard:
    """Guard must detect directory, pass for files, pass for missing paths."""

    def test_detects_directory_and_exits(self):
        """When agents.yaml is a directory, guard exits with code 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dir_path = Path(tmpdir) / "agents.yaml"
            dir_path.mkdir()
            with pytest.raises(SystemExit) as exc_info:
                _check_agents_config_directory(str(dir_path))
            assert exc_info.value.code == 1

    def test_passes_when_path_is_file(self, tmp_path):
        """When agents.yaml is a regular file, guard does nothing."""
        file_path = tmp_path / "agents.yaml"
        file_path.write_text("agents: []")
        # Should not raise
        _check_agents_config_directory(str(file_path))

    def test_passes_when_path_missing(self, tmp_path):
        """When agents.yaml does not exist, guard does nothing."""
        missing_path = tmp_path / "nonexistent.yaml"
        # Should not raise
        _check_agents_config_directory(str(missing_path))
