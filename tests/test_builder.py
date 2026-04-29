import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pillywiggins.skills import builder as _builder

DANGEROUS_PATTERNS = _builder.DANGEROUS_PATTERNS
DraftStatus = _builder.DraftStatus
SkillDraft = _builder.SkillDraft
_extract_meta = _builder._extract_meta
_sanitize_code = _builder._sanitize_code
publish_skill = _builder.publish_skill
draft_skill = _builder.draft_skill
review_skill = _builder.review_skill
run_skill_tests = _builder.test_skill
validate_skill_code = _builder.validate_skill_code
validate_tests = _builder.validate_tests
_test_driven_skill = _builder.test_driven_skill


VALID_SKILL_CODE = """\
SKILL_META = {
    "name": "double",
    "description": "Double a number",
    "parameters": {"x": {"type": "number", "description": "Number to double"}},
    "returns": "dict with result",
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""

CODE_MISSING_META = """\
def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""

CODE_MISSING_RUN = """\
SKILL_META = {
    "name": "broken",
    "description": "No run function",
}

def compute(x):
    return x * 2
"""

CODE_SYNTAX_ERROR = """\
SKILL_META = {"name": "bad"}
def run(:
    return {}
"""

CODE_WITH_EVAL = """\
SKILL_META = {"name": "evil", "permissions": {"network": False, "subprocess": False, "file_write": False}}
def run(expr: str = "") -> dict:
    return {"result": eval(expr)}
"""

CODE_WITH_EXEC = """\
SKILL_META = {"name": "evil", "permissions": {"network": False, "subprocess": False, "file_write": False}}
def run(cmd: str = "") -> dict:
    exec(cmd)
    return {"done": True}
"""

CODE_WITH_OS_SYSTEM = """\
SKILL_META = {"name": "evil", "permissions": {"network": False, "subprocess": False, "file_write": False}}
import os
def run(cmd: str = "") -> dict:
    os.system(cmd)
    return {"done": True}
"""

CODE_WITH_SUBPROCESS_POPEN = """\
SKILL_META = {"name": "evil", "permissions": {"network": False, "subprocess": False, "file_write": False}}
import subprocess
def run(cmd: str = "") -> dict:
    subprocess.Popen(cmd.split())
    return {"done": True}
"""

CODE_WITH_SUBPROCESS_ALLOWED = """\
SKILL_META = {
    "name": "runner",
    "description": "Runs subprocesses",
    "permissions": {"network": False, "subprocess": True, "file_write": False},
}
import subprocess
def run(cmd: str = "") -> dict:
    subprocess.Popen(cmd.split())
    return {"done": True}
"""

CODE_WITH_IMPORT = """\
SKILL_META = {"name": "evil", "permissions": {"network": False, "subprocess": False, "file_write": False}}
def run(mod: str = "") -> dict:
    m = __import__(mod)
    return {"module": str(m)}
"""

# Model-quality escape issues — these strings are deliberately malformed to
# reproduce common LLM mis-escaping patterns observed in tool-call arguments.
CODE_WITH_ESCAPED_TRIPLE_QUOTES = 'x = \\"""Get weather"""\n'
# The raw Python string contains a backslash followed by """.
# Python sees \ as a line-continuation character and then """ as a string
# delimiter, producing: SyntaxError: unexpected character after line
# continuation character.

CODE_WITH_ESCAPED_NEWLINE_LITERAL = 'def run():\\n    return 1\n'
# A literal "\\n" in the code instead of an actual newline character.
# After JSON parsing this is still "\\n" in the string, which ast.parse
# rejects because \\n is a line-continuation + "n".


class TestDraftStatus:
    def test_draft_value(self):
        assert DraftStatus.DRAFT.value == "draft"

    def test_tested_value(self):
        assert DraftStatus.TESTED.value == "tested"

    def test_reviewed_value(self):
        assert DraftStatus.REVIEWED.value == "reviewed"

    def test_approved_value(self):
        assert DraftStatus.APPROVED.value == "approved"

    def test_rejected_value(self):
        assert DraftStatus.REJECTED.value == "rejected"

    def test_is_enum(self):
        assert isinstance(DraftStatus.DRAFT, DraftStatus)

    def test_all_values_unique(self):
        values = [s.value for s in DraftStatus]
        assert len(values) == len(set(values))


