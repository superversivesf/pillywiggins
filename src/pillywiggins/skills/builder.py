import ast
import enum
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from pillywiggins.skills.sandbox import SandboxResult, run_sandboxed


class DraftStatus(enum.Enum):
    DRAFT = "draft"
    TESTED = "tested"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


DANGEROUS_PATTERNS = {
    "os.system": r"os\.system\s*\(",
    "subprocess.Popen": r"subprocess\.Popen\s*\(",
    "eval": r"\beval\s*\(",
    "exec": r"\bexec\s*\(",
    "__import__": r"__import__\s*\(",
}


def validate_skill_code(
    code: str, permissions: Optional[dict[str, bool]] = None
) -> tuple[bool, str]:
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error: {e}"

    has_meta = "SKILL_META" in code
    if not has_meta:
        return False, "Code must contain a SKILL_META dict assignment"

    has_run = bool(re.search(r"(async\s+def|def)\s+run\s*\(", code))
    if not has_run:
        return False, "Code must contain an async def run() or def run() function"

    perm = permissions or {}
    for pattern, regex in DANGEROUS_PATTERNS.items():
        if pattern == "subprocess.Popen" and perm.get("subprocess"):
            continue
        if re.search(regex, code):
            return False, f"Code contains dangerous pattern: {pattern}"

    return True, ""


def _extract_meta(code: str) -> dict:
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SKILL_META":
                    try:
                        compiled = compile(ast.Expression(node.value), "<meta>", "eval")
                        return eval(compiled)
                    except Exception:
                        pass
    return {}


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
        legacy_network = self.meta.get("network_access", False)
        permissions = {
            "network": perm_meta.get("network", False) or legacy_network,
            "subprocess": perm_meta.get("subprocess", False),
            "file_write": perm_meta.get("file_write", False),
        }
        return permissions


def draft_skill(name: str, code: str) -> SkillDraft:
    meta = _extract_meta(code)
    permissions = {
        "network": meta.get("permissions", {}).get("network", False)
        or meta.get("network_access", False),
        "subprocess": meta.get("permissions", {}).get("subprocess", False),
        "file_write": meta.get("permissions", {}).get("file_write", False),
    }
    valid, error = validate_skill_code(code, permissions)
    if not valid:
        raise ValueError(f"Skill code validation failed: {error}")

    return SkillDraft(name=name, code=code, meta=meta, status=DraftStatus.DRAFT)


async def test_skill(draft: SkillDraft, test_cases: list[dict[str, Any]]) -> SkillDraft:
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


def review_skill(draft: SkillDraft) -> str:
    lines = []
    lines.append(f"=== Skill Review: {draft.name} ===")
    lines.append(f"Status: {draft.status.value}")
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
    lines.append(f"⚠ User approval is required to deploy this skill.")
    return "\n".join(lines)


async def deploy_skill(
    draft: SkillDraft,
    approved: bool,
    skills_dir: str,
    registry: Any,
    nats_bus: Any = None,
) -> str:
    if not approved:
        return f"Skill '{draft.name}' deployment was not approved."

    if draft.status not in (DraftStatus.TESTED, DraftStatus.REVIEWED, DraftStatus.APPROVED):
        return f"Skill '{draft.name}' cannot be deployed: status is '{draft.status.value}', must be 'tested', 'reviewed', or 'approved'."

    if draft.test_results:
        failed = [r for r in draft.test_results if not r["passed"]]
        if failed:
            return f"Skill '{draft.name}' has {len(failed)} failing test(s). Fix before deploying."

    registry.register_skill(draft.name, draft.code, draft.meta)

    if nats_bus is not None:
        try:
            await nats_bus.publish_broadcast(
                "skill_deployed",
                {
                    "skill_name": draft.name,
                    "meta": draft.meta,
                },
            )
        except Exception:
            pass

    return f"Skill '{draft.name}' deployed successfully."
