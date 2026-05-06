"""Tests for brain skill tools: build_skill, test_skill_code, review_skill_code,
publish_skill_code, _make_skill_tool, _should_sandbox, _run_sandboxed_skill,
and retry/correction logic."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext

from pillywiggins.agents.brain import (
    build_skill,
    test_skill_code as run_skill_test,
    review_skill_code,
    publish_skill_code,
)
from pillywiggins.agents.tools import (
    _make_skill_tool,
    _should_sandbox,
    _retry_counts,
    _get_retry_key,
    _check_and_increment_retries,
    _format_correction_prompt,
)
from pillywiggins.skills.registry import Skill, SkillRegistry
from tests.helpers import make_ctx, make_skill

_make_ctx = make_ctx
_make_skill = make_skill


@pytest.fixture(autouse=True)
def clear_retry_counts():
    _retry_counts.clear()
    yield


class TestShouldSandbox:
    @patch("pillywiggins.config.Settings")
    def test_returns_true_when_sandbox_all(self, mock_settings_cls):
        mock_settings = MagicMock()
        mock_settings.should_sandbox_all.return_value = True
        mock_settings_cls.return_value = mock_settings
        assert _should_sandbox("any_skill") is True

    @patch("pillywiggins.config.Settings")
    def test_returns_true_when_skill_in_sandbox_list(self, mock_settings_cls):
        mock_settings = MagicMock()
        mock_settings.should_sandbox_all.return_value = False
        mock_settings.get_sandbox_skill_names.return_value = {"dangerous_skill", "web_search"}
        mock_settings_cls.return_value = mock_settings
        assert _should_sandbox("web_search") is True

    @patch("pillywiggins.config.Settings")
    def test_returns_false_when_skill_not_in_list(self, mock_settings_cls):
        mock_settings = MagicMock()
        mock_settings.should_sandbox_all.return_value = False
        mock_settings.get_sandbox_skill_names.return_value = {"dangerous_skill"}
        mock_settings_cls.return_value = mock_settings
        assert _should_sandbox("safe_skill") is False


class TestRunSandboxedSkill:
    @pytest.mark.asyncio
    async def test_skill_no_file_path_returns_error(self):
        from pillywiggins.agents.tools import _run_sandboxed_skill

        skill = _make_skill(name="nofile")
        result = await _run_sandboxed_skill(skill, {}, "puck", "discord")
        assert "no source file" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.sandbox.run_sandboxed", new_callable=AsyncMock)
    async def test_sandbox_failure_returns_error(self, mock_run_sandboxed):
        from pillywiggins.agents.tools import _run_sandboxed_skill

        mock_run_sandboxed.return_value = MagicMock(
            success=False, error="timeout exceeded", result=None
        )
        skill = _make_skill(name="fail_skill", file_path=Path("/some/path/fail_skill.py"))
        with patch.object(Path, "read_text", return_value="code"):
            result = await _run_sandboxed_skill(skill, {}, "puck", "discord")
        assert "Sandbox failed" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.sandbox.run_sandboxed", new_callable=AsyncMock)
    async def test_sandbox_success_with_string_result(self, mock_run_sandboxed):
        from pillywiggins.agents.tools import _run_sandboxed_skill

        mock_run_sandboxed.return_value = MagicMock(success=True, error=None, result="hello world")
        skill = _make_skill(name="str_skill", file_path=Path("/some/path/str_skill.py"))
        with patch.object(Path, "read_text", return_value="code"):
            result = await _run_sandboxed_skill(skill, {}, "puck", "discord")
        assert result == "hello world"

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.sandbox.run_sandboxed", new_callable=AsyncMock)
    async def test_sandbox_success_with_dict_result(self, mock_run_sandboxed):
        from pillywiggins.agents.tools import _run_sandboxed_skill

        mock_run_sandboxed.return_value = MagicMock(
            success=True, error=None, result={"key": "value"}
        )
        skill = _make_skill(name="dict_skill", file_path=Path("/some/path/dict_skill.py"))
        with patch.object(Path, "read_text", return_value="code"):
            result = await _run_sandboxed_skill(skill, {}, "puck", "discord")
        parsed = json.loads(result)
        assert parsed == {"key": "value"}


class TestMakeSkillTool:
    def test_generates_tool_with_name_and_doc(self):
        skill = _make_skill(
            name="weather",
            description="Get the weather for a city",
            meta={"parameters": {"city": {"type": "string", "description": "City name"}}},
        )
        tool_fn = _make_skill_tool(skill)
        assert tool_fn.__name__ == "weather"
        assert "weather" in tool_fn.__doc__
        assert "city" in tool_fn.__doc__

    def test_generates_tool_with_permissions_in_doc(self):
        skill = _make_skill(
            name="net_skill",
            description="Network skill",
            permissions={"network": True, "subprocess": False, "file_write": False},
        )
        tool_fn = _make_skill_tool(skill)
        assert "network" in tool_fn.__doc__

    def test_generates_tool_with_default_parameter_values(self):
        skill = _make_skill(
            name="param_skill",
            description="Skill with defaults",
            meta={
                "parameters": {
                    "count": {"type": "int", "description": "Number", "default": 5},
                },
            },
        )
        tool_fn = _make_skill_tool(skill)
        assert "default: 5" in tool_fn.__doc__

    @pytest.mark.asyncio
    async def test_skill_tool_calls_execute(self):
        run_func = AsyncMock(return_value="executed")
        skill = _make_skill(name="test_skill", description="test", run_func=run_func)
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        with patch("pillywiggins.agents.tools._should_sandbox", return_value=False):
            result = await tool_fn(ctx, query="hello")
        run_func.assert_awaited_once_with(query="hello")
        assert result == "executed"

    @pytest.mark.asyncio
    async def test_skill_tool_returns_json_for_non_string(self):
        run_func = AsyncMock(return_value={"key": "value"})
        skill = _make_skill(name="json_skill", description="json test", run_func=run_func)
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        with patch("pillywiggins.agents.tools._should_sandbox", return_value=False):
            result = await tool_fn(ctx)

        parsed = json.loads(result)
        assert parsed == {"key": "value"}

    @pytest.mark.asyncio
    async def test_skill_tool_type_error_returns_available_params(self):
        run_func = AsyncMock(side_effect=TypeError("unexpected keyword argument 'bad_param'"))
        skill = _make_skill(
            name="strict_skill",
            description="strict",
            run_func=run_func,
            meta={"parameters": {"valid_param": {"type": "string"}}},
        )
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        with patch("pillywiggins.agents.tools._should_sandbox", return_value=False):
            result = await tool_fn(ctx, bad_param="oops")
        assert "invalid arguments" in result
        assert "valid_param" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.agents.tools._should_sandbox", return_value=True)
    @patch("pillywiggins.agents.tools._run_sandboxed_skill", new_callable=AsyncMock)
    async def test_skill_tool_sandbox_path(self, mock_run_sandboxed, mock_should_sandbox):
        skill = _make_skill(name="dangerous", description="dangerous skill")
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        mock_run_sandboxed.return_value = "sandboxed result"
        result = await tool_fn(ctx)
        mock_run_sandboxed.assert_awaited_once_with(skill, {}, "puck", "discord", None)
        assert result == "sandboxed result"


class TestBuildSkill:
    @pytest.mark.asyncio
    async def test_build_skill_success(self):
        code = (
            'SKILL_META = {"name": "hello", "description": "says hi", '
            '"parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}\n'
            'async def run(**kwargs): return "hello"'
        )
        ctx = _make_ctx()
        result = await build_skill(ctx, name="hello", code=code)
        assert "Draft created" in result
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_build_skill_validation_failure(self):
        code = "print('no meta or run')"
        ctx = _make_ctx()
        _retry_counts.clear()
        result = await build_skill(ctx, name="bad_skill", code=code)
        assert "Skill validation failed" in result
        assert "Schema error" in result
        assert "fix" in result.lower()

    @pytest.mark.asyncio
    async def test_build_skill_syntax_error_graceful(self):
        code = 'SKILL_META = {"name": "bad", "description": "bad", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}\nasync def run(**kwargs): return "hello"  \n    invalid syntax here'
        ctx = _make_ctx()
        _retry_counts.clear()
        result = await build_skill(ctx, name="bad_skill", code=code)
        assert "Skill generation failed" in result
        assert "fix and try again" in result.lower()

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_build_skill_exception_caught(self, mock_draft):
        mock_draft.side_effect = SyntaxError("unexpected EOF while parsing")
        ctx = _make_ctx()
        _retry_counts.clear()
        result = await build_skill(ctx, name="oops", code="bad")
        assert "Skill generation failed: SyntaxError" in result
        assert "fix and try again" in result.lower()

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_build_skill_error_draft_returns_message(self, mock_draft):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(
            name="bad",
            code="bad",
            meta={},
            status=DraftStatus.ERROR,
            test_results=[{"passed": False, "error": "Syntax error: invalid syntax"}],
        )
        mock_draft.return_value = draft
        ctx = _make_ctx()
        _retry_counts.clear()
        result = await build_skill(ctx, name="bad", code="bad")
        assert "Skill generation failed: Syntax error" in result
        assert "fix and try again" in result.lower()

    @pytest.mark.asyncio
    async def test_build_skill_with_permissions(self):
        code = (
            'SKILL_META = {"name": "net_skill", "description": "network skill", '
            '"parameters": {}, "permissions": {"network": True, "subprocess": False, "file_write": False}}\n'
            "async def run(**kwargs): return 'net'"
        )
        ctx = _make_ctx()
        result = await build_skill(ctx, name="net_skill", code=code)
        assert "Permissions requested: network" in result

    @pytest.mark.asyncio
    async def test_build_skill_no_permissions(self):
        code = (
            'SKILL_META = {"name": "safe_skill", "description": "safe", '
            '"parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}\n'
            "async def run(**kwargs): return 'safe'"
        )
        ctx = _make_ctx()
        result = await build_skill(ctx, name="safe_skill", code=code)
        assert "Permissions: none" in result


class TestTestSkillCode:
    @pytest.mark.asyncio
    async def test_invalid_json(self):
        ctx = _make_ctx()
        result = await run_skill_test(ctx, name="skill", code="pass", test_cases_json="not json")
        assert "test cases JSON is invalid" in result

    @pytest.mark.asyncio
    async def test_not_array(self):
        ctx = _make_ctx()
        result = await run_skill_test(
            ctx, name="skill", code="pass", test_cases_json='{"key": "val"}'
        )
        assert "must be a JSON array" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_code_validation_failure(self, mock_draft):
        mock_draft.side_effect = ValueError("Code must contain a SKILL_META dict assignment")
        ctx = _make_ctx()
        result = await run_skill_test(ctx, name="skill", code="bad code", test_cases_json="[]")
        assert "Skill generation failed: ValueError" in result
        assert "fix and try again" in result.lower()

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.test_skill", new_callable=AsyncMock)
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_successful_test_results(self, mock_draft, mock_test):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(name="hello", code="code", meta={}, status=DraftStatus.TESTED)
        mock_draft.return_value = draft
        draft_with_results = SkillDraft(
            name="hello", code="code", meta={}, status=DraftStatus.TESTED
        )
        draft_with_results.test_results = [
            {
                "args": {},
                "expected": "hello",
                "passed": True,
                "actual": "hello",
                "error": None,
                "execution_time_ms": 10.0,
            },
            {
                "args": {},
                "expected": "world",
                "passed": False,
                "actual": "hello",
                "error": "Assertion failed",
                "execution_time_ms": 5.0,
            },
        ]
        mock_test.return_value = draft_with_results
        ctx = _make_ctx()
        result = await run_skill_test(
            ctx, name="hello", code="code", test_cases_json='[{"args": {}}]'
        )
        assert "has test failures" in result
        assert "Assertion failed" in result
        assert "fix the code" in result.lower()

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.test_skill", new_callable=AsyncMock)
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_test_results_with_error_and_no_expected(self, mock_draft, mock_test):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(name="fail", code="code", meta={}, status=DraftStatus.TESTED)
        mock_draft.return_value = draft
        draft_with_results = SkillDraft(
            name="fail", code="code", meta={}, status=DraftStatus.TESTED
        )
        draft_with_results.test_results = [
            {
                "args": {},
                "expected": None,
                "passed": False,
                "actual": None,
                "error": "crashed",
                "execution_time_ms": 1.0,
            },
        ]
        mock_test.return_value = draft_with_results
        ctx = _make_ctx()
        result = await run_skill_test(
            ctx, name="fail", code="code", test_cases_json='[{"args": {}}]'
        )

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_error_draft_returns_self_correction(self, mock_draft):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(
            name="bad",
            code="bad",
            meta={},
            status=DraftStatus.ERROR,
            test_results=[{"passed": False, "error": "Syntax error: invalid syntax"}],
        )
        mock_draft.return_value = draft
        ctx = _make_ctx()
        result = await run_skill_test(ctx, name="bad", code="bad", test_cases_json="[]")
        assert "Skill generation failed: Syntax error" in result
        assert "fix and try again" in result.lower()

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.test_skill", new_callable=AsyncMock)
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_all_tests_pass_success(self, mock_draft, mock_test):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(name="good", code="code", meta={}, status=DraftStatus.TESTED)
        mock_draft.return_value = draft
        draft_results = SkillDraft(name="good", code="code", meta={}, status=DraftStatus.TESTED)
        draft_results.test_results = [
            {
                "args": {},
                "expected": "hi",
                "passed": True,
                "actual": "hi",
                "error": None,
                "execution_time_ms": 10.0,
            }
        ]
        mock_test.return_value = draft_results
        ctx = _make_ctx()
        result = await run_skill_test(
            ctx, name="good", code="code", test_cases_json='[{"args": {}}]'
        )
        assert "1/1 passed" in result
        assert "PASS" in result


class TestReviewSkillCode:
    @pytest.mark.asyncio
    async def test_invalid_json(self):
        ctx = _make_ctx()
        result = await review_skill_code(ctx, name="skill", code="pass", test_cases_json="bad json")
        assert "test cases JSON is invalid" in result

    @pytest.mark.asyncio
    async def test_not_array(self):
        ctx = _make_ctx()
        result = await review_skill_code(ctx, name="skill", code="pass", test_cases_json='{"a": 1}')
        assert "must be a JSON array" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_code_validation_failure(self, mock_draft):
        mock_draft.side_effect = ValueError("Code must contain a SKILL_META dict assignment")
        ctx = _make_ctx()
        result = await review_skill_code(ctx, name="skill", code="bad", test_cases_json="[]")
        assert "Skill generation failed: ValueError" in result
        assert "fix and try again" in result.lower()

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.review_skill")
    @patch("pillywiggins.skills.builder.test_skill", new_callable=AsyncMock)
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_successful_review(self, mock_draft, mock_test, mock_review):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(name="hello", code="code", meta={}, status=DraftStatus.TESTED)
        mock_draft.return_value = draft
        mock_test.return_value = draft
        mock_review.return_value = "=== Skill Review: hello ===\nApproved!"
        ctx = _make_ctx()
        result = await review_skill_code(ctx, name="hello", code="code", test_cases_json="[]")
        mock_review.assert_called_once_with(draft)

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_error_draft_returns_self_correction(self, mock_draft):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(
            name="bad",
            code="bad",
            meta={},
            status=DraftStatus.ERROR,
            test_results=[{"passed": False, "error": "Syntax error: invalid syntax"}],
        )
        mock_draft.return_value = draft
        ctx = _make_ctx()
        result = await review_skill_code(ctx, name="bad", code="bad", test_cases_json="[]")
        assert "Skill generation failed: Syntax error" in result
        assert "fix and try again" in result.lower()


class TestPublishSkillCode:
    @pytest.mark.asyncio
    async def test_invalid_json(self):
        ctx = _make_ctx(skill_registry=MagicMock(spec=SkillRegistry))
        result = await publish_skill_code(
            ctx, name="skill", code="pass", test_cases_json="bad", approved=True
        )
        assert "test cases JSON is invalid" in result

    @pytest.mark.asyncio
    async def test_not_array(self):
        ctx = _make_ctx(skill_registry=MagicMock(spec=SkillRegistry))
        result = await publish_skill_code(
            ctx, name="skill", code="pass", test_cases_json='{"a":1}', approved=True
        )
        assert "must be a JSON array" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_code_validation_failure(self, mock_draft):
        mock_draft.side_effect = ValueError("Code must contain a SKILL_META dict assignment")
        ctx = _make_ctx(skill_registry=MagicMock(spec=SkillRegistry))
        result = await publish_skill_code(
            ctx, name="skill", code="bad", test_cases_json="[]", approved=True
        )
        assert "Skill generation failed: ValueError" in result
        assert "fix and try again" in result.lower()

    @pytest.mark.asyncio
    @patch("pillywiggins.config.Settings")
    @patch("pillywiggins.skills.builder.publish_skill")
    @patch("pillywiggins.skills.builder.test_skill", new_callable=AsyncMock)
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_successful_publish(self, mock_draft, mock_test, mock_publish, mock_settings_cls):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(name="hello", code="code", meta={}, status=DraftStatus.TESTED)
        mock_draft.return_value = draft
        mock_test.return_value = draft
        mock_publish.return_value = "Skill 'hello' published successfully."
        mock_settings_cls.return_value = MagicMock(skills_dir="/tmp/skills")
        registry = MagicMock(spec=SkillRegistry)
        ctx = _make_ctx(skill_registry=registry)
        result = await publish_skill_code(
            ctx, name="hello", code="code", test_cases_json="[]", approved=True
        )
        mock_publish.assert_awaited_once()


class TestRetryTracking:
    def test_retry_key_format(self):
        ctx = _make_ctx(conversation_key="puck")
        assert _get_retry_key(ctx, "build_skill") == "puck:build_skill"

    def test_check_and_increment_retries_allows_first_two(self):
        ctx = _make_ctx(conversation_key="conv-1")
        allowed, msg = _check_and_increment_retries(ctx, "build_skill", max_retries=2)
        assert allowed is True
        assert msg == ""
        allowed, msg = _check_and_increment_retries(ctx, "build_skill", max_retries=2)
        assert allowed is True
        assert msg == ""
        assert _retry_counts["conv-1:build_skill"] == 2

    def test_check_and_increment_retries_blocks_on_fourth(self):
        ctx = _make_ctx(conversation_key="conv-2")
        for _ in range(3):
            _check_and_increment_retries(ctx, "test_skill_code", max_retries=2)
        allowed, msg = _check_and_increment_retries(ctx, "test_skill_code", max_retries=2)
        assert allowed is False
        assert "Max retries reached" in msg
        assert "test_skill_code" in msg

    def test_format_correction_prompt_structure(self):
        result = _format_correction_prompt("build_skill", ["missing run()", "bad permissions"], 1)
        assert "Skill validation failed. Corrections needed:" in result
        assert "1. Schema error: missing run()" in result
        assert "2. Schema error: bad permissions" in result
        assert "You have 1 retries remaining" in result
        assert "build_skill" in result

    def test_format_correction_prompt_zero_remaining(self):
        result = _format_correction_prompt("build_skill", ["err"], 0)
        assert "You have 0 retries remaining" in result

    def test_retry_counts_isolated_by_conversation(self):
        ctx1 = _make_ctx(conversation_key="a")
        ctx2 = _make_ctx(conversation_key="b")
        _check_and_increment_retries(ctx1, "build_skill")
        assert _retry_counts["a:build_skill"] == 1
        assert "b:build_skill" not in _retry_counts


class TestBuildSkillRetryAndCorrection:
    @pytest.mark.asyncio
    async def test_build_skill_fourth_call_blocked(self):
        bad_code = "print('no meta')"
        ctx = _make_ctx(conversation_key="retry-build")
        for _ in range(3):
            result = await build_skill(ctx, name="bad", code=bad_code)
            assert "Skill generation failed" in result or "Corrections needed" in result
        result = await build_skill(ctx, name="bad", code=bad_code)
        assert "Max retries reached" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_build_skill_shows_correction_prompt_with_schema_errors(self, mock_draft):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(
            name="bad",
            code="bad",
            meta={"schema_errors": ["missing async def run()", "disallowed import requests"]},
            status=DraftStatus.ERROR,
            test_results=[{"passed": False, "error": "Schema validation failed"}],
        )
        mock_draft.return_value = draft
        ctx = _make_ctx(conversation_key="corr-build")
        result = await build_skill(ctx, name="bad", code="bad")
        assert "Skill validation failed. Corrections needed:" in result
        assert "1. Schema error: missing async def run()" in result
        assert "2. Schema error: disallowed import requests" in result
        assert "retries remaining" in result

    @pytest.mark.asyncio
    async def test_build_skill_successful_retry_after_failure(self):
        good_code = 'SKILL_META = {"name": "ok", "description": "ok", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}\nasync def run(**kwargs): return "ok"'
        ctx = _make_ctx(conversation_key="retry-ok")
        bad_result = await build_skill(ctx, name="bad", code="print('no')")
        assert "failed" in bad_result.lower() or "Corrections" in bad_result
        # second call should still succeed with valid code
        result = await build_skill(ctx, name="ok", code=good_code)
        assert "Draft created" in result


class TestTestSkillCodeRetryAndCorrection:
    @pytest.mark.asyncio
    async def test_test_skill_code_fourth_call_blocked(self):
        ctx = _make_ctx(conversation_key="retry-test")
        for _ in range(3):
            result = await run_skill_test(ctx, name="bad", code="bad", test_cases_json="[]")
            assert "Skill generation failed" in result or "Corrections needed" in result
        result = await run_skill_test(ctx, name="bad", code="bad", test_cases_json="[]")
        assert "Max retries reached" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_test_skill_code_shows_correction_prompt(self, mock_draft):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(
            name="bad",
            code="bad",
            meta={"schema_errors": ["run() must be async"]},
            status=DraftStatus.ERROR,
            test_results=[{"passed": False, "error": "Schema"}],
        )
        mock_draft.return_value = draft
        ctx = _make_ctx(conversation_key="corr-test")
        result = await run_skill_test(ctx, name="bad", code="bad", test_cases_json="[]")
        assert "Corrections needed:" in result
        assert "run() must be async" in result


class TestReviewSkillCodeRetryAndCorrection:
    @pytest.mark.asyncio
    async def test_review_skill_code_fourth_call_blocked(self):
        ctx = _make_ctx(conversation_key="retry-review")
        for _ in range(3):
            result = await review_skill_code(ctx, name="bad", code="bad", test_cases_json="[]")
            assert "Skill generation failed" in result or "Corrections needed" in result
        result = await review_skill_code(ctx, name="bad", code="bad", test_cases_json="[]")
        assert "Max retries reached" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_review_skill_code_shows_correction_prompt(self, mock_draft):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(
            name="bad",
            code="bad",
            meta={"schema_errors": ["missing permissions"]},
            status=DraftStatus.ERROR,
            test_results=[{"passed": False, "error": "Schema"}],
        )
        mock_draft.return_value = draft
        ctx = _make_ctx(conversation_key="corr-review")
        result = await review_skill_code(ctx, name="bad", code="bad", test_cases_json="[]")
        assert "missing permissions" in result


class TestPublishSkillCodeRetryAndCorrection:
    @pytest.mark.asyncio
    async def test_publish_skill_code_fourth_call_blocked(self):
        ctx = _make_ctx(conversation_key="retry-pub")
        for _ in range(3):
            result = await publish_skill_code(
                ctx, name="bad", code="bad", test_cases_json="[]", approved=True
            )
            assert "Skill generation failed" in result or "Corrections needed" in result
        result = await publish_skill_code(
            ctx, name="bad", code="bad", test_cases_json="[]", approved=True
        )
        assert "Max retries reached" in result

    @pytest.mark.asyncio
    @patch("pillywiggins.skills.builder.draft_skill")
    async def test_publish_skill_code_shows_correction_prompt(self, mock_draft):
        from pillywiggins.skills.builder import SkillDraft, DraftStatus

        draft = SkillDraft(
            name="bad",
            code="bad",
            meta={"schema_errors": ["disallowed import requests"]},
            status=DraftStatus.ERROR,
            test_results=[{"passed": False, "error": "Schema"}],
        )
        mock_draft.return_value = draft
        ctx = _make_ctx(conversation_key="corr-pub")
        result = await publish_skill_code(
            ctx, name="bad", code="bad", test_cases_json="[]", approved=True
        )
        assert "disallowed import requests" in result


def test_retry_counts_module_level_dict():
    assert isinstance(_retry_counts, dict)


class TestSanitizerIntegrationSkill:
    @pytest.mark.asyncio
    async def test_build_skill_result_sanitized(self):
        code = (
            'SKILL_META = {"name": "hello", "description": "says hi", '
            '"parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}\n'
            'async def run(**kwargs): return "hello"'
        )
        ctx = _make_ctx()
        result = await build_skill(ctx, name="hello", code=code)
        assert "Draft created" in result
        assert "hello" in result