class TestSkillDraft:
    def test_default_status_is_draft(self):
        draft = SkillDraft(name="test", code="pass")
        assert draft.status == DraftStatus.DRAFT

    def test_default_meta_is_empty_dict(self):
        draft = SkillDraft(name="test", code="pass")
        assert draft.meta == {}

    def test_default_test_results_is_empty_list(self):
        draft = SkillDraft(name="test", code="pass")
        assert draft.test_results == []

    def test_explicit_fields(self):
        draft = SkillDraft(
            name="my_skill",
            code="x = 1",
            meta={"name": "my_skill"},
            status=DraftStatus.TESTED,
            test_results=[{"passed": True}],
        )
        assert draft.name == "my_skill"
        assert draft.code == "x = 1"
        assert draft.meta == {"name": "my_skill"}
        assert draft.status == DraftStatus.TESTED
        assert draft.test_results == [{"passed": True}]

    def test_permissions_from_meta(self):
        draft = SkillDraft(
            name="test",
            code="pass",
            meta={"permissions": {"network": True, "subprocess": False, "file_write": False}},
        )
        assert draft.permissions == {"network": True, "subprocess": False, "file_write": False}

    def test_permissions_default_when_no_meta(self):
        draft = SkillDraft(name="test", code="pass", meta={})
        assert draft.permissions == {"network": False, "subprocess": False, "file_write": False}

    def test_permissions_legacy_network_access(self):
        draft = SkillDraft(
            name="test",
            code="pass",
            meta={"network_access": True, "permissions": {}},
        )
        assert draft.permissions["network"] is True

    def test_permissions_meta_overrides_legacy(self):
        draft = SkillDraft(
            name="test",
            code="pass",
            meta={"network_access": False, "permissions": {"network": True}},
        )
        assert draft.permissions["network"] is True

    def test_each_draft_has_independent_test_results(self):
        d1 = SkillDraft(name="a", code="a")
        d2 = SkillDraft(name="b", code="b")
        d1.test_results.append({"passed": True})
        assert d1.test_results == [{"passed": True}]
        assert d2.test_results == []

    def test_each_draft_has_independent_meta(self):
        d1 = SkillDraft(name="a", code="a", meta={"x": 1})
        d2 = SkillDraft(name="b", code="b", meta={"y": 2})
        assert d1.meta == {"x": 1}
        assert d2.meta == {"y": 2}


