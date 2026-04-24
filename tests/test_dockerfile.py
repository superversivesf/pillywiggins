import re
from pathlib import Path

import pytest


def _dockerfile() -> str:
    path = Path(__file__).resolve().parent.parent / "Dockerfile"
    if not path.exists():
        pytest.skip("Dockerfile not found")
    return path.read_text()


def test_dockerfile_has_cmd():
    content = _dockerfile()
    assert "CMD" in content, "Dockerfile must define a CMD"


def test_dockerfile_cmd_does_not_hardcode_telegram():
    content = _dockerfile()
    cmd_match = re.search(r"^CMD\s+(.+)", content, re.MULTILINE | re.IGNORECASE)
    assert cmd_match, "Dockerfile must define a CMD"
    cmd = cmd_match.group(1)
    assert "--channel" not in cmd, (
        f"Dockerfile CMD should not hardcode --channel (got: {cmd}). Use --agent-id instead so channel is configured via agents.yaml."
    )


def test_dockerfile_cmd_uses_agent_id():
    content = _dockerfile()
    cmd_match = re.search(r"^CMD\s+(.+)", content, re.MULTILINE | re.IGNORECASE)
    assert cmd_match, "Dockerfile must define a CMD"
    cmd = cmd_match.group(1)
    assert "--agent-id" in cmd, (
        f"Dockerfile CMD should use --agent-id so the agent is resolved from agents.yaml (got: {cmd})."
    )


def test_dockerfile_cmd_entrypoint_is_python_module():
    content = _dockerfile()
    cmd_match = re.search(r"^CMD\s+(.+)", content, re.MULTILINE | re.IGNORECASE)
    assert cmd_match, "Dockerfile must define a CMD"
    cmd = cmd_match.group(1)
    # Accepts JSON or shell forms; check the raw string contains the expected module invocation
    assert '"python", "-m", "pillywiggins"' in cmd or "python -m pillywiggins" in cmd, (
        f"Dockerfile CMD should invoke pillywiggins (got: {cmd})."
    )
