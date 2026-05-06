import ast
import enum
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pillywiggins.skills import schema
from pillywiggins.skills.sandbox import SandboxResult, run_sandboxed, run_test_driven

logger = logging.getLogger(__name__)


class DraftStatus(enum.Enum):
    DRAFT = "draft"
    TESTED = "tested"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    ERROR = "error"


DANGEROUS_PATTERNS = {
    "os.system": r"os\.system\s*\(",
    "subprocess.Popen": r"subprocess\.Popen\s*\(",
    "eval": r"\beval\s*\(",
    "exec": r"\bexec\s*\(",
    "__import__": r"__import__\s*\(",
}


def _sanitize_code(code: str) -> str:
    r"""Attempt to fix common LLM mis-escaping patterns.

    Common issues:
    - Literal ``\n`` instead of actual newlines.
    - Literal ``\t`` instead of actual tabs.
    - Backslash-escaped triple quotes ``\"""``.
    """
    # Replace literal backslash-newline with actual newline
    # But be careful not to break valid escape sequences like \"
    sanitized = code

    # Fix literal \\n (two chars: backslash, n) -> newline
    sanitized = re.sub(r"(?<!\\)\\n", "\n", sanitized)

    # Fix literal \\t -> tab
    sanitized = re.sub(r"(?<!\\)\\t", "\t", sanitized)

    # Fix backslash before triple quotes (common in docstrings)
    sanitized = sanitized.replace('\\"""', '"""')

    # Fix backslash before single quotes
    sanitized = sanitized.replace("\\'", "'")

    # Remove trailing backslashes at end of lines that are line-continuation characters
    # when they appear before a quote. This is a heuristic.
    sanitized = re.sub(r'\\("""|\'\'\'|"|\')', r'\1', sanitized)

    return sanitized


def _extract_meta_from_comments(code: str) -> dict:
    """Parse comment-format SKILL_META block into a dict.

    Lines starting with ``# SKILL_META``, ``# name:``, ``# description:``,
    etc.  Values are parsed as JSON when possible; otherwise kept as plain
    strings.
    """
    meta: dict[str, Any] = {}
    in_block = False
    for line in code.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            if in_block:
                break
            continue
        comment_text = stripped[1:].strip()
        if comment_text.startswith("SKILL_META"):
            in_block = True
            continue
        if not in_block:
            continue
        if ":" not in comment_text:
            continue
        key, value = comment_text.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        try:
            parsed: Any = json.loads(value)
            meta[key] = parsed
        except (json.JSONDecodeError, ValueError):
            meta[key] = value
    return meta


