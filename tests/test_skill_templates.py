import ast

import pytest

from pillywiggins.skills.templates import (
    generate_skill_boilerplate,
    generate_skill_template,
    validate_permissions,
    validate_run_signature,
    validate_skill_code,
    validate_skill_meta,
    VALID_PERMISSIONS,
)


# ---------------------------------------------------------------------------
# generate_skill_boilerplate (legacy)
# ---------------------------------------------------------------------------


def test_generate_skill_boilerplate_is_valid_python():
    code = generate_skill_boilerplate(name="hello_skill", description="A greeting skill", author="warmfire")
    tree = ast.parse(code)
    assert isinstance(tree, ast.Module)


def test_generate_skill_boilerplate_substitutes_fields():
    code = generate_skill_boilerplate(name="my_skill", description="does stuff", version="2.0", author="puck")
    assert '"my_skill"' in code
    assert '"does stuff"' in code
    assert '"2.0"' in code
    assert '"puck"' in code


# ---------------------------------------------------------------------------
# generate_skill_template (new, spec-matching)
# ---------------------------------------------------------------------------


def test_generate_skill_template_produces_valid_python():
    code = generate_skill_template(
        name="roll_dice",
        description="Roll dice and return the result.",
        parameters={
            "num_dice": {"type": "integer", "description": "Number of dice", "default": 1},
            "sides": {"type": "integer", "description": "Number of sides", "default": 6},
        },
        returns="dict with rolls list and total",
        permissions={"network": False, "subprocess": False, "file_write": False},
        version="1.0",
        author="system",
    )
    tree = ast.parse(code)
    assert isinstance(tree, ast.Module)


def test_generate_skill_template_has_skill_meta():
    code = generate_skill_template(name="foo", description="bar")
    assert 'SKILL_META = {' in code
    assert '"name": "foo"' in code
    assert '"description": "bar"' in code


def test_generate_skill_template_has_parameters():
    code = generate_skill_template(
        name="count_words",
        description="Count words in text.",
        parameters={"text": {"type": "string", "description": "Input text"}},
    )
    assert '"parameters": {' in code
    assert '"text"' in code


def test_generate_skill_template_has_permissions():
    code = generate_skill_template(
        name="net_skill",
        description="Uses network.",
        permissions={"network": True, "subprocess": False, "file_write": False},
    )
    assert '"network": True' in code
    assert '"subprocess": False' in code
    assert '"file_write": False' in code


def test_generate_skill_template_has_run_function():
    code = generate_skill_template(name="foo", description="bar")
    assert "async def run(" in code


def test_generate_skill_template_run_signature_with_params():
    code = generate_skill_template(
        name="adder",
        description="Add two numbers.",
        parameters={
            "a": {"type": "integer", "description": "First number"},
            "b": {"type": "integer", "description": "Second number", "default": 0},
        },
    )
    assert "async def run(a: int, b: int = 0)" in code


def test_generate_skill_template_run_signature_no_params():
    code = generate_skill_template(name="foo", description="bar", parameters={})
    assert "async def run(**kwargs)" in code


def test_generate_skill_template_loads_in_registry(tmp_path):
    from pillywiggins.skills.registry import SkillRegistry

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    code = generate_skill_template(
        name="hello_registry",
        description="reg test",
        permissions={"network": False, "subprocess": False, "file_write": False},
        version="1.0",
        author="system",
    )
    (skills_dir / "hello_registry.py").write_text(code)
    reg = SkillRegistry(skills_dir=skills_dir)
    skills = reg.load_all()

    assert len(skills) == 1
    assert skills[0].name == "hello_registry"
    assert skills[0].description == "reg test"


