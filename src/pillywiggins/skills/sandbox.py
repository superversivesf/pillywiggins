import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

SAFE_ENV_VARS = {"PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE"}

DENIED_ENV_PATTERNS = (
    "DATABASE", "DB_", "SECRET", "TOKEN", "API_KEY", "PASSWORD",
    "AUTH", "CREDENTIAL", "PRIVATE", "OLLAMA_API_KEY", "OPENAI_API_KEY",
    "REDIS", "NATS", "POSTGRES", "PG_",
)

DEFAULT_TIMEOUT = 30


@dataclass
class SandboxResult:
    success: bool
    result: Any = None
    error: Optional[str] = None
    timed_out: bool = False
    execution_time_ms: float = 0.0


def restricted_env(permissions: dict[str, bool]) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in SAFE_ENV_VARS:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value

    if permissions.get("network"):
        env["SKILL_NETWORK"] = "1"
    if permissions.get("subprocess"):
        env["SKILL_SUBPROCESS"] = "1"
    if permissions.get("file_write"):
        env["SKILL_FILE_WRITE"] = "1"

    return env


def _is_dangerous_env(key: str) -> bool:
    upper = key.upper()
    for pattern in DENIED_ENV_PATTERNS:
        if upper.startswith(pattern) or upper == pattern:
            return True
    return False


_WRAPPER_TEMPLATE = """\
import json
import sys

{skill_code}

def _safe_str(exc):
    try:
        return str(exc)
    except Exception:
        try:
            return repr(exc)
        except Exception:
            return "Unknown error occurred."

if __name__ == "__main__":
    try:
        _args = json.loads(sys.argv[1]) if sys.argv[1] else {{}}
        _result = run(**_args)
        print(json.dumps({{"success": True, "result": _result}}))
    except Exception as _e:
        print(json.dumps({{"success": False, "error": _safe_str(_e)}}))
"""


_TEST_DRIVEN_WRAPPER = """\
import json
import sys

{skill_code}

def _safe_str(exc):
    try:
        return str(exc)
    except Exception:
        try:
            return repr(exc)
        except Exception:
            return "Unknown error occurred."

if __name__ == "__main__":
    errors = []
    try:
        exec({test_code!r})
    except AssertionError as e:
        errors.append("Assertion failed: " + str(e))
    except Exception as e:
        errors.append("Test error: " + str(e))

    if errors:
        print(json.dumps({{"success": False, "error": "\\n".join(errors)}}))
    else:
        print(json.dumps({{"success": True, "result": "All tests passed"}}))
"""


async def run_test_driven(
    code: str,
    test_code: str,
    permissions: dict[str, bool],
    timeout: int = DEFAULT_TIMEOUT,
) -> SandboxResult:
    """Run test code against skill code in a sandboxed subprocess.

    The skill code is included in the same module scope as the test code,
    so the test code can call ``run()`` directly.
    """
    env = restricted_env(permissions)
    start = time.monotonic()

    script = _TEST_DRIVEN_WRAPPER.format(skill_code=code, test_code=test_code)

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir="/tmp", delete=False,
        ) as f:
            f.write(script)
            script_path = f.name

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd="/tmp",
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                elapsed = (time.monotonic() - start) * 1000
                return SandboxResult(
                    success=False,
                    error=f"Sandbox timed out after {timeout}s",
                    timed_out=True,
                    execution_time_ms=elapsed,
                )

            elapsed = (time.monotonic() - start) * 1000

            if proc.returncode != 0:
                stderr_text = stderr.decode("utf-8", errors="replace").strip()
                return SandboxResult(
                    success=False,
                    error=f"Process exited with code {proc.returncode}: {stderr_text}",
                    execution_time_ms=elapsed,
                )

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            if not stdout_text:
                stderr_text = stderr.decode("utf-8", errors="replace").strip()
                return SandboxResult(
                    success=False,
                    error=f"No output from sandbox{': ' + stderr_text if stderr_text else ''}",
                    execution_time_ms=elapsed,
                )

            try:
                parsed = json.loads(stdout_text)
            except json.JSONDecodeError as e:
                stderr_text = stderr.decode("utf-8", errors="replace").strip()
                err_detail = f"Invalid JSON output: {e}"
                if stderr_text:
                    err_detail += f" | stderr: {stderr_text}"
                return SandboxResult(
                    success=False,
                    error=err_detail,
                    execution_time_ms=elapsed,
                )

            if not parsed.get("success", False):
                return SandboxResult(
                    success=False,
                    error=parsed.get("error", "Unknown test error"),
                    execution_time_ms=elapsed,
                )

            return SandboxResult(
                success=True,
                result=parsed.get("result"),
                execution_time_ms=elapsed,
            )

        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        logger.exception("Test-driven sandbox execution failed")
        return SandboxResult(
            success=False,
            error=str(e),
            execution_time_ms=elapsed,
        )


async def run_sandboxed(
    code: str,
    args: dict[str, Any],
    permissions: dict[str, bool],
    timeout: int = DEFAULT_TIMEOUT,
) -> SandboxResult:
    env = restricted_env(permissions)
    start = time.monotonic()

    script = _WRAPPER_TEMPLATE.format(skill_code=code)

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir="/tmp", delete=False,
        ) as f:
            f.write(script)
            script_path = f.name

        try:
            args_json = json.dumps(args)
            proc = await asyncio.create_subprocess_exec(
                sys.executable, script_path, args_json,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd="/tmp",
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                elapsed = (time.monotonic() - start) * 1000
                return SandboxResult(
                    success=False,
                    error=f"Sandbox timed out after {timeout}s",
                    timed_out=True,
                    execution_time_ms=elapsed,
                )

            elapsed = (time.monotonic() - start) * 1000

            if proc.returncode != 0:
                stderr_text = stderr.decode("utf-8", errors="replace").strip()
                return SandboxResult(
                    success=False,
                    error=f"Process exited with code {proc.returncode}: {stderr_text}",
                    execution_time_ms=elapsed,
                )

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            if not stdout_text:
                stderr_text = stderr.decode("utf-8", errors="replace").strip()
                return SandboxResult(
                    success=False,
                    error=f"No output from skill{': ' + stderr_text if stderr_text else ''}",
                    execution_time_ms=elapsed,
                )

            try:
                parsed = json.loads(stdout_text)
            except json.JSONDecodeError as e:
                stderr_text = stderr.decode("utf-8", errors="replace").strip()
                err_detail = f"Invalid JSON output: {e}"
                if stderr_text:
                    err_detail += f" | stderr: {stderr_text}"
                return SandboxResult(
                    success=False,
                    error=err_detail,
                    execution_time_ms=elapsed,
                )

            if not parsed.get("success", False):
                return SandboxResult(
                    success=False,
                    error=parsed.get("error", "Unknown skill error"),
                    execution_time_ms=elapsed,
                )

            return SandboxResult(
                success=True,
                result=parsed.get("result"),
                execution_time_ms=elapsed,
            )

        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        logger.exception("Sandbox execution failed")
        return SandboxResult(
            success=False,
            error=str(e),
            execution_time_ms=elapsed,
        )