"""Tests for the skill builder self-correction loop and progress messages.

These verify that:
- Progress messages are emitted at each stage (drafting, testing, reviewing, publishing).
- When schema validation fails, a structured correction prompt is returned.
- The retry flow works end-to-end through the brain tools (max 2 retries).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.skills import builder as _builder
from pillywiggins.skills.builder import (
    DraftStatus,
    SkillDraft,
    draft_skill,
    format_correction_prompt,
    get_progress_message,
)

VALID_SKILL_CODE = """\
SKILL_META = {
    "name": "double",
    "description": "Double a number",
    "parameters": {"x": {"type": "number", "description": "Number to double"}},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

async def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""

INVALID_SKILL_CODE_MISSING_META = """\
async def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""

INVALID_SKILL_CODE_SYNC_RUN = """\
SKILL_META = {
    "name": "sync",
    "description": "Sync run",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""

SYNTAX_ERROR_CODE = """\
SKILL_META = {"name": "bad", "description": "bad", "parameters": {}, "permissions": {}}
async def run(:
    return {}
"""


# ---------------------------------------------------------------------------
# Tests: progress messages
# ---------------------------------------------------------------------------


class TestProgressMessages:
    def test_drafting_message(self):
        assert get_progress_message("drafting") == "Drafting skill..."

    def test_testing_message(self):
        assert get_progress_message("testing") == "Testing skill..."

    def test_reviewing_message(self):
        assert get_progress_message("reviewing") == "Reviewing skill..."

    def test_publishing_message(self):
        assert get_progress_message("publishing") == "Publishing skill..."

    def test_unknown_stage_returns_generic(self):
        assert get_progress_message("unknown") == "Working on unknown..."

    def test_progress_messages_are_not_empty(self):
        for stage in ("drafting", "testing", "reviewing", "publishing"):
            msg = get_progress_message(stage)
            assert isinstance(msg, str)
            assert len(msg) > 0


# ---------------------------------------------------------------------------
# Tests: correction prompt formatting
# ---------------------------------------------------------------------------


class TestFormatCorrectionPrompt:
    def test_basic_structure(self):
        result = format_correction_prompt("build_skill", ["missing async def run()"], 2)
        assert "Skill validation failed. Corrections needed:" in result
        assert "1. Schema error: missing async def run()" in result
        assert "Fix these issues and call build_skill again. You have 2 retries remaining." in result

    def test_multiple_errors_numbered(self):
        errors = ["missing run()", "bad permissions", "disallowed import requests"]
        result = format_correction_prompt("test_skill_code", errors, 1)
        assert "1. Schema error: missing run()" in result
        assert "2. Schema error: bad permissions" in result
        assert "3. Schema error: disallowed import requests" in result
        assert "You have 1 retries remaining." in result

    def test_zero_retries_remaining(self):
        result = format_correction_prompt("review_skill_code", ["err"], 0)
        assert "You have 0 retries remaining." in result

    def test_empty_errors_list(self):
        result = format_correction_prompt("build_skill", [], 2)
        assert "Skill validation failed. Corrections needed:" in result
        assert "Fix these issues and call build_skill again. You have 2 retries remaining." in result


# ---------------------------------------------------------------------------
# Tests: draft_skill returns schema_errors for retry loop
# ---------------------------------------------------------------------------


class TestDraftSkillSchemaErrors:
    def test_missing_meta_produces_schema_errors(self):
        draft = draft_skill("no_meta", INVALID_SKILL_CODE_MISSING_META)
        assert draft.status == DraftStatus.ERROR
        assert "schema_errors" in draft.meta
        assert any("SKILL_META" in e for e in draft.meta["schema_errors"])

    def test_sync_run_produces_schema_errors(self):
        draft = draft_skill("sync_run", INVALID_SKILL_CODE_SYNC_RUN)
        assert draft.status == DraftStatus.ERROR
        assert "schema_errors" in draft.meta
        assert any("async" in e for e in draft.meta["schema_errors"])

    def test_valid_skill_has_no_schema_errors(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        assert draft.status == DraftStatus.DRAFT
        assert draft.meta.get("schema_errors") is None


# ---------------------------------------------------------------------------
# Tests: end-to-end retry flow via brain tool (build_skill)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_retry_counts():
    from pillywiggins.agents.tools import _retry_counts

    _retry_counts.clear()
    yield


class TestBuilderSelfCorrectionLoop:
    @pytest.mark.asyncio
    async def test_build_skill_returns_correction_prompt_on_schema_failure(self):
        from pillywiggins.agents.tools import build_skill
        from tests.helpers import make_ctx

        ctx = make_ctx(conversation_key="corr-1")
        result = await build_skill(ctx, name="bad", code=INVALID_SKILL_CODE_MISSING_META)
        assert "Drafting skill..." in result
        assert "Skill validation failed. Corrections needed:" in result
        assert any("SKILL_META" in e for e in result.splitlines())

    @pytest.mark.asyncio
    async def test_build_skill_returns_progress_message_on_success(self):
        from pillywiggins.agents.tools import build_skill
        from tests.helpers import make_ctx

        ctx = make_ctx(conversation_key="prog-1")
        result = await build_skill(ctx, name="double", code=VALID_SKILL_CODE)
        assert "Drafting skill..." in result
        assert "Draft created: double" in result

    @pytest.mark.asyncio
    async def test_test_skill_code_returns_progress_and_results(self):
        from pillywiggins.agents.tools import test_skill_code
        from tests.helpers import make_ctx

        ctx = make_ctx(conversation_key="prog-2")
        test_cases_json = json.dumps([{"args": {"x": 5}, "expected": {"result": 10}}])
        result = await test_skill_code(ctx, name="double", code=VALID_SKILL_CODE, test_cases_json=test_cases_json)
        assert "Testing skill..." in result
        assert "Test results for 'double': 1/1 passed" in result

    @pytest.mark.asyncio
    async def test_review_skill_code_returns_progress_and_review(self):
        from pillywiggins.agents.tools import review_skill_code
        from tests.helpers import make_ctx

        ctx = make_ctx(conversation_key="prog-3")
        test_cases_json = json.dumps([{"args": {"x": 5}, "expected": {"result": 10}}])
        result = await review_skill_code(ctx, name="double", code=VALID_SKILL_CODE, test_cases_json=test_cases_json)
        assert "Reviewing skill..." in result
        assert "=== Skill Review: double ===" in result

    @pytest.mark.asyncio
    async def test_publish_skill_code_returns_progress_and_result(self):
        from pillywiggins.agents.tools import publish_skill_code
        from tests.helpers import make_ctx

        ctx = make_ctx(conversation_key="prog-4")
        test_cases_json = json.dumps([{"args": {"x": 5}, "expected": {"result": 10}}])
        result = await publish_skill_code(
            ctx, name="double", code=VALID_SKILL_CODE, test_cases_json=test_cases_json, approved=False
        )
        assert "Publishing skill..." in result
        assert "not approved" in result

    @pytest.mark.asyncio
    async def test_retry_count_decrements_remaining_in_prompt(self):
        from pillywiggins.agents.tools import build_skill, _retry_counts
        from tests.helpers import make_ctx

        ctx = make_ctx(conversation_key="retry-1")
        # 1st call: allowed, remaining=2
        result1 = await build_skill(ctx, name="bad", code=INVALID_SKILL_CODE_MISSING_META)
        assert "You have 2 retries remaining" in result1
        # 2nd call: allowed, remaining=1
        result2 = await build_skill(ctx, name="bad", code=INVALID_SKILL_CODE_MISSING_META)
        assert "You have 1 retries remaining" in result2
        # 3rd call: allowed (last retry), remaining=0
        result3 = await build_skill(ctx, name="bad", code=INVALID_SKILL_CODE_MISSING_META)
        assert "You have 0 retries remaining" in result3
        # 4th call: blocked
        result4 = await build_skill(ctx, name="bad", code=INVALID_SKILL_CODE_MISSING_META)
        assert "Max retries reached" in result4

    @pytest.mark.asyncio
    async def test_successful_retry_after_failure(self):
        from pillywiggins.agents.tools import build_skill
        from tests.helpers import make_ctx

        ctx = make_ctx(conversation_key="retry-ok")
        bad_result = await build_skill(ctx, name="bad", code=INVALID_SKILL_CODE_MISSING_META)
        assert "Skill validation failed" in bad_result

        good_result = await build_skill(ctx, name="double", code=VALID_SKILL_CODE)
        assert "Drafting skill..." in good_result
        assert "Draft created: double" in good_result


# ---------------------------------------------------------------------------
# Tests: test_skill progression from draft -> tested
# ---------------------------------------------------------------------------


class TestTestSkillProgression:
    async def test_draft_error_surfaces_in_test_results(self):
        from pillywiggins.skills.builder import test_skill
        draft = draft_skill("bad", SYNTAX_ERROR_CODE)
        result = await test_skill(draft, [])
        assert result.status == DraftStatus.TESTED
        assert result.test_results[0]["passed"] is False
        assert "Syntax error" in result.test_results[0]["error"]

    async def test_valid_skill_tests_update_status(self):
        from pillywiggins.skills.builder import test_skill
        draft = draft_skill("double", VALID_SKILL_CODE)
        result = await test_skill(draft, [{"args": {"x": 3}, "expected": {"result": 6}}])
        assert result.status == DraftStatus.TESTED
        assert result.test_results[0]["passed"] is True