@pytest.mark.asyncio
async def test_generate_skill_template_executes_in_registry(tmp_path):
    from pillywiggins.skills.registry import SkillRegistry

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    code = generate_skill_template(
        name="exec_registry",
        description="exec test",
        version="1.0",
        author="system",
        permissions={"network": False, "subprocess": False, "file_write": False},
    )
    # Patch the TODO so it returns something real
    code = code.replace(
        "        # TODO: Implement skill logic",
        '        return {"status": "ok"}',
    )
    (skills_dir / "exec_registry.py").write_text(code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()

    skill = reg.get_skill("exec_registry")
    result = await skill.execute()
    assert result == {"status": "ok"}


def test_generate_skill_template_escaped_quotes():
    code = generate_skill_template(name='say_"hello"', description='She said "hi"')
    # Should compile without syntax errors
    ast.parse(code)


# ---------------------------------------------------------------------------
# validate_skill_meta
# ---------------------------------------------------------------------------


def test_validate_skill_meta_accept_valid():
    ok, err = validate_skill_meta(
        {
            "name": "roll_dice",
            "description": "Roll dice",
            "version": "1.0",
            "permissions": {"network": False, "subprocess": False, "file_write": False},
        }
    )
    assert ok is True
    assert err == ""


def test_validate_skill_meta_reject_non_dict():
    ok, err = validate_skill_meta("not a dict")
    assert ok is False
    assert "must be a dict" in err.lower()


def test_validate_skill_meta_reject_missing_keys():
    ok, err = validate_skill_meta({"name": "foo"})
    assert ok is False
    assert "missing" in err.lower()
    assert "description" in err
    assert "version" in err


def test_validate_skill_meta_reject_invalid_permission_keys():
    ok, err = validate_skill_meta(
        {
            "name": "foo",
            "description": "bar",
            "version": "1.0",
            "permissions": {"network": False, "subprocess": False, "file_write": False, "exec": True},
        }
    )
    assert ok is False
    assert "exec" in err


def test_validate_skill_meta_reject_non_dict_permissions():
    ok, err = validate_skill_meta(
        {
            "name": "foo",
            "description": "bar",
            "version": "1.0",
            "permissions": "nope",
        }
    )
    assert ok is False
    assert "permissions" in err.lower()


# ---------------------------------------------------------------------------
# validate_run_signature
# ---------------------------------------------------------------------------


def test_validate_run_signature_accept_valid():
    code = "async def run(**kwargs): pass"
    ok, err = validate_run_signature(code)
    assert ok is True
    assert err == ""


def test_validate_run_signature_reject_sync():
    code = "def run(**kwargs): pass"
    ok, err = validate_run_signature(code)
    assert ok is False
    assert "async" in err.lower()


def test_validate_run_signature_reject_missing():
    code = "async def other(): pass"
    ok, err = validate_run_signature(code)
    assert ok is False
    assert "async def run" in err.lower()


def test_validate_run_signature_reject_syntax_error():
    code = "def broken(\n"
    ok, err = validate_run_signature(code)
    assert ok is False
    assert "syntax" in err.lower()


# ---------------------------------------------------------------------------
# validate_permissions
# ---------------------------------------------------------------------------


def test_validate_permissions_accept_valid():
    ok, err = validate_permissions({"network": False, "subprocess": False, "file_write": False})
    assert ok is True
    assert err == ""


def test_validate_permissions_reject_invalid_key():
    ok, err = validate_permissions({"network": False, "exec": True})
    assert ok is False
    assert "exec" in err


def test_validate_permissions_reject_non_bool():
    ok, err = validate_permissions({"network": "yes"})
    assert ok is False
    assert "boolean" in err.lower()
    assert "network" in err


def test_validate_permissions_reject_non_dict():
    ok, err = validate_permissions(None)
    assert ok is False
    assert "dict" in err.lower()


# ---------------------------------------------------------------------------
# validate_skill_code (legacy compound validator)
# ---------------------------------------------------------------------------


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


def test_validate_skill_code_rejects_run_without_try_except():
    code = """
SKILL_META = {"name": "no_except", "description": "bad", "version": "1.0"}
async def run(**kwargs):
    return 42
"""
    valid, error = validate_skill_code(code)
    assert valid is False
    assert "try/except" in error.lower()


def test_validate_skill_code_rejects_syntax_error():
    code = "this is not valid python"
    valid, error = validate_skill_code(code)
    assert valid is False
    assert "syntax" in error.lower()


def test_validate_skill_code_checks_logger_exists():
    code = generate_skill_boilerplate(name="log_check", description="Checking logger")
    valid, error = validate_skill_code(code)
    assert valid is True
    assert "logging.getLogger" in code


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------


def test_valid_permissions_constant():
    assert VALID_PERMISSIONS == {"network", "subprocess", "file_write"}
