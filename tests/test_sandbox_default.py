"""Tests for _should_sandbox default behavior change (sandbox_all=True).

Part A of Fix-4: Verify _should_sandbox returns True for unknown skills
with the new sandbox_all=True default from config.py.
"""

from unittest.mock import MagicMock

import pytest

from pillywiggins.agents.tools import _should_sandbox


class TestShouldSandboxWithDefaults:
    """Part A: _should_sandbox returns True for unknown skills by default."""

    def test_returns_true_for_unknown_skill_by_default(self):
        """When sandbox_all=True (default), _should_sandbox returns True for any skill."""
        settings = MagicMock()
        settings.should_sandbox_all.return_value = True
        settings.get_sandbox_skill_names.return_value = set()

        result = _should_sandbox("completely_unknown_skill", settings=settings)
        assert result is True

    def test_returns_true_for_any_skill_when_sandbox_all_true(self):
        """sandbox_all=True should sandbox every skill regardless of name."""
        settings = MagicMock()
        settings.should_sandbox_all.return_value = True
        settings.get_sandbox_skill_names.return_value = {"specific_skill"}

        # Even skills not in the specific list should be sandboxed
        assert _should_sandbox("unknown_skill", settings=settings) is True
        assert _should_sandbox("specific_skill", settings=settings) is True
        assert _should_sandbox("random_thing", settings=settings) is True

    def test_returns_false_when_sandbox_all_false_and_not_in_list(self):
        """When sandbox_all=False, only skills in the sandbox_skills list are sandboxed."""
        settings = MagicMock()
        settings.should_sandbox_all.return_value = False
        settings.get_sandbox_skill_names.return_value = {"dangerous_skill"}

        assert _should_sandbox("safe_skill", settings=settings) is False
        assert _should_sandbox("another_safe", settings=settings) is False

    def test_returns_true_when_sandbox_all_false_and_skill_in_list(self):
        """When sandbox_all=False, skills explicitly listed should still be sandboxed."""
        settings = MagicMock()
        settings.should_sandbox_all.return_value = False
        settings.get_sandbox_skill_names.return_value = {"dangerous_skill"}

        assert _should_sandbox("dangerous_skill", settings=settings) is True

    def test_uses_real_settings_with_sandbox_all_default(self):
        """With real Settings (sandbox_all=True default), unknown skills sandboxed."""
        from pillywiggins.config import Settings

        # conftest sets DATABASE_URL and PG_PASSWORD via monkeypatch
        settings = Settings()
        assert settings.sandbox_all is True

        result = _should_sandbox("any_unknown_skill", settings=settings)
        assert result is True

    def test_does_not_call_get_sandbox_skill_names_when_sandbox_all_true(self):
        """When sandbox_all=True, get_sandbox_skill_names should not be called."""
        settings = MagicMock()
        settings.should_sandbox_all.return_value = True

        _should_sandbox("any_skill", settings=settings)

        settings.get_sandbox_skill_names.assert_not_called()

    def test_calls_get_sandbox_skill_names_when_sandbox_all_false(self):
        """When sandbox_all=False, get_sandbox_skill_names should be checked."""
        settings = MagicMock()
        settings.should_sandbox_all.return_value = False
        settings.get_sandbox_skill_names.return_value = set()

        _should_sandbox("any_skill", settings=settings)

        settings.get_sandbox_skill_names.assert_called_once()

    def test_returns_true_for_empty_skill_name_by_default(self):
        """Empty skill name should still be sandboxed when sandbox_all=True."""
        settings = MagicMock()
        settings.should_sandbox_all.return_value = True

        result = _should_sandbox("", settings=settings)
        assert result is True

    def test_returns_false_for_empty_skill_name_when_not_in_list(self):
        """Empty skill name should NOT be sandboxed when sandbox_all=False and not in list."""
        settings = MagicMock()
        settings.should_sandbox_all.return_value = False
        settings.get_sandbox_skill_names.return_value = {"specific_skill"}

        result = _should_sandbox("", settings=settings)
        assert result is False


class TestShouldSandboxEdgeCases:
    """Edge cases for _should_sandbox behavior."""

    def test_nonexistent_skill_not_in_whitelist(self):
        """A skill that doesn't exist is sandboxed under sandbox_all=True."""
        settings = MagicMock()
        settings.should_sandbox_all.return_value = True

        # Even skills that don't exist anywhere should be sandboxed
        for skill_name in ["phantomskill_xyz", "no_such_skill_123", "a" * 100]:
            assert _should_sandbox(skill_name, settings=settings) is True

    def test_skill_with_special_chars_sandboxed(self):
        """Skills with special characters in name still get sandboxed."""
        settings = MagicMock()
        settings.should_sandbox_all.return_value = True

        assert _should_sandbox("skill/with/slashes", settings=settings) is True
        assert _should_sandbox("skill.with.dots", settings=settings) is True
        assert _should_sandbox("skill-with-dashes", settings=settings) is True

    def test_returns_true_when_sandbox_all_true_regardless_of_list(self):
        """sandbox_all=True overrides any sandbox_skills list."""
        settings = MagicMock()
        settings.should_sandbox_all.return_value = True
        # get_sandbox_skill_names returns an empty set when sandbox_all=True
        settings.get_sandbox_skill_names.return_value = set()

        # Every skill should be sandboxed
        assert _should_sandbox("skill_a", settings=settings) is True
        assert _should_sandbox("skill_b", settings=settings) is True
        assert _should_sandbox("skill_c", settings=settings) is True
