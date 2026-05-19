"""Tests for Docker security hardening: USER directive, HEALTHCHECK, and
docker-compose security fields (cap_drop, read_only, no-new-privileges,
deploy.resources.limits).
"""

from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dockerfile() -> str:
    path = Path(__file__).resolve().parent.parent / "Dockerfile"
    if not path.exists():
        pytest.skip("Dockerfile not found")
    return path.read_text()


def _compose_services():
    path = Path(__file__).resolve().parent.parent / "docker-compose.yaml.example"
    if not path.exists():
        pytest.skip("docker-compose.yaml.example not found")
    data = yaml.safe_load(path.read_text())
    return data.get("services", {})


# ---------------------------------------------------------------------------
# Dockerfile tests
# ---------------------------------------------------------------------------

def test_dockerfile_has_user_directive():
    """Dockerfile must contain a USER directive so the container does not run as root."""
    content = _dockerfile()
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
    user_lines = [line for line in lines if line.upper().startswith("USER ")]
    assert user_lines, (
        "Dockerfile must contain a USER directive (non-root user). "
        "Add 'USER appuser' after creating the appuser account."
    )


def test_dockerfile_user_is_not_root():
    """The USER directive must not be 'root' or 0."""
    content = _dockerfile()
    import re
    for match in re.finditer(r"^USER\s+(.+)$", content, re.MULTILINE | re.IGNORECASE):
        user = match.group(1).strip().strip('"').strip("'")
        assert user.lower() != "root", "USER directive must not be 'root'"
        assert user != "0", "USER directive must not be uid 0"


def test_dockerfile_has_healthcheck():
    """Dockerfile must contain a HEALTHCHECK directive."""
    content = _dockerfile()
    assert "HEALTHCHECK" in content.upper(), (
        "Dockerfile must contain a HEALTHCHECK directive."
    )


def test_dockerfile_creates_appuser():
    """Dockerfile must create a non-root user (e.g. 'RUN useradd -m appuser')."""
    content = _dockerfile()
    assert "useradd" in content.lower(), (
        "Dockerfile must create a non-root user with 'RUN useradd -m appuser' or similar."
    )


# ---------------------------------------------------------------------------
# docker-compose.yaml.example security tests
# ---------------------------------------------------------------------------

ALLOWED_SERVICES = {"postgres", "redis", "nats", "searxng"}
HARDENED_SERVICES = {"nats", "searxng"}


def _compose_services_live():
    path = Path(__file__).resolve().parent.parent / "docker-compose.yaml"
    if not path.exists():
        pytest.skip("docker-compose.yaml not found")
    data = yaml.safe_load(path.read_text())
    return data.get("services", {})


def _infra_services(services):
    """Return all infrastructure services (exclude agent services)."""
    return {k: v for k, v in services.items()
            if v is not None and k in ALLOWED_SERVICES}


def _hardened_services(services):
    """Return services that should be hardened with cap_drop, read_only, etc.
    Excludes databases (postgres, redis) which need write access to persistent volumes."""
    return {k: v for k, v in services.items()
            if v is not None and k in HARDENED_SERVICES}


def test_all_services_have_cap_drop_all():
    """Every hardened infrastructure service must have cap_drop: [ALL].
    Databases (postgres, redis) are excluded — they need kernel capabilities
    for chown, user switching, and writing to persistent volumes."""
    services = _hardened_services(_compose_services())
    missing = [name for name, svc in services.items()
               if svc.get("cap_drop") != ["ALL"]]
    assert not missing, (
        f"Services missing cap_drop: [ALL]: {missing}"
    )


def test_all_services_have_read_only():
    """Every hardened infrastructure service must have read_only: true.
    Databases are excluded."""
    services = _hardened_services(_compose_services())
    missing = [name for name, svc in services.items()
               if svc.get("read_only") is not True]
    assert not missing, (
        f"Services missing read_only: true: {missing}"
    )


def test_all_services_have_no_new_privileges():
    """Every hardened infrastructure service must have no-new-privileges:true
    (via security_opt or top-level compose v2 key). Databases excluded."""
    services = _hardened_services(_compose_services())

    def _has_no_new_priv(svc):
        if svc.get("no_new_privileges") is True:
            return True
        sec_opts = svc.get("security_opt", [])
        return "no-new-privileges:true" in sec_opts

    missing = [name for name, svc in services.items()
               if not _has_no_new_priv(svc)]
    assert not missing, (
        f"Services missing no-new-privileges:true (add security_opt or no_new_privileges): {missing}"
    )


def test_all_services_have_restart_unless_stopped():
    """Every infrastructure service must have restart: unless-stopped."""
    services = _infra_services(_compose_services())
    missing = [name for name, svc in services.items()
               if svc.get("restart") != "unless-stopped"]
    assert not missing, (
        f"Services missing restart: unless-stopped: {missing}"
    )