class TestValidateSkillCode:
    def test_valid_code_passes(self):
        valid, error = validate_skill_code(VALID_SKILL_CODE)
        assert valid is True
        assert error == ""

    def test_missing_skill_meta_fails(self):
        valid, error = validate_skill_code(CODE_MISSING_META)
        assert valid is False
        assert "SKILL_META" in error

    def test_missing_run_function_fails(self):
        valid, error = validate_skill_code(CODE_MISSING_RUN)
        assert valid is False
        assert "run()" in error

    def test_syntax_error_fails(self):
        valid, error = validate_skill_code(CODE_SYNTAX_ERROR)
        assert valid is False
        assert "Syntax error" in error

    def test_dangerous_eval_blocked(self):
        valid, error = validate_skill_code(CODE_WITH_EVAL)
        assert valid is False
        assert "eval" in error

    def test_dangerous_exec_blocked(self):
        valid, error = validate_skill_code(CODE_WITH_EXEC)
        assert valid is False
        assert "exec" in error

    def test_dangerous_os_system_blocked(self):
        valid, error = validate_skill_code(CODE_WITH_OS_SYSTEM)
        assert valid is False
        assert "os.system" in error

    def test_dangerous_subprocess_popen_blocked(self):
        valid, error = validate_skill_code(CODE_WITH_SUBPROCESS_POPEN)
        assert valid is False
        assert "subprocess.Popen" in error

    def test_dangerous_import_blocked(self):
        valid, error = validate_skill_code(CODE_WITH_IMPORT)
        assert valid is False
        assert "__import__" in error

    def test_subprocess_popen_allowed_with_permission(self):
        valid, error = validate_skill_code(
            CODE_WITH_SUBPROCESS_ALLOWED,
            permissions={"network": False, "subprocess": True, "file_write": False},
        )
        assert valid is True

    def test_subprocess_popen_still_blocked_without_permission(self):
        valid, error = validate_skill_code(
            CODE_WITH_SUBPROCESS_ALLOWED,
            permissions={"network": False, "subprocess": False, "file_write": False},
        )
        assert valid is False
        assert "subprocess.Popen" in error

    def test_os_system_never_allowed_even_with_permission(self):
        code = """\
SKILL_META = {"name": "evil", "permissions": {"network": True, "subprocess": True, "file_write": True}}
import os
def run(cmd: str = "") -> dict:
    os.system(cmd)
    return {"done": True}
"""
        valid, error = validate_skill_code(code, permissions={"subprocess": True})
        assert valid is False
        assert "os.system" in error

    def test_permissions_default_to_empty(self):
        valid, error = validate_skill_code(VALID_SKILL_CODE, permissions=None)
        assert valid is True

    def test_sync_run_function_accepted(self):
        code = """\
SKILL_META = {"name": "sync_skill", "description": "sync"}
def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""
        valid, error = validate_skill_code(code)
        assert valid is True

    def test_async_run_function_accepted(self):
        code = """\
SKILL_META = {"name": "async_skill", "description": "async"}
async def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""
        valid, error = validate_skill_code(code)
        assert valid is True

    def test_all_dangerous_patterns_have_regex(self):
        for pattern_name, regex in DANGEROUS_PATTERNS.items():
            assert isinstance(regex, str)
            assert len(regex) > 0


class TestExtractMeta:
    def test_extracts_skill_meta(self):
        meta = _extract_meta(VALID_SKILL_CODE)
        assert meta["name"] == "double"
        assert meta["description"] == "Double a number"

    def test_returns_empty_when_no_meta(self):
        meta = _extract_meta(CODE_MISSING_META)
        assert meta == {}

    def test_extracts_permissions(self):
        meta = _extract_meta(VALID_SKILL_CODE)
        assert "permissions" in meta
        assert meta["permissions"]["network"] is False

    def test_extracts_parameters(self):
        meta = _extract_meta(VALID_SKILL_CODE)
        assert "parameters" in meta
        assert "x" in meta["parameters"]


