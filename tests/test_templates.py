import ast
from pathlib import Path

import pytest

from pillywiggins.skills.templates import generate_skill_boilerplate, validate_skill_code


def test_generate_skill_boilerplate_is_valid_python():
    code = generate_skill_boilerplate(name="hello_skill", description="A greeting skill", author="warmfire")
    tree = ast.parse(code)
    assert isinstance(tree, ast.Module)


def test_validate_skill_code_accepts_valid_boilerplate():
    code = generate_skill_boilerplate(name="hello_skill", description="A greeting skill", author="warmfire")
    valid, error = validate_skill_code(code)
    assert valid is True
    assert error == ""


def test_validate_skill_code_rejects_missing_meta():
    code = """
async def run():
    pass
"""
    valid, error = validate_skill_code(code)
    assert valid is False
    assert "skill_meta" in error.lower()


def test_validate_skill_code_rejects_missing_run():
    code = """
SKILL_META = {
    "name": "bad",
    "description": "no run",
    "version": "1.0",
}
"""
    valid, error = validate_skill_code(code)
    assert valid is False
    assert "run" in error.lower()


def test_validate_skill_code_rejects_sync_run():
    code = """
SKILL_META = {"name": "sync_run", "description": "bad", "version": "1.0"}
def run():
    pass
"""
    valid, error = validate_skill_code(code)
    assert valid is False
    assert "async" in error.lower()


def test_validate_skill_code_rejects_run_without_kwargs():
    code = """
SKILL_META = {"name": "no_kwargs", "description": "bad", "version": "1.0"}
async def run():
    pass
"""
    valid, error = validate_skill_code(code)
    assert valid is False
    assert "kwargs" in error.lower()


def test_validate_skill_code_rejects_syntax_error():
    code = "this is not valid python"
    valid, error = validate_skill_code(code)
    assert valid is False
    assert "syntax" in error.lower()


def test_validate_skill_code_checks_permissions_exist():
    code = generate_skill_boilerplate(name="perm_check", description="Checking permissions")
    valid, error = validate_skill_code(code)
    assert valid is True
    assert "SKILL_META" in code
    assert "permissions" in code


def test_validate_skill_code_checks_logger_exists():
    code = generate_skill_boilerplate(name="log_check", description="Checking logger")
    valid, error = validate_skill_code(code)
    assert valid is True
    assert "logging.getLogger" in code


def test_validate_skill_code_checks_try_except_in_run():
    code = generate_skill_boilerplate(name="except_check", description="Checking try/except")
    valid, error = validate_skill_code(code)
    assert valid is True
    assert "try:" in code and "except" in code


def test_validate_skill_code_rejects_run_without_try_except():
    code = """
SKILL_META = {"name": "no_except", "description": "bad", "version": "1.0"}
async def run(**kwargs):
    return 42
"""
    valid, error = validate_skill_code(code)
    assert valid is False
    assert "try/except" in error.lower()


def test_generate_skill_boilerplate_substitutes_fields():
    code = generate_skill_boilerplate(name="my_skill", description="does stuff", version="2.0", author="puck")
    assert '"my_skill"' in code
    assert '"does stuff"' in code
    assert '"2.0"' in code
    assert '"puck"' in code


def test_boilerplate_loads_in_registry(tmp_path):
    from pillywiggins.skills.registry import SkillRegistry

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    code = generate_skill_boilerplate(name="hello_registry", description="reg test", author="warmfire")
    (skills_dir / "hello_registry.py").write_text(code)
    reg = SkillRegistry(skills_dir=skills_dir)
    skills = reg.load_all()

    assert len(skills) == 1
    assert skills[0].name == "hello_registry"
    assert skills[0].description == "reg test"


@pytest.mark.asyncio
async def test_boilerplate_executes_in_registry(tmp_path):
    from pillywiggins.skills.registry import SkillRegistry

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    code = generate_skill_boilerplate(name="exec_registry", description="exec test", author="warmfire")
    # Patch the TODO so it returns something real
    code = code.replace(
        "# TODO: Implement skill logic",
        'return {"status": "ok"}'
    )
    (skills_dir / "exec_registry.py").write_text(code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()

    skill = reg.get_skill("exec_registry")
    result = await skill.execute()
    assert result == {"status": "ok"}
