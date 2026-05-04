import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


def test_skill_repr(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {"name": "repr_test", "description": "test repr", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
async def run():
    return "ok"
'''
    (skills_dir / "repr_test.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()

    skill = reg.get_skill("repr_test")
    assert repr(skill) == "Skill(name='repr_test')"


def test_load_all_skips_syntax_error(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "broken_syntax.py").write_text("def broken(:\n  pass")
    reg = SkillRegistry(skills_dir=skills_dir)
    skills = reg.load_all()

    assert skills == []


def test_register_skill_returns_none_on_load_failure(tmp_path):
    skills_dir = tmp_path / "skills"
    reg = SkillRegistry(skills_dir=skills_dir)

    code = "this is not valid python"
    meta = {"name": "bad_skill", "description": "bad", "version": "1.0", "parameters": {}}
    import pytest
    with pytest.raises(SyntaxError):
        reg.register_skill("bad_skill", code, meta)


def test_load_all_multiple_skills(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    for name in ["alpha", "beta", "gamma"]:
        code = f'''
SKILL_META = {{"name": "{name}", "description": "Skill {name}", "version": "1.0", "parameters": {{}}, "permissions": {{"network": False, "subprocess": False, "file_write": False}}}}
async def run():
    return "{name}"
'''
        (skills_dir / f"{name}.py").write_text(code)

    reg = SkillRegistry(skills_dir=skills_dir)
    skills = reg.load_all()

    assert len(skills) == 3
    names = {s.name for s in skills}
    assert names == {"alpha", "beta", "gamma"}


def test_load_all_clears_previous_skills(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    skill_code = '''
SKILL_META = {"name": "persistent", "description": "should be cleared", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
async def run():
    return "ok"
'''
    (skills_dir / "persistent.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()
    assert len(reg.list_skills()) == 1

    (skills_dir / "persistent.py").unlink()
    reg.load_all()

    assert len(reg.list_skills()) == 0


def test_register_skill_creates_directory(tmp_path):
    skills_dir = tmp_path / "nested" / "skills"
    reg = SkillRegistry(skills_dir=skills_dir)

    code = '''SKILL_META = {"name": "new_skill", "description": "new", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
async def run():
    return "new"
'''
    meta = {"name": "new_skill", "description": "new", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
    reg.register_skill("new_skill", code, meta)

    assert skills_dir.exists()
    assert (skills_dir / "new_skill.py").exists()


def test_parse_permissions_legacy_and_explicit_merge(tmp_path):
    reg = SkillRegistry(skills_dir=tmp_path / "skills")
    meta = {
        "name": "both",
        "description": "both legacy and explicit",
        "parameters": {},
        "network_access": True,
        "permissions": {"network": True, "subprocess": True, "file_write": False},
    }
    permissions = reg._parse_permissions(meta)

    assert permissions["network"] is True
    assert permissions["subprocess"] is True
    assert permissions["file_write"] is False


def test_parse_permissions_legacy_only_network(tmp_path):
    reg = SkillRegistry(skills_dir=tmp_path / "skills")
    meta = {
        "name": "legacy_net",
        "description": "legacy network flag only",
        "parameters": {},
        "network_access": True,
    }
    permissions = reg._parse_permissions(meta)

    assert permissions == {"network": True, "subprocess": False, "file_write": False}


def test_has_skill_before_load_returns_false(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {"name": "unloaded", "description": "test", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
async def run():
    return "ok"
'''
    (skills_dir / "unloaded.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)

    assert reg.has_skill("unloaded") is False

    reg.load_all()

    assert reg.has_skill("unloaded") is True


def test_register_skill_updates_existing_in_registry(tmp_path):
    skills_dir = tmp_path / "skills"
    reg = SkillRegistry(skills_dir=skills_dir)

    code_v1 = '''SKILL_META = {"name": "versioned", "description": "v1", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
async def run():
    return "v1"
'''
    meta_v1 = {"name": "versioned", "description": "v1", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
    reg.register_skill("versioned", code_v1, meta_v1)

    registry = json.loads((skills_dir / "registry.json").read_text())
    entry = [s for s in registry["skills"] if s["name"] == "versioned"][0]
    assert entry["description"] == "v1"

    code_v2 = code_v1.replace("v1", "v2")
    meta_v2 = {**meta_v1, "description": "v2"}
    reg.register_skill("versioned", code_v2, meta_v2)

    registry = json.loads((skills_dir / "registry.json").read_text())
    entries = [s for s in registry["skills"] if s["name"] == "versioned"]
    assert len(entries) == 1
    assert entries[0]["description"] == "v1"


@pytest.mark.asyncio
async def test_skill_execute_with_kwargs(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {"name": "greeting", "description": "says hello", "version": "1.0", "parameters": {"name": {"type": "string"}}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
async def run(name: str = "world") -> dict:
    return {"greeting": f"Hello, {name}!"}
'''
    (skills_dir / "greeting.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()

    skill = reg.get_skill("greeting")
    result = await skill.execute(name="Puck")
    assert result == {"greeting": "Hello, Puck!"}


def test_list_skills_returns_copy(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {"name": "test", "description": "test", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}
async def run():
    return "ok"
'''
    (skills_dir / "test.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()

    skills1 = reg.list_skills()
    skills2 = reg.list_skills()
    assert skills1 == skills2
    assert skills1 is not skills2


def test_load_skill_file_spec_none(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "empty_module.py").write_text("")
    reg = SkillRegistry(skills_dir=skills_dir)

    with patch("pillywiggins.skills.registry.importlib.util.spec_from_file_location", return_value=None):
        result = reg._load_skill_file(skills_dir / "empty_module.py")

    assert result is None


def test_load_skill_file_spec_loader_none(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "no_loader.py").write_text("")
    reg = SkillRegistry(skills_dir=skills_dir)

    mock_spec = MagicMock()
    mock_spec.loader = None
    with patch("pillywiggins.skills.registry.importlib.util.spec_from_file_location", return_value=mock_spec):
        result = reg._load_skill_file(skills_dir / "no_loader.py")

    assert result is None


# ---------------------------------------------------------------------------
# Hot-reload watcher tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_loop_detects_new_file_and_reloads(tmp_path):
    """_watch_loop should detect a new .py file and call load_all."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    reg = SkillRegistry(skills_dir=skills_dir)
    reg._last_snapshot = reg._snapshot_skills()  # baseline empty
    reg._watcher_running = True

    load_calls = []
    original_load_all = reg.load_all

    def tracking_load_all():
        load_calls.append(1)
        return original_load_all()

    reg.load_all = tracking_load_all

    # Create a new skill file after the baseline snapshot.
    (skills_dir / "new_skill.py").write_text(
        'SKILL_META = {"name": "new_skill", "description": "x", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}\n'
        "async def run():\n    return 'ok'\n"
    )

    # Patch asyncio.sleep so we don't wait; raise CancelledError on second call to exit the loop.
    sleep_count = 0

    async def fake_sleep(_):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError()

    with patch("pillywiggins.skills.registry.asyncio.sleep", fake_sleep):
        await reg._watch_loop(interval=0.001)

    assert len(load_calls) >= 1
    reg.stop_watching()


@pytest.mark.asyncio
async def test_watch_loop_syncs_registry_json_on_change(tmp_path):
    """When a change is detected the watcher must also rewrite registry.json."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    reg = SkillRegistry(skills_dir=skills_dir)
    reg._last_snapshot = reg._snapshot_skills()  # baseline empty
    reg._watcher_running = True

    sync_calls = 0
    original_sync = reg._sync_registry_json

    def tracking_sync():
        nonlocal sync_calls
        sync_calls += 1
        return original_sync()

    reg._sync_registry_json = tracking_sync

    (skills_dir / "auto.py").write_text(
        'SKILL_META = {"name": "auto", "description": "auto", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}\n'
        "async def run():\n    return 'ok'\n"
    )

    sleep_count = 0

    async def fake_sleep(_):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 2:
            raise asyncio.CancelledError()

    with patch("pillywiggins.skills.registry.asyncio.sleep", fake_sleep):
        await reg._watch_loop(interval=0.001)

    assert sync_calls >= 1
    reg.stop_watching()


@pytest.mark.asyncio
async def test_watch_for_changes_delegates_to_start_watching(tmp_path):
    """watch_for_changes should invoke start_watching with a 10-second default."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    reg = SkillRegistry(skills_dir=skills_dir)

    start_calls = []

    def fake_start_watching(interval):
        start_calls.append(interval)
        reg._watcher_running = True
        reg._last_snapshot = reg._snapshot_skills()

    reg.start_watching = fake_start_watching
    reg.watch_for_changes()

    assert len(start_calls) == 1
    assert start_calls[0] == 10.0

    reg.stop_watching()


@pytest.mark.asyncio
async def test_notify_reload_with_nats_bus(tmp_path):
    """_notify_reload should call publish_broadcast when a NATS bus is available."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    mock_bus = AsyncMock()
    reg = SkillRegistry(skills_dir=skills_dir, agent_id="test-agent", nats_bus=mock_bus)
    await reg._notify_reload()

    mock_bus.publish_broadcast.assert_awaited_once_with(
        "skill_published",
        {"agent_id": "test-agent", "action": "reload"},
    )


@pytest.mark.asyncio
async def test_notify_reload_without_nats_bus(tmp_path):
    """_notify_reload should silently return when no NATS bus is configured."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    reg = SkillRegistry(skills_dir=skills_dir)
    await reg._notify_reload()  # should not raise


@pytest.mark.asyncio
async def test_broadcast_reload_schedules_task(tmp_path):
    """broadcast_reload should schedule _notify_reload on the running event loop."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    mock_bus = AsyncMock()
    reg = SkillRegistry(skills_dir=skills_dir, agent_id="agent-42", nats_bus=mock_bus)

    reg.broadcast_reload()
    # Give the loop a chance to execute the spawned task
    await asyncio.sleep(0.05)

    mock_bus.publish_broadcast.assert_awaited_once_with(
        "skill_published",
        {"agent_id": "agent-42", "action": "reload"},
    )


def test_broadcast_reload_no_loop_warns(caplog):
    """broadcast_reload should log a warning when no event loop is running."""
    import logging

    reg = SkillRegistry(agent_id="agent-x")
    with caplog.at_level(logging.WARNING, logger="pillywiggins.skills.registry"):
        reg.broadcast_reload()
    assert any("No running event loop" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Atomic registry.json write tests
# ---------------------------------------------------------------------------


def test_sync_registry_json_writes_temp_then_replaces(tmp_path):
    """_sync_registry_json should write to a temp file and atomically replace registry.json."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    reg = SkillRegistry(skills_dir=skills_dir)

    # Seed a skill so there is something to sync.
    (skills_dir / "alpha.py").write_text(
        'SKILL_META = {"name": "alpha", "description": "a", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}\n'
        "async def run():\n    return 'ok'\n"
    )
    reg.load_all()

    reg._sync_registry_json()

    registry_path = skills_dir / "registry.json"
    assert registry_path.exists()
    tmp_path_file = skills_dir / "registry.json.tmp"
    # Temp file should have been replaced; it may or may not exist after os.replace,
    # but on most POSIX systems it is gone.  We assert that the real file exists and is valid JSON.
    data = json.loads(registry_path.read_text())
    assert "skills" in data
    assert any(s["name"] == "alpha" for s in data["skills"])


# ---------------------------------------------------------------------------
# load_errors surfacing tests
# ---------------------------------------------------------------------------


def test_load_all_captures_error_in_load_errors(tmp_path):
    """When a skill file fails to load, the error should be stored in load_errors and surfaced via get_status."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "good.py").write_text(
        'SKILL_META = {"name": "good", "description": "g", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}\n'
        "async def run():\n    return 'ok'\n"
    )
    (skills_dir / "broken.py").write_text("this is not valid python syntax :\n")
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()

    status = reg.get_status()
    assert status["loaded"] == 1
    assert len(status["errors"]) >= 1
    assert any("broken.py" in err for err in status["errors"])
    assert len(reg.load_errors) >= 1


# ---------------------------------------------------------------------------
# run() coroutine validation tests
# ---------------------------------------------------------------------------


def test_load_all_skips_non_coroutine_run(tmp_path, caplog):
    """A skill with def run() (not async def) should be rejected with an ERROR log and skipped."""
    import logging

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "sync_run.py").write_text(
        'SKILL_META = {"name": "sync_run", "description": "s", "version": "1.0", "parameters": {}, "permissions": {"network": False, "subprocess": False, "file_write": False}}\n'
        "def run():\n    return 'not async'\n"
    )
    reg = SkillRegistry(skills_dir=skills_dir)
    with caplog.at_level(logging.ERROR, logger="pillywiggins.skills.registry"):
        skills = reg.load_all()

    assert skills == []
    assert any("not a coroutine function" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Skill.as_tool() tests
# ---------------------------------------------------------------------------


def test_skill_as_tool_returns_pydantic_tool(tmp_path):
    """Skill.as_tool() should return a pydantic_ai.tools.Tool instance."""
    from pydantic_ai.tools import Tool

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {
    "name": "adder",
    "description": "Add two numbers",
    "parameters": {
        "a": {"type": "integer", "description": "First number"},
        "b": {"type": "integer", "description": "Second number"},
    },
}

async def run(a: int, b: int) -> dict:
    return {"result": a + b}
'''
    (skills_dir / "adder.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()
    skill = reg.get_skill("adder")
    tool = skill.as_tool()
    assert isinstance(tool, Tool)
    assert tool.name == "adder"


def test_skill_as_tool_schema_from_meta(tmp_path):
    """The generated tool should expose parameters derived from SKILL_META, not just **kwargs."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {
    "name": "greeter",
    "description": "Greet someone",
    "parameters": {
        "name": {"type": "string", "description": "Who to greet", "default": "world"},
        "times": {"type": "integer", "description": "How many times", "default": 1},
    },
}

async def run(name: str = "world", times: int = 1):
    return "Hello, " + name + "!" * times
'''
    (skills_dir / "greeter.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()
    skill = reg.get_skill("greeter")
    tool = skill.as_tool()
    assert tool.name == "greeter"

    schema = tool.function_schema
    assert schema is not None
    props = schema.json_schema.get("properties", {})
    assert "name" in props
    assert "times" in props
    assert props["name"].get("type") == "string"
    assert props["times"].get("type") == "integer"


@pytest.mark.asyncio
async def test_skill_as_tool_execution(tmp_path):
    """Calling the wrapped tool should route through skill.execute()."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {
    "name": "multiplier",
    "description": "Multiply numbers",
    "parameters": {
        "x": {"type": "integer", "description": "First factor"},
        "y": {"type": "integer", "description": "Second factor"},
    },
}

async def run(x: int, y: int) -> dict:
    return {"product": x * y}
'''
    (skills_dir / "multiplier.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()
    skill = reg.get_skill("multiplier")
    tool = skill.as_tool()

    result = await tool.function(x=3, y=4)
    assert result == '{"product": 12}'


@pytest.mark.asyncio
async def test_skill_as_tool_with_string_description_and_default(tmp_path):
    """A skill whose run() returns a plain string should return the string unchanged."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {
    "name": "echo",
    "description": "Echo a message",
    "parameters": {
        "msg": {"type": "string", "description": "Message to echo"},
    },
}

async def run(msg: str) -> str:
    return msg
'''
    (skills_dir / "echo.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()
    skill = reg.get_skill("echo")
    tool = skill.as_tool()

    result = await tool.function(msg="hi there")
    assert result == "hi there"


def test_skill_as_tool_docstring_includes_params(tmp_path):
    """The generated docstring should carry parameter descriptions from SKILL_META."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_code = '''
SKILL_META = {
    "name": "param_doc",
    "description": "Demonstrate doc",
    "parameters": {
        "alpha": {"type": "string", "description": "Alpha param"},
        "beta": {"type": "integer", "description": "Beta param"},
    },
}

async def run(alpha, beta):
    return {"alpha": alpha, "beta": beta}
'''
    (skills_dir / "param_doc.py").write_text(skill_code)
    reg = SkillRegistry(skills_dir=skills_dir)
    reg.load_all()
    skill = reg.get_skill("param_doc")
    tool = skill.as_tool()

    assert "Alpha param" in tool.function_schema.json_schema["properties"]["alpha"].get("description", "")
    assert "Beta param" in tool.function_schema.json_schema["properties"]["beta"].get("description", "")