class TestDraftSkill:
    def test_creates_draft_with_correct_name(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        assert draft.name == "double"

    def test_creates_draft_with_draft_status(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        assert draft.status == DraftStatus.DRAFT

    def test_extracts_meta_from_code(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        assert draft.meta["name"] == "double"
        assert draft.meta["description"] == "Double a number"

    def test_validates_code_on_creation(self):
        draft = draft_skill("broken", CODE_MISSING_META)
        assert draft.status == DraftStatus.ERROR
        assert "validation failed" in draft.test_results[0].get("error", "")

    def test_validates_syntax_on_creation(self):
        draft = draft_skill("bad", CODE_SYNTAX_ERROR)
        assert draft.status == DraftStatus.ERROR
        assert "Syntax error" in draft.meta.get("error", "")

    def test_validates_dangerous_patterns_on_creation(self):
        draft = draft_skill("evil", CODE_WITH_EVAL)
        assert draft.status == DraftStatus.ERROR
        assert "dangerous pattern" in draft.test_results[0].get("error", "")

    def test_stores_code(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        assert draft.code == VALID_SKILL_CODE

    def test_empty_test_results(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        assert draft.test_results == []


class TestTestSkill:
    async def test_passing_test_case(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        test_cases = [{"args": {"x": 5}, "expected": {"result": 10}}]
        result = await run_skill_tests(draft, test_cases)
        assert result.test_results[0]["passed"] is True
        assert result.test_results[0]["actual"] == {"result": 10}

    async def test_failing_test_case(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        test_cases = [{"args": {"x": 5}, "expected": {"result": 999}}]
        result = await run_skill_tests(draft, test_cases)
        assert result.test_results[0]["passed"] is False
        assert result.test_results[0]["actual"] == {"result": 10}

    async def test_sets_status_to_tested(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        test_cases = [{"args": {"x": 0}, "expected": {"result": 0}}]
        result = await run_skill_tests(draft, test_cases)
        assert result.status == DraftStatus.TESTED

    async def test_records_execution_time(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        test_cases = [{"args": {"x": 1}, "expected": {"result": 2}}]
        result = await run_skill_tests(draft, test_cases)
        assert result.test_results[0]["execution_time_ms"] > 0

    async def test_multiple_test_cases(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        test_cases = [
            {"args": {"x": 0}, "expected": {"result": 0}},
            {"args": {"x": 3}, "expected": {"result": 6}},
            {"args": {"x": -1}, "expected": {"result": -2}},
        ]
        result = await run_skill_tests(draft, test_cases)
        assert len(result.test_results) == 3
        assert all(r["passed"] for r in result.test_results)

    async def test_no_expected_always_passes(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        test_cases = [{"args": {"x": 5}}]
        result = await run_skill_tests(draft, test_cases)
        assert result.test_results[0]["passed"] is True

    async def test_error_in_skill_recorded(self):
        error_code = """\
SKILL_META = {
    "name": "crasher",
    "description": "Crashes",
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

def run() -> dict:
    raise RuntimeError("intentional crash")
"""
        draft = draft_skill("crasher", error_code)
        test_cases = [{"args": {}, "expected": None}]
        result = await run_skill_tests(draft, test_cases)
        assert result.test_results[0]["passed"] is False
        assert result.test_results[0]["error"] is not None
        assert "intentional crash" in result.test_results[0]["error"]

    async def test_timeout_recorded(self):
        timeout_code = """\
SKILL_META = {
    "name": "slowpoke",
    "description": "Does nothing",
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

import time

def run() -> dict:
    time.sleep(60)
    return {"done": True}
"""
        draft = draft_skill("slowpoke", timeout_code)
        test_cases = [{"args": {}, "expected": None}]
        with patch("pillywiggins.skills.builder.run_sandboxed") as mock_run:
            from pillywiggins.skills.sandbox import SandboxResult

            mock_run.return_value = SandboxResult(
                success=False,
                error="Sandbox timed out after 2s",
                timed_out=True,
                execution_time_ms=2000.0,
            )
            result = await run_skill_tests(draft, test_cases)
            assert result.test_results[0]["passed"] is False
            assert result.test_results[0]["timed_out"] is True

    async def test_empty_test_cases_list(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        result = await run_skill_tests(draft, [])
        assert result.test_results == []
        assert result.status == DraftStatus.TESTED

    async def test_args_passed_through(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        test_cases = [{"args": {"x": 7}, "expected": {"result": 14}}]
        result = await run_skill_tests(draft, test_cases)
        assert result.test_results[0]["args"] == {"x": 7}
        assert result.test_results[0]["actual"] == {"result": 14}

    async def test_sandbox_error_sets_actual_none(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        test_cases = [{"args": {"x": 5}, "expected": {"result": 10}}]
        with patch("pillywiggins.skills.builder.run_sandboxed") as mock_run:
            from pillywiggins.skills.sandbox import SandboxResult

            mock_run.return_value = SandboxResult(
                success=False,
                error="Process exited with code 1",
                execution_time_ms=5.0,
            )
            result = await run_skill_tests(draft, test_cases)
            assert result.test_results[0]["passed"] is False
            assert result.test_results[0]["actual"] is None
            assert "exited with code 1" in result.test_results[0]["error"]

    async def test_mixed_pass_fail_results(self):
        draft = draft_skill("double", VALID_SKILL_CODE)
        test_cases = [
            {"args": {"x": 2}, "expected": {"result": 4}},
            {"args": {"x": 3}, "expected": {"result": 999}},
        ]
        result = await run_skill_tests(draft, test_cases)
        assert result.test_results[0]["passed"] is True
        assert result.test_results[1]["passed"] is False


class TestValidateTests:
    def test_valid_test_code(self):
        valid, error = validate_tests("assert 1 + 1 == 2")
        assert valid is True
        assert error == ""

    def test_syntax_error_caught(self):
        valid, error = validate_tests(
            'assert 1 +\n        assert 2\n'
        )
        assert valid is False
        assert "Syntax error" in error

    def test_empty_string_is_valid(self):
        # ast.parse accepts the empty string too
        valid, error = validate_tests("")
        assert valid is True


class TestTestDrivenSkill:
    async def test_valid_skill_and_tests_pass(self):
        code = """\
SKILL_META = {
    "name": "double",
    "description": "Double a number",
    "parameters": {"x": {"type": "number", "description": "Number to double"}},
    "returns": "dict with result",
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""
        test_code = "assert run(5) == {'result': 10}\nassert run(0) == {'result': 0}"
        draft = await _test_driven_skill("double", code, test_code)
        assert draft.status == DraftStatus.DRAFT
        assert draft.test_results[0]["passed"] is True

    async def test_assertion_error_caught(self):
        code = """\
SKILL_META = {
    "name": "double",
    "description": "Double a number",
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""
        test_code = "assert run(5) == {'result': 999}"
        draft = await _test_driven_skill("double", code, test_code)
        assert draft.status == DraftStatus.ERROR
        assert "Assertion failed" in draft.test_results[0]["error"]

    async def test_invalid_skill_code_returns_error(self):
        code = "invalid python {{"
        test_code = "assert True"
        draft = await _test_driven_skill("bad", code, test_code)
        assert draft.status == DraftStatus.ERROR
        assert "syntax error" in draft.test_results[0]["error"].lower()

    async def test_invalid_test_code_returns_error(self):
        code = """\
SKILL_META = {
    "name": "double",
    "description": "Double a number",
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""
        test_code = "assert 5 +\n"
        draft = await _test_driven_skill("double", code, test_code)
        assert draft.status == DraftStatus.ERROR
        assert "Test code validation failed" in draft.test_results[0]["error"]

    async def test_exception_in_test_code_recorded(self):
        code = """\
SKILL_META = {
    "name": "double",
    "description": "Double a number",
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""
        test_code = "run('string')['missing_key']"
        draft = await _test_driven_skill("double", code, test_code)
        assert draft.status == DraftStatus.ERROR
        assert "missing_key" in draft.test_results[0]["error"]

    async def test_execution_time_recorded(self):
        code = """\
SKILL_META = {
    "name": "double",
    "description": "Double a number",
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""
        test_code = "assert run(5) == {'result': 10}"
        draft = await _test_driven_skill("double", code, test_code)
        assert draft.status == DraftStatus.DRAFT
        assert draft.test_results[0]["execution_time_ms"] > 0

    async def test_preserves_meta(self):
        code = VALID_SKILL_CODE
        test_code = "assert run(5) == {'result': 10}"
        draft = await _test_driven_skill("double", code, test_code)
        assert draft.meta["name"] == "double"
        assert draft.meta["description"] == "Double a number"


class TestReviewSkill:
    def test_includes_skill_name(self):
        draft = SkillDraft(name="my_skill", code="pass", status=DraftStatus.TESTED)
        output = review_skill(draft)
        assert "my_skill" in output

    def test_includes_status(self):
        draft = SkillDraft(name="test", code="pass", status=DraftStatus.TESTED)
        output = review_skill(draft)
        assert "tested" in output

    def test_includes_code(self):
        draft = SkillDraft(name="test", code="my_code_content", status=DraftStatus.DRAFT)
        output = review_skill(draft)
        assert "my_code_content" in output

    def test_includes_test_results(self):
        draft = SkillDraft(
            name="test",
            code="pass",
            status=DraftStatus.TESTED,
            test_results=[
                {
                    "passed": True,
                    "args": {"x": 1},
                    "actual": {"result": 2},
                    "expected": {"result": 2},
                    "error": None,
                    "timed_out": False,
                    "execution_time_ms": 5.0,
                },
            ],
        )
        output = review_skill(draft)
        assert "1/1 tests passed" in output
        assert "PASS" in output

    def test_shows_failing_test_results(self):
        draft = SkillDraft(
            name="test",
            code="pass",
            status=DraftStatus.TESTED,
            test_results=[
                {
                    "passed": False,
                    "args": {"x": 1},
                    "actual": {"result": 3},
                    "expected": {"result": 2},
                    "error": None,
                    "timed_out": False,
                    "execution_time_ms": 5.0,
                },
            ],
        )
        output = review_skill(draft)
        assert "0/1 tests passed" in output
        assert "FAIL" in output

    def test_no_test_results_shows_message(self):
        draft = SkillDraft(name="test", code="pass", status=DraftStatus.DRAFT)
        output = review_skill(draft)
        assert "No test results available" in output

    def test_includes_approval_warning(self):
        draft = SkillDraft(name="test", code="pass", status=DraftStatus.DRAFT)
        output = review_skill(draft)
        assert "⚠" in output
        assert "approval" in output.lower()

    def test_shows_expected_and_actual(self):
        draft = SkillDraft(
            name="test",
            code="pass",
            status=DraftStatus.TESTED,
            test_results=[
                {
                    "passed": False,
                    "args": {},
                    "actual": 42,
                    "expected": 99,
                    "error": None,
                    "timed_out": False,
                    "execution_time_ms": 1.0,
                },
            ],
        )
        output = review_skill(draft)
        assert "42" in output
        assert "99" in output

    def test_shows_error_in_result(self):
        draft = SkillDraft(
            name="test",
            code="pass",
            status=DraftStatus.TESTED,
            test_results=[
                {
                    "passed": False,
                    "args": {},
                    "actual": None,
                    "expected": None,
                    "error": "something broke",
                    "timed_out": False,
                    "execution_time_ms": 1.0,
                },
            ],
        )
        output = review_skill(draft)
        assert "something broke" in output

    def test_multiple_test_results_counted(self):
        results = [
            {
                "passed": True,
                "args": {},
                "actual": None,
                "expected": None,
                "error": None,
                "timed_out": False,
                "execution_time_ms": 1.0,
            },
            {
                "passed": True,
                "args": {},
                "actual": None,
                "expected": None,
                "error": None,
                "timed_out": False,
                "execution_time_ms": 1.0,
            },
            {
                "passed": False,
                "args": {},
                "actual": None,
                "expected": None,
                "error": "err",
                "timed_out": False,
                "execution_time_ms": 1.0,
            },
        ]
        draft = SkillDraft(
            name="test", code="pass", status=DraftStatus.TESTED, test_results=results
        )
        output = review_skill(draft)
        assert "2/3 tests passed" in output


class TestPublishSkill:
    async def test_publish_without_approval_rejected(self):
        draft = SkillDraft(name="test", code="pass", status=DraftStatus.TESTED)
        registry = MagicMock()
        result = await publish_skill(draft, approved=False, skills_dir="/tmp", registry=registry)
        assert "not approved" in result
        registry.register_skill.assert_not_called()

    async def test_publish_with_draft_status_rejected(self):
        draft = SkillDraft(name="test", code="pass", status=DraftStatus.DRAFT)
        registry = MagicMock()
        result = await publish_skill(draft, approved=True, skills_dir="/tmp", registry=registry)
        assert "cannot be published" in result
        assert "draft" in result
        registry.register_skill.assert_not_called()

    async def test_publish_with_reviewed_status_succeeds(self):
        draft = SkillDraft(
            name="test",
            code=VALID_SKILL_CODE,
            status=DraftStatus.REVIEWED,
            meta={"name": "test"},
        )
        registry = MagicMock()
        result = await publish_skill(draft, approved=True, skills_dir="/tmp", registry=registry)
        assert "published successfully" in result
        registry.register_skill.assert_called_once_with("test", VALID_SKILL_CODE, {"name": "test"})

    async def test_publish_with_approved_status_succeeds(self):
        draft = SkillDraft(
            name="test",
            code=VALID_SKILL_CODE,
            status=DraftStatus.APPROVED,
            meta={"name": "test"},
        )
        registry = MagicMock()
        result = await publish_skill(draft, approved=True, skills_dir="/tmp", registry=registry)
        assert "published successfully" in result
        registry.register_skill.assert_called_once()

    async def test_publish_with_tested_status_succeeds(self):
        draft = SkillDraft(
            name="test",
            code=VALID_SKILL_CODE,
            status=DraftStatus.TESTED,
            meta={"name": "test"},
            test_results=[
                {
                    "passed": True,
                    "args": {},
                    "actual": None,
                    "expected": None,
                    "error": None,
                    "timed_out": False,
                    "execution_time_ms": 1.0,
                },
            ],
        )
        registry = MagicMock()
        result = await publish_skill(draft, approved=True, skills_dir="/tmp", registry=registry)
        assert "published successfully" in result
        registry.register_skill.assert_called_once()

    async def test_publish_with_rejected_status_blocked(self):
        draft = SkillDraft(name="test", code="pass", status=DraftStatus.REJECTED)
        registry = MagicMock()
        result = await publish_skill(draft, approved=True, skills_dir="/tmp", registry=registry)
        assert "cannot be published" in result
        registry.register_skill.assert_not_called()

    async def test_publish_with_failing_tests_blocked(self):
        draft = SkillDraft(
            name="test",
            code="pass",
            status=DraftStatus.TESTED,
            test_results=[
                {
                    "passed": True,
                    "args": {},
                    "actual": None,
                    "expected": None,
                    "error": None,
                    "timed_out": False,
                    "execution_time_ms": 1.0,
                },
                {
                    "passed": False,
                    "args": {},
                    "actual": None,
                    "expected": None,
                    "error": "fail",
                    "timed_out": False,
                    "execution_time_ms": 1.0,
                },
            ],
        )
        registry = MagicMock()
        result = await publish_skill(draft, approved=True, skills_dir="/tmp", registry=registry)
        assert "failing test" in result
        registry.register_skill.assert_not_called()

    async def test_publish_calls_registry_with_correct_args(self):
        draft = SkillDraft(
            name="my_skill",
            code=VALID_SKILL_CODE,
            meta={"name": "my_skill", "description": "A test skill"},
            status=DraftStatus.TESTED,
            test_results=[
                {
                    "passed": True,
                    "args": {},
                    "actual": None,
                    "expected": None,
                    "error": None,
                    "timed_out": False,
                    "execution_time_ms": 1.0,
                },
            ],
        )
        registry = MagicMock()
        await publish_skill(draft, approved=True, skills_dir="/tmp/skills", registry=registry)
        registry.register_skill.assert_called_once_with(
            "my_skill",
            VALID_SKILL_CODE,
            {"name": "my_skill", "description": "A test skill"},
        )

    async def test_publish_with_empty_test_results_passes(self):
        draft = SkillDraft(name="test", code="pass", status=DraftStatus.TESTED, test_results=[])
        registry = MagicMock()
        result = await publish_skill(draft, approved=True, skills_dir="/tmp", registry=registry)
        assert "published successfully" in result


class TestEscapedSkillCode:
    """Reproduce model-quality escaping issues in build_skill tool-call arguments.

    When a model emits Python source code inside a JSON tool-call argument,
    the JSON parser (json.loads) correctly unescapes standard JSON escapes.
    These tests verify that *after* JSON parsing --- i.e. the string that
    actually reaches ``draft_skill()`` --- certain malformed patterns are
    caught gracefully and returned as structured error drafts instead of
    crashing with an unhandled SyntaxError.
    """

    def test_escaped_triple_quotes_caught_gracefully(self):
        """Backslash before triple quotes -> no crash, returns error draft."""
        code = 'x = \\"""Get weather"""\n'
        draft = draft_skill("bad_escape", code)
        assert draft.status == DraftStatus.ERROR
        assert "validation failed" in draft.test_results[0].get("error", "")

    def test_escaped_newline_literal_caught_gracefully(self):
        """Literal \\n in code instead of real newline -> no crash, returns error draft."""
        code = 'def run():\\n    return 1\n'
        draft = draft_skill("bad_escape", code)
        assert draft.status == DraftStatus.ERROR
        assert "validation failed" in draft.test_results[0].get("error", "")

    def test_escaped_newline_literal_caught_gracefully(self):
        """Literal \\n in code instead of real newline -> structured error, no crash."""
        code = 'def run():\\n    return 1\n'
        draft = draft_skill("bad_escape", code)
        assert draft.status == DraftStatus.ERROR
        assert "validation failed" in draft.test_results[0].get("error", "")

    def test_sanitization_fixes_escaped_newlines(self):
        """Sanitization should turn literal \\n into real newlines so valid code parses."""
        code = 'SKILL_META = {"name": "sanitized", "permissions": {"network": False, "subprocess": False, "file_write": False}}\ndef run():\\n    return {"result": 1}\n'
        draft = draft_skill("sanitized", code)
        assert draft.status == DraftStatus.DRAFT
        assert draft.meta["name"] == "sanitized"

    def test_sanitization_fixes_escaped_triple_quotes(self):
        """Sanitization should remove backslashes before triple quotes."""
        code = 'SKILL_META = {"name": "doc_skill", "permissions": {"network": False, "subprocess": False, "file_write": False}}\ndef run():\\n    \\"""Get weather"""\\n    return {"result": 1}\n'
        draft = draft_skill("doc_skill", code)
        assert draft.status == DraftStatus.DRAFT
        assert draft.meta["name"] == "doc_skill"

    def test_well_formed_code_still_works(self):
        """A correctly formatted skill should pass as before."""
        draft = draft_skill("double", VALID_SKILL_CODE)
        assert draft.status == DraftStatus.DRAFT
        assert draft.meta["name"] == "double"

    def test_json_roundtrip_does_not_introduce_backslash(self):
        """PydanticAI receives JSON-encoded strings; json.loads turns \" into "
        and \\n into a real newline.  A correctly‑formatted triple‑quoted
        docstring survives round-trip intact."""
        import json
        original = (
            'SKILL_META = {"name": "good_docstring", "description": "A skill", '
            '"permissions": {"network": False, "subprocess": False, "file_write": False}}\n'
            'def run():\n    """Get weather"""\n    return 1\n'
        )
        json_encoded = json.dumps(original)
        decoded = json.loads(json_encoded)
        # Should parse cleanly --- *this* is what a well‑behaved model passes.
        draft = draft_skill("good_docstring", decoded)
        assert draft.code == original
        assert draft.status == DraftStatus.DRAFT


class TestSanitizeCode:
    def test_fixes_literal_newlines(self):
        raw = 'line1\\nline2'
        assert _sanitize_code(raw) == 'line1\nline2'

    def test_fixes_literal_tabs(self):
        raw = 'col1\\tcol2'
        assert _sanitize_code(raw) == 'col1\tcol2'

    def test_fixes_escaped_triple_quotes(self):
        raw = '\\"""docstring"""'
        assert _sanitize_code(raw) == '"""docstring"""'

    def test_does_not_break_valid_backslash_newline(self):
        raw = 'x = \\\n    1'
        assert _sanitize_code(raw) == 'x = \\\n    1'

    def test_does_not_alter_well_formed_code(self):
        assert _sanitize_code(VALID_SKILL_CODE) == VALID_SKILL_CODE

    def test_leaves_backslash_escaped_quote(self):
        raw = 'x = \\"hello\\"'
        assert _sanitize_code(raw) == 'x = "hello"'