def _extract_meta(code: str) -> dict:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        comment_meta = _extract_meta_from_comments(code)
        if comment_meta:
            return comment_meta
        return {"error": f"Syntax error in skill code: {e}"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SKILL_META":
                    try:
                        compiled = compile(ast.Expression(node.value), "<meta>", "eval")
                        return eval(compiled)
                    except Exception:
                        pass
    # AST didn't find a dict assignment; try comment-format fallback
    return _extract_meta_from_comments(code)


@dataclass
class SkillDraft:
    name: str
    code: str
    meta: dict = field(default_factory=dict)
    status: DraftStatus = DraftStatus.DRAFT
    test_results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def permissions(self) -> dict[str, bool]:
        perm_meta = self.meta.get("permissions", {})
        if isinstance(perm_meta, list):
            perm_meta = {k: True for k in perm_meta}
        legacy_network = self.meta.get("network_access", False)
        permissions = {
            "network": perm_meta.get("network", False) or legacy_network,
            "subprocess": perm_meta.get("subprocess", False),
            "file_write": perm_meta.get("file_write", False),
        }
        return permissions


def draft_skill(name: str, code: str) -> SkillDraft:
    # Try sanitization first for common LLM mis-escaping
    sanitized = _sanitize_code(code)
    meta = _extract_meta(sanitized)
    if "error" in meta:
        # Sanitization didn't help; try raw code as fallback
        meta_raw = _extract_meta(code)
        if "error" not in meta_raw:
            # Raw code parses, use it
            sanitized = code
            meta = meta_raw
        else:
            # Both sanitized and raw have syntax errors; prefer the original for reporting
            sanitized = code
            meta = meta_raw
            return SkillDraft(
                name=name,
                code=sanitized,
                meta=meta,
                status=DraftStatus.ERROR,
                test_results=[
                    {
                        "passed": False,
                        "error": meta["error"],
                    }
                ],
            )

    perm_meta = meta.get("permissions", {})
    if isinstance(perm_meta, list):
        perm_meta = {k: True for k in perm_meta}
    permissions = {
        "network": perm_meta.get("network", False)
        or meta.get("network_access", False),
        "subprocess": perm_meta.get("subprocess", False),
        "file_write": perm_meta.get("file_write", False),
    }
    valid, errors = schema.validate_skill_code(sanitized, permissions)
    if not valid:
        return SkillDraft(
            name=name,
            code=sanitized,
            meta={**meta, "schema_errors": errors},
            status=DraftStatus.ERROR,
            test_results=[
                {
                    "passed": False,
                    "error": f"Schema validation failed ({len(errors)} errors): " + "; ".join(errors),
                }
            ],
        )

    return SkillDraft(name=name, code=sanitized, meta=meta, status=DraftStatus.DRAFT)


async def test_skill(draft: SkillDraft, test_cases: list[dict[str, Any]]) -> SkillDraft:
    # If draft already has a syntax/validation error, surface it immediately
    if "error" in draft.meta:
        draft.status = DraftStatus.TESTED
        if not draft.test_results:
            draft.test_results = [
                {
                    "args": {},
                    "expected": None,
                    "passed": False,
                    "actual": None,
                    "error": draft.meta["error"],
                    "timed_out": False,
                    "execution_time_ms": 0.0,
                }
            ]
        return draft

    results = []
    for case in test_cases:
        args = case.get("args", {})
        expected = case.get("expected")

        try:
            sandbox_result: SandboxResult = await run_sandboxed(
                draft.code,
                args,
                draft.permissions,
            )

            if not sandbox_result.success:
                results.append(
                    {
                        "args": args,
                        "expected": expected,
                        "passed": False,
                        "actual": None,
                        "error": sandbox_result.error,
                        "timed_out": sandbox_result.timed_out,
                        "execution_time_ms": sandbox_result.execution_time_ms,
                    }
                )
                continue

            actual = sandbox_result.result
            passed = actual == expected if expected is not None else True

            results.append(
                {
                    "args": args,
                    "expected": expected,
                    "passed": passed,
                    "actual": actual,
                    "error": None,
                    "timed_out": False,
                    "execution_time_ms": sandbox_result.execution_time_ms,
                }
            )
        except Exception as e:
            results.append(
                {
                    "args": args,
                    "expected": expected,
                    "passed": False,
                    "actual": None,
                    "error": str(e),
                    "timed_out": False,
                    "execution_time_ms": 0.0,
                }
            )

    draft.test_results = results
    draft.status = DraftStatus.TESTED
    return draft


def validate_tests(test_code: str) -> tuple[bool, str]:
    """Check whether *test_code* is syntactically valid Python.

    Returns:
        (True, "") if the code parses cleanly, otherwise (False, error_msg).
    """
    try:
        ast.parse(test_code)
    except SyntaxError as e:
        return False, f"Syntax error in test code: {e}"
    return True, ""


async def test_driven_skill(name: str, code: str, test_code: str) -> SkillDraft:
    """Validate both skill code and test code, then run tests via sandbox.

    This is the TDD path: the user (or agent) provides both the skill
    implementation and the test assertions.  We verify that both parse,
    then inject the test code into a sandbox alongside the skill code.

    Args:
        name: Skill name.
        code: Skill source code (must contain SKILL_META and run()).
        test_code: Python test source.  It executes in the same module
            scope as the skill code, so it can call ``run()`` directly.

    Returns:
        A SkillDraft with status DRAFT (both valid, tests passed) or
        ERROR (validation failure or test failure).  Results are stored in
        ``test_results``.
    """
    # Step 1: validate skill code
    draft = draft_skill(name, code)
    if draft.status == DraftStatus.ERROR:
        return draft

    # Step 2: validate test code parses
    valid_test, test_error = validate_tests(test_code)
    if not valid_test:
        return SkillDraft(
            name=name,
            code=code,
            meta=draft.meta,
            status=DraftStatus.ERROR,
            test_results=[
                {
                    "passed": False,
                    "error": f"Test code validation failed: {test_error}",
                }
            ],
        )

    # Step 3: run the combined test in the sandbox
    try:
        sandbox_result: SandboxResult = await run_test_driven(
            draft.code,
            test_code,
            draft.permissions,
        )
    except Exception as exc:
        return SkillDraft(
            name=name,
            code=code,
            meta=draft.meta,
            status=DraftStatus.ERROR,
            test_results=[
                {
                    "passed": False,
                    "error": f"Test execution error: {exc}",
                }
            ],
        )

    if not sandbox_result.success:
        return SkillDraft(
            name=name,
            code=code,
            meta=draft.meta,
            status=DraftStatus.ERROR,
            test_results=[
                {
                    "passed": False,
                    "error": sandbox_result.error,
                    "execution_time_ms": sandbox_result.execution_time_ms,
                }
            ],
        )

    # All good
    return SkillDraft(
        name=name,
        code=code,
        meta=draft.meta,
        status=DraftStatus.DRAFT,
        test_results=[
            {
                "passed": True,
                "error": None,
                "result": sandbox_result.result,
                "execution_time_ms": sandbox_result.execution_time_ms,
            }
        ],
    )


def review_skill(draft: SkillDraft) -> str:
    lines = []
    lines.append(f"=== Skill Review: {draft.name} ===")
    lines.append(f"Status: {draft.status.value}")
    schema_errors = draft.meta.get("schema_errors")
    if draft.status == DraftStatus.ERROR and schema_errors:
        lines.append("")
        lines.append("--- Schema Validation Errors ---")
        for err in schema_errors:
            lines.append(f"  • {err}")
    lines.append("")
    lines.append("--- Code ---")
    lines.append(draft.code)
    lines.append("")
    lines.append("--- Test Results ---")

    if not draft.test_results:
        lines.append("No test results available.")
    else:
        passed_count = sum(1 for r in draft.test_results if r["passed"])
        total_count = len(draft.test_results)
        lines.append(f"{passed_count}/{total_count} tests passed")
        lines.append("")

        for i, result in enumerate(draft.test_results, 1):
            status = "PASS" if result["passed"] else "FAIL"
            lines.append(f"  Test {i}: [{status}]")
            lines.append(f"    Args: {result['args']}")
            if result.get("expected") is not None:
                lines.append(f"    Expected: {result['expected']}")
            lines.append(f"    Actual: {result.get('actual')}")
            if result.get("error"):
                lines.append(f"    Error: {result['error']}")
            lines.append(f"    Time: {result.get('execution_time_ms', 0):.1f}ms")

    lines.append("")
    lines.append(f"⚠ User approval is required to publish this skill.")
    return "\n".join(lines)


async def publish_skill(
    draft: SkillDraft,
    approved: bool,
    skills_dir: str,
    registry: Any,
    nats_bus: Any = None,
) -> str:
    if not approved:
        return f"Skill '{draft.name}' publication was not approved."

    if draft.status == DraftStatus.ERROR:
        details = ""
        schema_errors = draft.meta.get("schema_errors")
        if schema_errors:
            details = " Schema errors: " + "; ".join(schema_errors)
        return f"Skill '{draft.name}' cannot be published: status is 'error', fix errors before publishing.{details}"

    if draft.status not in (DraftStatus.TESTED, DraftStatus.REVIEWED, DraftStatus.APPROVED):
        return f"Skill '{draft.name}' cannot be published: status is '{draft.status.value}', must be 'tested', 'reviewed', or 'approved'."

    if draft.test_results:
        failed = [r for r in draft.test_results if not r["passed"]]
        if failed:
            error_parts = []
            for r in failed:
                if r.get("error"):
                    error_parts.append(r["error"])
            detail = " Errors: " + "; ".join(error_parts) if error_parts else ""
            return f"Skill '{draft.name}' has {len(failed)} failing test(s). Fix before publishing.{detail}"

    skill = registry.register_skill(draft.name, draft.code, draft.meta)
    if skill is None:
        error_msg = ""
        if hasattr(registry, "load_errors") and registry.load_errors:
            error_msg = f" Registry error: {registry.load_errors[-1]}"
        return f"Skill '{draft.name}' was written but could not be loaded.{error_msg}"

    # Only broadcast if the skill was actually registered
    if nats_bus is not None:
        try:
            await nats_bus.publish_broadcast(
                "skill_deployed",
                {
                    "skill_name": draft.name,
                    "agent_id": getattr(nats_bus, "_agent_id", "unknown"),
                    "deployed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:
            logger.warning("Failed to broadcast skill_deployed for %s", draft.name, exc_info=True)

    return f"Skill '{draft.name}' published successfully."
