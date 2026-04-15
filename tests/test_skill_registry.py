import json
import tempfile
from pathlib import Path

import pytest

from pillywiggins.skills.registry import SkillRegistry


@pytest.fixture
def skills_dir(tmp_path):
    return tmp_path / "skills"


@pytest.fixture
def registry(skills_dir):
    reg = SkillRegistry(skills_dir=skills_dir)
    return reg


def test_load_all_empty_dir(registry, skills_dir):
    skills_dir.mkdir(parents=True)
    skills = registry.load_all()
    assert skills == []


def test_load_all_no_dir(registry):
    skills = registry.load_all()
    assert skills == []


def test_load_all_loads_skill(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {
    "name": "hello",
    "description": "Says hello",
    "version": "1.0",
    "parameters": {},
    "permissions": {"network": False, "subprocess": False, "file_write": False},
}

async def run():
    return "Hello!"
'''
    (skills_dir / "hello.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    skills = reg.load_all()

    assert len(skills) == 1
    assert skills[0].name == "hello"
    assert skills[0].description == "Says hello"
    assert skills[0].permissions == {"network": False, "subprocess": False, "file_write": False}


def test_load_all_skips_init_file(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "__init__.py").write_text("")
    reg = SkillRegistry(skills_dir=skills_dir)
    skills = reg.load_all()

    assert skills == []


def test_load_all_skips_underscore_prefix(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "_helper.py").write_text("SKILL_META = {}")
    reg = SkillRegistry(skills_dir=skills_dir)
    skills = reg.load_all()

    assert skills == []


def test_load_all_skips_missing_meta(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "broken.py").write_text("async def run(): pass\n")
    reg = SkillRegistry(skills_dir=skills_dir)
    skills = reg.load_all()

    assert skills == []


def test_load_all_skips_missing_run(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "no_run.py").write_text('SKILL_META = {"name": "no_run", "description": "x"}\n')
    reg = SkillRegistry(skills_dir=skills_dir)
    skills = reg.load_all()

    assert skills == []


def test_list_skills(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {"name": "test_skill", "description": "A test", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
async def run():
    return "test"
'''
    (skills_dir / "test_skill.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()

    skills = reg.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "test_skill"


def test_get_skill(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {"name": "my_skill", "description": "desc", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
async def run():
    return "result"
'''
    (skills_dir / "my_skill.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()

    skill = reg.get_skill("my_skill")
    assert skill is not None
    assert skill.name == "my_skill"


def test_get_skill_not_found(registry):
    assert registry.get_skill("nonexistent") is None


def test_has_skill(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {"name": "checker", "description": "checks things", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
async def run():
    return "ok"
'''
    (skills_dir / "checker.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()

    assert reg.has_skill("checker") is True
    assert reg.has_skill("missing") is False


@pytest.mark.asyncio
async def test_skill_execute(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {"name": "adder", "description": "adds numbers", "version": "1.0", "parameters": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
async def run(a: int, b: int) -> dict:
    return {"result": a + b}
'''
    (skills_dir / "adder.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()

    skill = reg.get_skill("adder")
    result = await skill.execute(a=2, b=3)
    assert result == {"result": 5}


def test_register_skill_creates_file(tmp_path):
    skills_dir = tmp_path / "skills"
    reg = SkillRegistry(skills_dir=skills_dir)

    code = '''SKILL_META = {"name": "new_skill", "description": "new", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
async def run():
    return "new"
'''
    meta = {"name": "new_skill", "description": "new", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
    skill = reg.register_skill("new_skill", code, meta)

    assert skill is not None
    assert skill.name == "new_skill"
    assert (skills_dir / "new_skill.py").exists()

    registry = json.loads((skills_dir / "registry.json").read_text())
    assert any(s["name"] == "new_skill" for s in registry["skills"])


def test_register_skill_updates_registry_not_duplicates(tmp_path):
    skills_dir = tmp_path / "skills"
    reg = SkillRegistry(skills_dir=skills_dir)

    code = '''SKILL_META = {"name": "dup_skill", "description": "first", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
async def run():
    return "first"
'''
    meta = {"name": "dup_skill", "description": "first", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
    reg.register_skill("dup_skill", code, meta)

    code2 = code.replace("first", "second")
    meta2 = {**meta, "description": "second"}
    reg.register_skill("dup_skill", code2, meta2)

    registry = json.loads((skills_dir / "registry.json").read_text())
    names = [s["name"] for s in registry["skills"]]
    assert names.count("dup_skill") == 1


def test_parse_permissions_explicit(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {
    "name": "web_checker",
    "description": "checks urls",
    "version": "1.0",
    "parameters": {},
    "permissions": {"network": True, "subprocess": False, "file_write": False},
}
async def run():
    return "ok"
'''
    (skills_dir / "web_checker.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    skills = reg.load_all()

    assert len(skills) == 1
    assert skills[0].permissions == {"network": True, "subprocess": False, "file_write": False}


def test_parse_permissions_legacy_network_access(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {
    "name": "legacy_skill",
    "description": "old style",
    "version": "1.0",
    "parameters": {},
    "network_access": True,
}
async def run():
    return "ok"
'''
    (skills_dir / "legacy_skill.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    skills = reg.load_all()

    assert len(skills) == 1
    assert skills[0].permissions == {"network": True, "subprocess": False, "file_write": False}


def test_parse_permissions_defaults_all_false(tmp_path):
    reg = SkillRegistry(skills_dir=tmp_path / "skills")
    meta = {"name": "basic", "description": "basic skill", "parameters": {}}
    permissions = reg._parse_permissions(meta)

    assert permissions == {"network": False, "subprocess": False, "file_write": False}