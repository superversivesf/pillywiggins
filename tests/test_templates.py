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


# ---------------------------------------------------------------------------
# Parametrized rejection tests
# ---------------------------------------------------------------------------

REJECTION_CASES = [
    pytest.param(
        "missing_meta",
        """
async def run():
    pass
""",
        "skill_meta",
        id="missing_meta",
    ),
    pytest.param(
        "missing_run",
        """
SKILL_META = {
    "name": "bad",
    "description": "no run",
    "version": "1.0",
}
""",
        "run",
        id="missing_run",
    ),
    pytest.param(
        "sync_run",
        """
SKILL_META = {"name": "sync_run", "description": "bad", "version": "1.0"}
def run():
    pass
""",
        "async",
        id="sync_run",
    ),
    pytest.param(
        "run_without_kwargs",
        """
SKILL_META = {"name": "no_kwargs", "description": "bad", "version": "1.0"}
async def run():
    pass
""",
        "kwargs",
        id="run_without_kwargs",
    ),
    pytest.param(
        "syntax_error",
        "this is not valid python",
        "syntax",
        id="syntax_error",
    ),
    pytest.param(
        "run_without_try_except",
        """
SKILL_META = {"name": "no_except", "description": "bad", "version": "1.0"}
async def run(**kwargs):
    return 42
""",
        "try/except",
        id="run_without_try_except",
    ),
]


@pytest.mark.parametrize("test_name,code,should_contain", REJECTION_CASES)
def test_validate_skill_code_rejections(test_name, code, should_contain):
    valid, error = validate_skill_code(code)
    assert valid is False
    assert should_contain in error.lower()


# ---------------------------------------------------------------------------
# Parametrized boilerplate structural checks
# ---------------------------------------------------------------------------

STRUCTURAL_CASES = [
    pytest.param(
        "perm_check",
        lambda c: "permissions" in c,
        id="permissions",
    ),
    pytest.param(
        "log_check",
        lambda c: "logging.getLogger" in c,
        id="logger",
    ),
    pytest.param(
        "except_check",
        lambda c: "try:" in c and "except" in c,
        id="try_except",
    ),
]


@pytest.mark.parametrize("name,check", STRUCTURAL_CASES)
def test_validate_skill_code_boilerplate_structure(name, check):
    code = generate_skill_boilerplate(name=name, description="Checking structure", author="warmfire")
    valid, error = validate_skill_code(code)
    assert valid is True
    assert check(code)


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
