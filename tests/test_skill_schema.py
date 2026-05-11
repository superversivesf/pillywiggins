"""Tests for the strict skill schema validation engine.

These tests verify that ``validate_skill_code`` in ``schema.py``
catches structural errors, bad permissions, disallowed imports, and
dangerous patterns with actionable error messages.
"""

from __future__ import annotations

import pytest

from pillywiggins.skills.schema import (
    DANGEROUS_PATTERNS,
    REQUIRED_META_KEYS,
    VALID_PERMISSIONS_KEYS,
    validate_skill_code,
)


# ---------------------------------------------------------------------------
# Helpers: valid / invalid code snippets
# ---------------------------------------------------------------------------

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

CODE_MISSING_META = """\
async def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""

CODE_MISSING_RUN = """\
SKILL_META = {
    "name": "broken",
    "description": "No run function",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

def compute(x):
    return x * 2
"""

CODE_SYNC_RUN = """\
SKILL_META = {
    "name": "sync",
    "description": "Sync run",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

def run(x: int = 0) -> dict:
    return {"result": x * 2}
"""

CODE_SYNTAX_ERROR = """\
SKILL_META = {"name": "bad", "description": "x", "parameters": {}, "permissions": {}}
async def run(:
    return {}
"""

CODE_LIST_PERMISSIONS = """\
SKILL_META = {
    "name": "list_perm",
    "description": "List permissions",
    "parameters": {},
    "permissions": ["network"],
}

async def run() -> dict:
    return {}
"""

CODE_STR_PERMISSIONS = """\
SKILL_META = {
    "name": "str_perm",
    "description": "String permissions",
    "parameters": {},
    "permissions": "network",
}

async def run() -> dict:
    return {}
"""

CODE_UNKNOWN_PERMISSION_KEY = """\
SKILL_META = {
    "name": "bad_key",
    "description": "Unknown permission key",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False, "magic": True},
}

async def run() -> dict:
    return {}
"""

CODE_MISSING_REQUIRED_META_KEYS = """\
SKILL_META = {
    "name": "partial",
    "description": "Missing parameters and permissions",
}

async def run() -> dict:
    return {}
"""

CODE_WITH_EVAL = """\
SKILL_META = {
    "name": "evil",
    "description": "Eval",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}
async def run(expr: str = "") -> dict:
    return {"result": eval(expr)}
"""

CODE_WITH_EXEC = """\
SKILL_META = {
    "name": "evil",
    "description": "Exec",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}
async def run(cmd: str = "") -> dict:
    exec(cmd)
    return {"done": True}
"""

CODE_WITH_OS_SYSTEM = """\
SKILL_META = {
    "name": "evil",
    "description": "OS system",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}
import os
async def run(cmd: str = "") -> dict:
    os.system(cmd)
    return {"done": True}
"""

CODE_WITH_SUBPROCESS_POPEN = """\
SKILL_META = {
    "name": "evil",
    "description": "Subprocess",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}
import subprocess
async def run(cmd: str = "") -> dict:
    subprocess.Popen(cmd.split())
    return {"done": True}
"""

CODE_WITH_SUBPROCESS_ALLOWED = """\
SKILL_META = {
    "name": "runner",
    "description": "Runs subprocesses",
    "parameters": {},
    "permissions": {"network": False, "subprocess": True, "file_write": False},
}
import subprocess
async def run(cmd: str = "") -> dict:
    subprocess.Popen(cmd.split())
    return {"done": True}
"""

CODE_WITH_IMPORT = """\
SKILL_META = {
    "name": "evil",
    "description": "Dynamic import",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}
async def run(mod: str = "") -> dict:
    m = __import__(mod)
    return {"module": str(m)}
"""

CODE_WITH_REQUESTS = """\
SKILL_META = {
    "name": "http",
    "description": "Uses requests",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}
import requests
async def run() -> dict:
    r = requests.get("https://example.com")
    return {"status": r.status_code}
"""

CODE_WITH_AIOHTTP = """\
SKILL_META = {
    "name": "http",
    "description": "Uses aiohttp",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}
import aiohttp
async def run() -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get("https://example.com") as resp:
            return {"status": resp.status}
"""

CODE_WITH_URLLIB = """\
SKILL_META = {
    "name": "http",
    "description": "Uses urllib",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}
import urllib.request
async def run() -> dict:
    with urllib.request.urlopen("https://example.com") as resp:
        return {"status": resp.status}
"""

CODE_NESTED_RUN = """\
SKILL_META = {
    "name": "nested",
    "description": "run inside a class",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

class Helper:
    async def run(self):
        return {}
"""


# ---------------------------------------------------------------------------
# Tests: schema constants
# ---------------------------------------------------------------------------


class TestSchemaConstants:
    @pytest.mark.parametrize(
        "name,expected",
        [
            pytest.param("REQUIRED_META_KEYS", {"name", "description", "parameters", "permissions"}, id="required_meta_keys"),
            pytest.param("VALID_PERMISSIONS_KEYS", {"network", "subprocess", "file_write"}, id="valid_permissions_keys"),
        ],
    )
    def test_schema_constants(self, name, expected):
        assert globals()[name] == expected

    def test_dangerous_patterns_is_dict(self):
        assert isinstance(DANGEROUS_PATTERNS, dict)
        assert all(isinstance(v, str) for v in DANGEROUS_PATTERNS.values())


# ---------------------------------------------------------------------------
# Tests: happy path
# ---------------------------------------------------------------------------


class TestValidSkillCode:
    def test_valid_code_passes(self):
        ok, errors = validate_skill_code(VALID_SKILL_CODE)
        assert ok is True
        assert errors == []

    def test_aiohttp_import_allowed(self):
        ok, errors = validate_skill_code(CODE_WITH_AIOHTTP)
        assert ok is True
        assert errors == []

    def test_urllib_import_allowed(self):
        ok, errors = validate_skill_code(CODE_WITH_URLLIB)
        assert ok is True
        assert errors == []

    def test_subprocess_allowed_with_permission(self):
        ok, errors = validate_skill_code(
            CODE_WITH_SUBPROCESS_ALLOWED,
            permissions={"network": False, "subprocess": True, "file_write": False},
        )
        assert ok is True


# ---------------------------------------------------------------------------
# Tests: structural errors
# ---------------------------------------------------------------------------


class TestStructuralErrors:
    @pytest.mark.parametrize(
        "code,checker",
        [
            pytest.param(
                CODE_MISSING_META,
                lambda errors: any("SKILL_META" in e for e in errors),
                id="missing_skill_meta",
            ),
            pytest.param(
                CODE_MISSING_RUN,
                lambda errors: any("run()" in e and "async" in e for e in errors),
                id="missing_run_function",
            ),
            pytest.param(
                CODE_SYNC_RUN,
                lambda errors: any("async" in e for e in errors),
                id="sync_run_rejected",
            ),
            pytest.param(
                CODE_SYNTAX_ERROR,
                lambda errors: any("Syntax error" in e for e in errors),
                id="syntax_error",
            ),
            pytest.param(
                CODE_NESTED_RUN,
                lambda errors: any("async def run()" in e for e in errors),
                id="nested_run_not_found",
            ),
        ],
    )
    def test_structural_errors(self, code, checker):
        ok, errors = validate_skill_code(code)
        assert ok is False
        assert checker(errors)


# ---------------------------------------------------------------------------
# Tests: permissions validation
# ---------------------------------------------------------------------------


class TestPermissionsValidation:
    @pytest.mark.parametrize(
        "code,checker",
        [
            pytest.param(
                CODE_LIST_PERMISSIONS,
                lambda errors: (
                    (err := next(e for e in errors if "permissions" in e.lower()))
                    and "dict" in err.lower()
                    and "list" in err.lower()
                    and "{" in err
                ),
                id="list_permissions",
            ),
            pytest.param(
                CODE_STR_PERMISSIONS,
                lambda errors: (
                    (err := next(e for e in errors if "permissions" in e.lower()))
                    and "dict" in err.lower()
                    and "str" in err.lower()
                ),
                id="string_permissions",
            ),
            pytest.param(
                CODE_UNKNOWN_PERMISSION_KEY,
                lambda errors: (
                    any("magic" in e for e in errors)
                    and any("Invalid permission key" in e for e in errors)
                ),
                id="unknown_key",
            ),
            pytest.param(
                CODE_MISSING_REQUIRED_META_KEYS,
                lambda errors: any("permissions" in e.lower() for e in errors),
                id="missing_permissions",
            ),
        ],
    )
    def test_permissions(self, code, checker):
        ok, errors = validate_skill_code(code)
        assert ok is False
        assert checker(errors)


# ---------------------------------------------------------------------------
# Tests: dangerous patterns
# ---------------------------------------------------------------------------


class TestDangerousPatterns:
    @pytest.mark.parametrize(
        "code,keyword",
        [
            pytest.param(CODE_WITH_EVAL, "eval", id="eval"),
            pytest.param(CODE_WITH_EXEC, "exec", id="exec"),
            pytest.param(CODE_WITH_OS_SYSTEM, "os.system", id="os_system"),
            pytest.param(CODE_WITH_SUBPROCESS_POPEN, "subprocess.Popen", id="subprocess_popen"),
            pytest.param(CODE_WITH_IMPORT, "__import__", id="import"),
        ],
    )
    def test_dangerous_patterns_blocked(self, code, keyword):
        ok, errors = validate_skill_code(code)
        assert ok is False
        assert any(keyword in e for e in errors)

    def test_subprocess_still_blocked_without_permission(self):
        ok, errors = validate_skill_code(
            CODE_WITH_SUBPROCESS_ALLOWED,
            permissions={"network": False, "subprocess": False, "file_write": False},
        )
        assert ok is False
        assert any("subprocess.Popen" in e for e in errors)

    def test_os_system_never_allowed(self):
        code = """\
SKILL_META = {
    "name": "evil",
    "description": "All perms",
    "parameters": {},
    "permissions": {"network": True, "subprocess": True, "file_write": True},
}
import os
async def run(cmd: str = "") -> dict:
    os.system(cmd)
    return {"done": True}
"""
        ok, errors = validate_skill_code(code, permissions={"subprocess": True})
        assert ok is False
        assert any("os.system" in e for e in errors)


# ---------------------------------------------------------------------------
# Tests: import whitelist / blacklist
# ---------------------------------------------------------------------------


class TestImportRestrictions:
    def test_requests_import_rejected(self):
        ok, errors = validate_skill_code(CODE_WITH_REQUESTS)
        assert ok is False
        assert any("requests" in e for e in errors)
        assert any("not allowed" in e.lower() for e in errors)

    def test_from_requests_import_rejected(self):
        code = """\
SKILL_META = {
    "name": "http",
    "description": "from requests",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}
from requests import get
async def run() -> dict:
    r = get("https://example.com")
    return {"status": r.status_code}
"""
        ok, errors = validate_skill_code(code)
        assert ok is False
        assert any("requests" in e for e in errors)

    def test_urllib_import_allowed(self):
        ok, errors = validate_skill_code(CODE_WITH_URLLIB)
        assert ok is True

    def test_aiohttp_import_allowed(self):
        ok, errors = validate_skill_code(CODE_WITH_AIOHTTP)
        assert ok is True


# ---------------------------------------------------------------------------
# Tests: multiple errors reported at once
# ---------------------------------------------------------------------------


class TestMultipleErrors:
    def test_multiple_errors_in_one_pass(self):
        """A broken skill can accumulate several independent errors."""
        code = """\
SKILL_META = {
    "name": "multi",
    "description": "Multiple problems",
}

import requests

def run(x):
    eval(x)
"""
        ok, errors = validate_skill_code(code)
        assert ok is False
        assert len(errors) >= 3
        # missing keys
        assert any("parameters" in e.lower() or "permissions" in e.lower() for e in errors)
        # sync run
        assert any("async" in e.lower() for e in errors)
        # requests
        assert any("requests" in e.lower() for e in errors)
        # eval
        assert any("eval" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Tests: error message usability
# ---------------------------------------------------------------------------


class TestErrorMessageUsability:
    @pytest.mark.parametrize(
        "code,checker",
        [
            pytest.param(
                CODE_LIST_PERMISSIONS,
                lambda errors: (
                    (err := next(e for e in errors if "list" in e.lower()))
                    and "Use {" in err
                    and "instead" in err.lower()
                ),
                id="list_permissions",
            ),
            pytest.param(
                CODE_UNKNOWN_PERMISSION_KEY,
                lambda errors: (
                    (err := next(e for e in errors if "Invalid permission key" in e))
                    and "network" in err
                    and "subprocess" in err
                    and "file_write" in err
                ),
                id="unknown_key",
            ),
            pytest.param(
                CODE_MISSING_REQUIRED_META_KEYS,
                lambda errors: "Expected keys" in next(
                    e for e in errors if "permissions" in e.lower()
                ),
                id="missing_permissions",
            ),
        ],
    )
    def test_actionable_messages(self, code, checker):
        ok, errors = validate_skill_code(code)
        assert ok is False
        assert checker(errors)