def test_all_services_have_healthcheck():
    """Every infrastructure service must have a healthcheck block."""
    services = _infra_services(_compose_services())
    missing = [name for name, svc in services.items()
               if "healthcheck" not in svc]
    assert not missing, (
        f"Services missing healthcheck block: {missing}"
    )


def test_all_services_have_deploy_resources_limits():
    """Every infrastructure service must have deploy.resources.limits
    with at least memory defined."""
    services = _infra_services(_compose_services())

    def _has_limits(svc):
        deploy = svc.get("deploy", {})
        resources = deploy.get("resources", {})
        limits = resources.get("limits", {})
        return "memory" in limits

    missing = [name for name, svc in services.items()
               if not _has_limits(svc)]
    assert not missing, (
        f"Services missing deploy.resources.limits.memory: {missing}"
    )


# ---------------------------------------------------------------------------
# docker-compose.yaml (live file) security tests
# ---------------------------------------------------------------------------


def test_live_services_have_cap_drop_all():
    """Every live hardened infrastructure service must have cap_drop: [ALL]."""
    services = _hardened_services(_compose_services_live())
    missing = [name for name, svc in services.items()
               if svc.get("cap_drop") != ["ALL"]]
    assert not missing, (
        f"Live services missing cap_drop: [ALL]: {missing}"
    )


def test_live_services_have_read_only():
    """Every live hardened infrastructure service must have read_only: true."""
    services = _hardened_services(_compose_services_live())
    missing = [name for name, svc in services.items()
               if svc.get("read_only") is not True]
    assert not missing, (
        f"Live services missing read_only: true: {missing}"
    )


def test_live_services_have_no_new_privileges():
    """Every live hardened infrastructure service must have no-new-privileges: true."""
    services = _hardened_services(_compose_services_live())

    def _has_no_new_priv(svc):
        if svc.get("no_new_privileges") is True:
            return True
        sec_opts = svc.get("security_opt", [])
        return "no-new-privileges:true" in sec_opts

    missing = [name for name, svc in services.items()
               if not _has_no_new_priv(svc)]
    assert not missing, (
        f"Live services missing no-new-privileges: true: {missing}"
    )


def test_live_services_have_deploy_resources_limits():
    """Every live infrastructure service must have deploy.resources.limits
    with at least memory defined."""
    services = _infra_services(_compose_services_live())

    def _has_limits(svc):
        deploy = svc.get("deploy", {})
        resources = deploy.get("resources", {})
        limits = resources.get("limits", {})
        return "memory" in limits

    missing = [name for name, svc in services.items()
               if not _has_limits(svc)]
    assert not missing, (
        f"Live services missing deploy.resources.limits.memory: {missing}"
    )


# ---------------------------------------------------------------------------
# .example agent template structure tests
# ---------------------------------------------------------------------------


def test_example_has_commented_agent_service():
    """docker-compose.yaml.example must contain a commented-out agent
    service block showing security fields."""
    path = Path(__file__).resolve().parent.parent / "docker-compose.yaml.example"
    raw = path.read_text()
    assert "# agent:" in raw, (
        "docker-compose.yaml.example must have a commented-out agent service template"
    )


def test_example_no_discord_specific_references():
    """docker-compose.yaml.example must not contain Discord-specific references
    (puck-discord, DISCORD_TOKEN, discord adapter)."""
    path = Path(__file__).resolve().parent.parent / "docker-compose.yaml.example"
    raw = path.read_text()
    disallowed = ["puck-discord", "DISCORD_TOKEN", "puck.adapters.discord"]
    for term in disallowed:
        assert term not in raw, (
            f"docker-compose.yaml.example must not contain '{term}'"
        )


def test_example_agent_template_has_security_fields():
    """The commented-out agent template must demonstrate all security fields:
    cap_drop, read_only, no_new_privileges, healthcheck, restart, deploy.resources.limits."""
    path = Path(__file__).resolve().parent.parent / "docker-compose.yaml.example"
    raw = path.read_text()
    required = ["cap_drop", "read_only", "security_opt",
                "healthcheck", "restart", "deploy", "resources", "limits"]
    missing = [field for field in required if field not in raw]
    assert not missing, (
        f"Agent template missing security fields: {missing}"
    )


# ---------------------------------------------------------------------------
# tmpfs tests (services needing writable space need tmpfs: [/tmp])
# ---------------------------------------------------------------------------

