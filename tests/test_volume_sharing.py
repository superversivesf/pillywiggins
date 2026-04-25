"""
Integration-style tests for the shared skills/ volume used by agent containers.

These tests verify:
1. docker-compose.yaml.example declares the named ``skills`` volume and mounts
   it into every agent service at ``/app/skills``.
2. A Docker-free simulation using a temporary directory proves that two
   independent ``SkillRegistry`` instances (modelling two agents) can read and
   write the same skill files through the shared directory.
3. File permission expectations match the current Dockerfile (root user).
"""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from pillywiggins.skills.registry import SkillRegistry

COMPOSE_PATH = Path(__file__).resolve().parent.parent / "docker-compose.yaml.example"
DOCKERFILE_PATH = Path(__file__).resolve().parent.parent / "Dockerfile"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "--version"],
            check=True,
            capture_output=True,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# docker-compose.yaml validation
# ---------------------------------------------------------------------------

def test_compose_declares_skills_volume():
    assert COMPOSE_PATH.exists(), "docker-compose.yaml.example should exist"
    data = yaml.safe_load(COMPOSE_PATH.read_text())
    volumes = data.get("volumes", {})
    assert "skills" in volumes, "'skills' named volume must be declared in volumes:"


def test_compose_agent_services_mount_skills_volume():
    data = yaml.safe_load(COMPOSE_PATH.read_text())
    services = data.get("services", {})

    agent_services = [
        name
        for name, svc in services.items()
        if str(svc.get("command", "")).startswith("python -m pillywiggins")
    ]
    assert agent_services, "Expected at least one agent service mounting /app/skills"

    for svc_name in agent_services:
        volumes = services[svc_name].get("volumes", [])
        assert any(
            str(v) == "skills:/app/skills" for v in volumes
        ), f"{svc_name} must mount 'skills:/app/skills'"


# ---------------------------------------------------------------------------
# Dockerfile user / permission documentation
# ---------------------------------------------------------------------------

def test_dockerfile_runs_as_root():
    """Documents that the Dockerfile lacks a USER directive.

    If a non-root user is introduced later this test should be updated to
    assert the expected UID/GID and verify the shared volume is writable
    by that user.
    """
    assert DOCKERFILE_PATH.exists(), "Dockerfile should exist"
    content = DOCKERFILE_PATH.read_text()
    assert "USER" not in content, (
        "Dockerfile does not define a USER directive, so containers run as root. "
        "Shared volume files will be created with root ownership. "
        "Update this test if you switch to a non-root runtime user."
    )


# ---------------------------------------------------------------------------
# Docker-free shared-volume simulation
# ---------------------------------------------------------------------------

def test_two_agents_can_share_skills_via_directory(tmp_path):
    """Simulate two agents sharing a skills/ directory (like a Docker volume)."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Agent A writes a skill
    reg_a = SkillRegistry(skills_dir=skills_dir)
    code = """\
SKILL_META = {
    "name": "shared_hello",
    "description": "A skill written by Agent A",
    "version": "1.0",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}
async def run():
    return "Hello from shared volume!"
"""
    meta = {
        "name": "shared_hello",
        "description": "A skill written by Agent A",
        "version": "1.0",
        "parameters": {},
        "permissions": {"network": False, "subprocess": False, "file_write": False},
    }
    reg_a.register_skill("shared_hello", code, meta)

    # Agent B loads from the same shared directory
    reg_b = SkillRegistry(skills_dir=skills_dir)
    reg_b.load_all()

    assert reg_b.has_skill("shared_hello"), (
        "Agent B should see the skill written by Agent A"
    )
    skill = reg_b.get_skill("shared_hello")
    assert skill is not None
    assert skill.description == "A skill written by Agent A"


def test_shared_volume_registry_json_is_readable(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    reg = SkillRegistry(skills_dir=skills_dir)
    code = """\
SKILL_META = {
    "name": "count",
    "description": "count",
    "version": "1.0",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}
async def run():
    return 1
"""
    meta = {
        "name": "count",
        "description": "count",
        "version": "1.0",
        "parameters": {},
        "permissions": {"network": False, "subprocess": False, "file_write": False},
    }
    reg.register_skill("count", code, meta)

    registry_path = skills_dir / "registry.json"
    assert registry_path.exists(), "registry.json should be created in shared volume"
    data = json.loads(registry_path.read_text())
    assert "skills" in data
    assert any(s["name"] == "count" for s in data["skills"])


def test_shared_volume_file_permissions(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    test_file = skills_dir / "perm_check.py"
    test_file.write_text("x = 1\n")

    mode = test_file.stat().st_mode
    # Owner should have at least read+write
    assert mode & 0o600 == 0o600, (
        f"Expected owner read+write permissions, got {oct(mode)}"
    )


# ---------------------------------------------------------------------------
# Optional Docker validation
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
def test_docker_compose_config_validates(tmp_path):
    """Run ``docker compose config`` to sanity-check the compose file."""
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_PATH), "config"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, (
        f"docker compose config failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
