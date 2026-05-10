import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any

from pillywiggins.security.prompt_sanitizer import sanitize_or_default

logger = logging.getLogger(__name__)

SAFE_ENV_VARS = {"PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE"}


DEFAULT_TIMEOUT = 30


@dataclass
class SandboxResult:
    success: bool
    result: Any = None
    error: str | None = None
    timed_out: bool = False
    execution_time_ms: float = 0.0


def _sanitize_sandbox_result(result: SandboxResult) -> SandboxResult:
    """Sanitize string result/error fields before returning to caller."""
    if result.result is not None and isinstance(result.result, str):
        result.result = sanitize_or_default(result.result, default="[Blocked]")
    if result.error is not None:
        result.error = sanitize_or_default(result.error, default="[Blocked]")
    return result


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



_WRAPPER_TEMPLATE = """\
import asyncio
import json
import sys
import traceback

{skill_code}

def _format_error(exc):
    tb = traceback.format_exc()
    msg = str(exc)
    if isinstance(exc, RuntimeError) and "no current event loop" in msg:
        return (
            "Event loop error: asyncio.get_event_loop() is not available in the test sandbox. "
            "Use asyncio.get_running_loop() or avoid calling the event loop directly."
            "\\n\\nOriginal traceback:\\n" + tb
        )
    return tb

async def _main():
    try:
        _args = json.loads(sys.argv[1]) if sys.argv[1] else {{}}
        _result = await run(**_args)
        print(json.dumps({{"success": True, "result": _result}}))
    except Exception as _e:
        print(json.dumps({{"success": False, "error": _format_error(_e)}}))

if __name__ == "__main__":
    asyncio.run(_main())
"""


_TEST_DRIVEN_WRAPPER = """\
import asyncio
import json
import sys
import traceback

{skill_code}

_original_run = run
def run(*args, **kwargs):
    result = _original_run(*args, **kwargs)
    if asyncio.iscoroutine(result):
        return asyncio.run(result)
    return result

def _format_error(exc):
    tb = traceback.format_exc()
    msg = str(exc)
    if isinstance(exc, RuntimeError) and "no current event loop" in msg:
        return (
            "Event loop error: asyncio.get_event_loop() is not available in the test sandbox. "
            "Use asyncio.get_running_loop() or avoid calling the event loop directly."
            "\\n\\nOriginal traceback:\\n" + tb
        )
    return tb

if __name__ == "__main__":
    errors = []
    try:
        exec({test_code!r})
    except AssertionError as e:
        errors.append("Assertion failed: " + _format_error(e))
    except Exception as e:
        errors.append("Test error: " + _format_error(e))

    if errors:
        print(json.dumps({{"success": False, "error": "\\n".join(errors)}}))
    else:
        print(json.dumps({{"success": True, "result": "All tests passed"}}))
"""


async def _run_subprocess(
    code: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    env_vars: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
) -> tuple[int | None, str, str, float]:
    """Run code in a sandboxed subprocess.

    Returns (exit_code, stdout, stderr, elapsed_ms).
    ``exit_code`` is ``None`` when the process was killed due to timeout.
    Raises on unexpected errors (e.g. filesystem failures).
    """
    start = time.monotonic()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir="/tmp", delete=False,
    ) as f:
        f.write(code)
        script_path = f.name

    try:
        cmd = [sys.executable, script_path]
        if extra_args:
            cmd.extend(extra_args)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env_vars or {},
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
            return None, "", "", elapsed

        elapsed = (time.monotonic() - start) * 1000
        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        return proc.returncode, stdout_text, stderr_text, elapsed

    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


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
    script = _TEST_DRIVEN_WRAPPER.format(skill_code=code, test_code=test_code)

    try:
        returncode, stdout, stderr, elapsed = await _run_subprocess(
            script, timeout=timeout, env_vars=env,
        )
    except Exception as e:
        logger.exception("Test-driven sandbox execution failed")
        return _sanitize_sandbox_result(SandboxResult(
            success=False,
            error=str(e),
            execution_time_ms=0,
        ))

    if returncode is None:
        return _sanitize_sandbox_result(SandboxResult(
            success=False,
            error=f"Sandbox timed out after {timeout}s",
            timed_out=True,
            execution_time_ms=elapsed,
        ))

    if returncode != 0:
        return _sanitize_sandbox_result(SandboxResult(
            success=False,
            error=f"Process exited with code {returncode}: {stderr}",
            execution_time_ms=elapsed,
        ))

    if not stdout:
        return _sanitize_sandbox_result(SandboxResult(
            success=False,
            error=f"No output from sandbox{': ' + stderr if stderr else ''}",
            execution_time_ms=elapsed,
        ))

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as e:
        err_detail = f"Invalid JSON output: {e}"
        if stderr:
            err_detail += f" | stderr: {stderr}"
        return _sanitize_sandbox_result(SandboxResult(
            success=False,
            error=err_detail,
            execution_time_ms=elapsed,
        ))

    if not parsed.get("success", False):
        err = parsed.get("error", "Unknown test error")
        if stderr and stderr.strip():
            err += f"\n\n[stderr]: {stderr.strip()}"
        return _sanitize_sandbox_result(SandboxResult(
            success=False,
            error=err,
            execution_time_ms=elapsed,
        ))

    return _sanitize_sandbox_result(SandboxResult(
        success=True,
        result=parsed.get("result"),
        execution_time_ms=elapsed,
    ))


async def run_sandboxed(
    code: str,
    args: dict[str, Any],
    permissions: dict[str, bool],
    timeout: int = DEFAULT_TIMEOUT,
) -> SandboxResult:
    env = restricted_env(permissions)
    script = _WRAPPER_TEMPLATE.format(skill_code=code)
    args_json = json.dumps(args)

    try:
        returncode, stdout, stderr, elapsed = await _run_subprocess(
            script, timeout=timeout, env_vars=env, extra_args=[args_json],
        )
    except Exception as e:
        logger.exception("Sandbox execution failed")
        return _sanitize_sandbox_result(SandboxResult(
            success=False,
            error=str(e),
            execution_time_ms=0,
        ))

    if returncode is None:
        return _sanitize_sandbox_result(SandboxResult(
            success=False,
            error=f"Sandbox timed out after {timeout}s",
            timed_out=True,
            execution_time_ms=elapsed,
        ))

    if returncode != 0:
        return _sanitize_sandbox_result(SandboxResult(
            success=False,
            error=f"Process exited with code {returncode}: {stderr}",
            execution_time_ms=elapsed,
        ))

    if not stdout:
        return _sanitize_sandbox_result(SandboxResult(
            success=False,
            error=f"No output from skill{': ' + stderr if stderr else ''}",
            execution_time_ms=elapsed,
        ))

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as e:
        err_detail = f"Invalid JSON output: {e}"
        if stderr:
            err_detail += f" | stderr: {stderr}"
        return _sanitize_sandbox_result(SandboxResult(
            success=False,
            error=err_detail,
            execution_time_ms=elapsed,
        ))

    if not parsed.get("success", False):
        err = parsed.get("error", "Unknown skill error")
        if stderr and stderr.strip():
            err += f"\n\n[stderr]: {stderr.strip()}"
        return _sanitize_sandbox_result(SandboxResult(
            success=False,
            error=err,
            execution_time_ms=elapsed,
        ))

    return _sanitize_sandbox_result(SandboxResult(
        success=True,
        result=parsed.get("result"),
        execution_time_ms=elapsed,
    ))