"""Strict skill schema validation engine.

Parses skill source code with the ``ast`` module and returns a list of
actionable error messages so problems are caught before downstream
processing (registry loading, sandbox execution, etc.).
"""

from __future__ import annotations

import ast
import re
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

REQUIRED_META_KEYS = {"name", "description", "parameters", "permissions"}
VALID_PERMISSIONS_KEYS = {"network", "subprocess", "file_write"}

# Allowed imports for HTTP/networking in skill code.
ALLOWED_HTTP_IMPORTS = {
    "aiohttp",
    "urllib",
    "urllib.request",
    "urllib.parse",
    "urllib.error",
    "urllib.robotparser",
    "urllib.response",
}

# Disallowed third-party HTTP libraries.
DISALLOWED_IMPORTS = {"requests"}

# Dangerous call patterns that are blocked unless explicitly permitted.
DANGEROUS_PATTERNS = {
    "os.system": r"os\.system\s*\(",
    "subprocess.Popen": r"subprocess\.Popen\s*\(",
    "eval": r"\beval\s*\(",
    "exec": r"\bexec\s*\(",
    "__import__": r"__import__\s*\(",
}

# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _extract_literal_dict(node: ast.expr) -> Optional[dict]:
    """Attempt to safely evaluate an AST dict literal."""
    try:
        compiled = compile(ast.Expression(node), "<meta>", "eval")
        return eval(compiled)  # noqa: S307
    except Exception:
        return None


def _find_top_level_assignments(tree: ast.Module) -> list[ast.Assign]:
    """Return top-level assignments (not nested inside functions/classes)."""
    assignments: list[ast.Assign] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            assignments.append(node)
    return assignments


def _find_function_defs(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return top-level function definitions."""
    funcs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node)
    return funcs


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------


def validate_skill_code(
    code: str,
    permissions: Optional[dict[str, bool]] = None,
) -> tuple[bool, list[str]]:
    """Validate skill source code against the strict schema.

    Returns ``(True, [])`` when *code* conforms to the schema, otherwise
    ``(False, [error1, error2, ...])`` where each error is a human-readable
    string with a concrete fix suggestion.

    Checks performed:
    * Syntax validation via ``ast.parse``.
    * ``SKILL_META`` is a top-level dict assignment containing the required
      keys: ``name``, ``description``, ``parameters``, ``permissions``.
    * ``permissions`` (inside ``SKILL_META``) is a dict with keys
      ``network``, ``subprocess``, ``file_write``.  Lists are rejected with
      a clear example of the correct dict format.
    * An ``async def run(...)`` exists at the top level.
    * No disallowed imports (e.g. ``requests``) are used.
    * No dangerous calls (``os.system``, ``eval``, ``exec``,
      ``subprocess.Popen``) unless explicitly permitted.
    """
    errors: list[str] = []

    # --- 1. Syntax ---------------------------------------------------------
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, [f"Syntax error: {exc}"]

    # --- 2. SKILL_META -----------------------------------------------------
    meta: Optional[dict] = None
    meta_node: Optional[ast.Assign] = None
    for assign in _find_top_level_assignments(tree):
        for target in assign.targets:
            if isinstance(target, ast.Name) and target.id == "SKILL_META":
                meta_node = assign
                meta = _extract_literal_dict(assign.value)
                break
        if meta_node is not None:
            break

    if meta_node is None:
        errors.append("Code must contain a SKILL_META dict assignment at the top level.")
    elif meta is None:
        errors.append("SKILL_META must be a dict literal (name = {...}).")
    else:
        if not isinstance(meta, dict):
            errors.append(f"SKILL_META must be a dict, got {type(meta).__name__}.")
        else:
            missing = REQUIRED_META_KEYS - meta.keys()
            if missing:
                errors.append(
                    f"SKILL_META missing required keys: {sorted(missing)}. "
                    f"Expected keys are: {sorted(REQUIRED_META_KEYS)}."
                )

            # --- 2a. Permissions -----------------------------------------
            raw_permissions = meta.get("permissions")
            if raw_permissions is None:
                errors.append(
                    "SKILL_META['permissions'] is required. Example: "
                    "{'network': False, 'subprocess': False, 'file_write': False}"
                )
            elif isinstance(raw_permissions, list):
                errors.append(
                    f"permissions must be a dict, got list: {raw_permissions!r}. "
                    "Use {'network': True, 'subprocess': False, 'file_write': False} instead."
                )
            elif not isinstance(raw_permissions, dict):
                errors.append(
                    f"permissions must be a dict, got {type(raw_permissions).__name__}: "
                    f"{raw_permissions!r}. Use a dict like "
                    "{'network': False, 'subprocess': False, 'file_write': False}."
                )
            else:
                for key in raw_permissions.keys():
                    if key not in VALID_PERMISSIONS_KEYS:
                        errors.append(
                            f"Invalid permission key '{key}'. Valid keys are: "
                            f"{sorted(VALID_PERMISSIONS_KEYS)}."
                        )

    # --- 3. run() function -------------------------------------------------
    run_found = False
    run_is_async = False
    for func in _find_function_defs(tree):
        if func.name == "run":
            run_found = True
            run_is_async = isinstance(func, ast.AsyncFunctionDef)
            break

    if not run_found:
        errors.append("Code must contain an async def run() function at the top level.")
    elif not run_is_async:
        errors.append("run() must be declared as 'async def run(...)'.")

    # --- 4. Imports whitelist / blacklist ----------------------------------
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[0]
                if alias.name in DISALLOWED_IMPORTS or base in DISALLOWED_IMPORTS:
                    errors.append(
                        f"Import '{alias.name}' is not allowed. "
                        f"Use 'aiohttp' or 'urllib' instead."
                    )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            base = module.split(".")[0]
            if module in DISALLOWED_IMPORTS or base in DISALLOWED_IMPORTS:
                errors.append(
                    f"Import from '{module}' is not allowed. "
                    f"Use 'aiohttp' or 'urllib' instead."
                )

    # --- 5. Dangerous patterns ---------------------------------------------
    granted = permissions or {}
    for pattern_name, regex in DANGEROUS_PATTERNS.items():
        if pattern_name == "subprocess.Popen" and granted.get("subprocess"):
            continue
        if re.search(regex, code):
            errors.append(f"Code contains dangerous pattern: {pattern_name}")

    if errors:
        return False, errors
    return True, []