def test_services_with_volumes_have_tmpfs():
    """Read-only services that have volumes should have tmpfs: [/tmp]
    so they have a writable temp area."""
    for name, svc in _hardened_services(_compose_services()).items():
        if svc.get("volumes"):
            tmpfs = svc.get("tmpfs", [])
            assert "/tmp" in tmpfs or any("/tmp" in t for t in tmpfs), (
                f"Service '{name}' has volumes but no tmpfs: [/tmp]. "
                "When read_only: true, add tmpfs for writable /tmp."
            )


# ---------------------------------------------------------------------------
# Onboard-generated agent security hardening tests
# ---------------------------------------------------------------------------

from unittest.mock import patch


def test_onboard_generated_agent_has_cap_drop_all(tmp_path):
    """add_agent_to_docker_compose() must include cap_drop: [ALL] in the
    generated service definition."""
    from pillywiggins.onboard import add_agent_to_docker_compose

    compose_path = tmp_path / "docker-compose.yaml"
    compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))
    with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
        add_agent_to_docker_compose(
            agent_id="testagent",
            personality_filename="test.yaml",
            token_env="TESTAGENT_TELEGRAM_TOKEN",
        )
    data = yaml.safe_load(compose_path.read_text())
    svc = data["services"]["testagent"]
    assert svc.get("cap_drop") == ["ALL"], (
        "Onboard-generated agent must have cap_drop: [ALL]. "
        "Missing from add_agent_to_docker_compose() in onboard.py."
    )


def test_onboard_generated_agent_has_read_only(tmp_path):
    """add_agent_to_docker_compose() must include read_only: true in the
    generated service definition."""
    from pillywiggins.onboard import add_agent_to_docker_compose

    compose_path = tmp_path / "docker-compose.yaml"
    compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))
    with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
        add_agent_to_docker_compose(
            agent_id="testagent",
            personality_filename="test.yaml",
            token_env="TESTAGENT_TELEGRAM_TOKEN",
        )
    data = yaml.safe_load(compose_path.read_text())
    svc = data["services"]["testagent"]
    assert svc.get("read_only") is True, (
        "Onboard-generated agent must have read_only: true. "
        "Missing from add_agent_to_docker_compose() in onboard.py."
    )


def test_onboard_generated_agent_has_no_new_privileges(tmp_path):
    """add_agent_to_docker_compose() must include no-new-privileges:true
    via security_opt."""
    from pillywiggins.onboard import add_agent_to_docker_compose

    compose_path = tmp_path / "docker-compose.yaml"
    compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))
    with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
        add_agent_to_docker_compose(
            agent_id="testagent",
            personality_filename="test.yaml",
            token_env="TESTAGENT_TELEGRAM_TOKEN",
        )
    data = yaml.safe_load(compose_path.read_text())
    svc = data["services"]["testagent"]
    sec_opts = svc.get("security_opt", [])
    assert "no-new-privileges:true" in sec_opts, (
        "Onboard-generated agent must have security_opt: [no-new-privileges:true]. "
        "Missing from add_agent_to_docker_compose() in onboard.py."
    )


def test_onboard_generated_agent_has_tmpfs(tmp_path):
    """add_agent_to_docker_compose() must include tmpfs: [/tmp]
    since the container runs read-only."""
    from pillywiggins.onboard import add_agent_to_docker_compose

    compose_path = tmp_path / "docker-compose.yaml"
    compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))
    with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
        add_agent_to_docker_compose(
            agent_id="testagent",
            personality_filename="test.yaml",
            token_env="TESTAGENT_TELEGRAM_TOKEN",
        )
    data = yaml.safe_load(compose_path.read_text())
    svc = data["services"]["testagent"]
    tmpfs = svc.get("tmpfs", [])
    assert "/tmp" in tmpfs, (
        "Onboard-generated agent must have tmpfs: [/tmp] for writable temp space. "
        "Missing from add_agent_to_docker_compose() in onboard.py."
    )


def test_onboard_generated_agent_has_deploy_resources_limits(tmp_path):
    """add_agent_to_docker_compose() must include deploy.resources.limits.memory."""
    from pillywiggins.onboard import add_agent_to_docker_compose

    compose_path = tmp_path / "docker-compose.yaml"
    compose_path.write_text(yaml.dump({"services": {}, "volumes": {}}))
    with patch("pillywiggins.onboard.DOCKER_COMPOSE", compose_path):
        add_agent_to_docker_compose(
            agent_id="testagent",
            personality_filename="test.yaml",
            token_env="TESTAGENT_TELEGRAM_TOKEN",
        )
    data = yaml.safe_load(compose_path.read_text())
    svc = data["services"]["testagent"]
    deploy = svc.get("deploy", {})
    limits = deploy.get("resources", {}).get("limits", {})
    assert limits.get("memory") == "512M", (
        f"Onboard-generated agent must have deploy.resources.limits.memory: 512M. "
        f"Got: {limits}. Missing from add_agent_to_docker_compose() in onboard.py."
    )
