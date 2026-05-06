import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic_ai import RunContext

from pillywiggins.agents.brain import _make_skill_tool
from pillywiggins.agents.deps import AgentDeps
from pillywiggins.skills.registry import Skill


def _make_ctx(agent_id="puck", channel="discord", private_memory=None, skill_registry=None):
    ctx = MagicMock(spec=RunContext)
    ctx.deps = AgentDeps(
        agent_id=agent_id,
        channel=channel,
        private_memory=private_memory,
        skill_registry=skill_registry,
    )
    return ctx


def _make_skill(name="test_skill", description="A test skill", run_func=None, meta=None, permissions=None):
    if run_func is None:
        run_func = AsyncMock(return_value="ok")
    if meta is None:
        meta = {"name": name, "description": description}
    if permissions is None:
        permissions = {"network": False, "subprocess": False, "file_write": False}
    return Skill(name=name, description=description, run_func=run_func, meta=meta, permissions=permissions)


class TestMakeSkillToolFunctionGeneration:
    @pytest.mark.asyncio
    async def test_generates_callable_tool_function(self):
        skill = _make_skill(name="greet", description="Greets the user")
        tool_fn = _make_skill_tool(skill)
        assert callable(tool_fn)

    @pytest.mark.asyncio
    async def test_tool_function_name_matches_skill_name(self):
        skill = _make_skill(name="greet_user", description="Greets the user")
        tool_fn = _make_skill_tool(skill)
        assert tool_fn.__name__ == "greet_user"

    @pytest.mark.asyncio
    async def test_tool_function_is_async(self):
        import inspect
        skill = _make_skill(name="async_check", description="Check async")
        tool_fn = _make_skill_tool(skill)
        assert inspect.iscoroutinefunction(tool_fn)

    @pytest.mark.asyncio
    async def test_tool_delegates_to_skill_execute(self):
        run_fn = AsyncMock(return_value="hello from skill")
        skill = _make_skill(name="greet", description="Greets", run_func=run_fn)
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        result = await tool_fn(ctx, name="world")
        skill.run_func.assert_awaited_once_with(name="world")
        assert result == "hello from skill"

    @pytest.mark.asyncio
    async def test_tool_returns_string_result_directly(self):
        skill = _make_skill(
            name="echo",
            description="Echoes input",
            run_func=AsyncMock(return_value="echoed"),
        )
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        result = await tool_fn(ctx, text="hello")
        assert result == "echoed"
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_tool_serializes_dict_result_as_json(self):
        skill = _make_skill(
            name="json_skill",
            description="Returns dict",
            run_func=AsyncMock(return_value={"key": "value", "count": 42}),
        )
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        result = await tool_fn(ctx)
        parsed = json.loads(result)
        assert parsed == {"key": "value", "count": 42}

    @pytest.mark.asyncio
    async def test_tool_serializes_list_result_as_json(self):
        skill = _make_skill(
            name="list_skill",
            description="Returns list",
            run_func=AsyncMock(return_value=[1, 2, 3]),
        )
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        result = await tool_fn(ctx)
        parsed = json.loads(result)
        assert parsed == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_tool_serializes_numeric_result_as_json(self):
        skill = _make_skill(
            name="count_skill",
            description="Returns number",
            run_func=AsyncMock(return_value=42),
        )
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        result = await tool_fn(ctx)
        assert json.loads(result) == 42

    @pytest.mark.asyncio
    async def test_tool_passes_kwargs_to_execute(self):
        run_fn = AsyncMock(return_value="done")
        skill = _make_skill(
            name="param_skill",
            description="Takes params",
            run_func=run_fn,
            meta={
                "name": "param_skill",
                "description": "Takes params",
                "parameters": {
                    "city": {"type": "string", "description": "City name"},
                    "units": {"type": "string", "description": "Temperature units", "default": "celsius"},
                },
            },
        )
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        await tool_fn(ctx, city="London", units="fahrenheit")
        run_fn.assert_awaited_once_with(city="London", units="fahrenheit")


class TestMakeSkillToolDocstringParsing:
    def test_docstring_includes_description(self):
        skill = _make_skill(name="weather", description="Gets the current weather")
        tool_fn = _make_skill_tool(skill)
        assert tool_fn.__doc__ is not None
        assert "Gets the current weather" in tool_fn.__doc__

    def test_docstring_includes_parameters_section(self):
        skill = _make_skill(
            name="weather",
            description="Gets the weather",
            meta={
                "name": "weather",
                "description": "Gets the weather",
                "parameters": {
                    "city": {"type": "string", "description": "City name"},
                },
            },
        )
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        assert "Args:" in doc
        assert "city" in doc
        assert "City name" in doc

    def test_docstring_includes_parameter_type(self):
        skill = _make_skill(
            name="weather",
            description="Gets the weather",
            meta={
                "name": "weather",
                "description": "Gets the weather",
                "parameters": {
                    "city": {"type": "string", "description": "City name"},
                    "count": {"type": "integer", "description": "Number of results"},
                },
            },
        )
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        assert "city (string)" in doc
        assert "count (integer)" in doc

    def test_docstring_includes_parameter_default(self):
        skill = _make_skill(
            name="weather",
            description="Gets the weather",
            meta={
                "name": "weather",
                "description": "Gets the weather",
                "parameters": {
                    "units": {"type": "string", "description": "Units", "default": "celsius"},
                },
            },
        )
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        assert "default: celsius" in doc

    def test_docstring_includes_parameter_without_description(self):
        skill = _make_skill(
            name="minimal",
            description="Minimal params",
            meta={
                "name": "minimal",
                "description": "Minimal params",
                "parameters": {
                    "x": {"type": "integer"},
                },
            },
        )
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        assert "x (integer)" in doc

    def test_docstring_no_args_section_when_no_params(self):
        skill = _make_skill(name="simple", description="No params needed")
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        assert "Args:" not in doc

    def test_docstring_empty_parameters_dict_means_no_args(self):
        skill = _make_skill(
            name="empty_params",
            description="Empty params",
            meta={
                "name": "empty_params",
                "description": "Empty params",
                "parameters": {},
            },
        )
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        assert "Args:" not in doc

    def test_docstring_default_type_is_string(self):
        skill = _make_skill(
            name="no_type",
            description="No type specified",
            meta={
                "name": "no_type",
                "description": "No type specified",
                "parameters": {
                    "value": {"description": "A value"},
                },
            },
        )
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        assert "value (string)" in doc

    def test_docstring_parameter_without_default_no_default_text(self):
        skill = _make_skill(
            name="no_default",
            description="No default",
            meta={
                "name": "no_default",
                "description": "No default",
                "parameters": {
                    "required_param": {"type": "string", "description": "A required param"},
                },
            },
        )
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        assert "required_param" in doc
        assert "default:" not in doc

    def test_docstring_none_default_not_rendered(self):
        skill = _make_skill(
            name="none_default",
            description="None default",
            meta={
                "name": "none_default",
                "description": "None default",
                "parameters": {
                    "opt": {"type": "string", "description": "Optional", "default": None},
                },
            },
        )
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        assert "default:" not in doc

    def test_multiple_parameters_all_appear_in_docstring(self):
        skill = _make_skill(
            name="multi",
            description="Multi param",
            meta={
                "name": "multi",
                "description": "Multi param",
                "parameters": {
                    "a": {"type": "string", "description": "First"},
                    "b": {"type": "integer", "description": "Second"},
                    "c": {"type": "boolean", "description": "Third"},
                },
            },
        )
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        assert "a (string)" in doc
        assert "b (integer)" in doc
        assert "c (boolean)" in doc


class TestMakeSkillToolNoParams:
    @pytest.mark.asyncio
    async def test_skill_with_no_params_called_without_kwargs(self):
        run_fn = AsyncMock(return_value="no args needed")
        skill = _make_skill(name="no_params", description="No params", run_func=run_fn)
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        result = await tool_fn(ctx)
        assert result == "no args needed"

    @pytest.mark.asyncio
    async def test_skill_with_no_meta_parameters_ignores_kwargs(self):
        run_fn = AsyncMock(return_value="ok")
        skill = _make_skill(
            name="bare",
            description="Bare skill",
            run_func=run_fn,
            meta={"name": "bare", "description": "Bare skill"},
        )
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        await tool_fn(ctx, unexpected_arg="wait")
        run_fn.assert_awaited_once_with(unexpected_arg="wait")

    def test_docstring_is_just_description_when_no_params_no_permissions(self):
        skill = _make_skill(name="bare", description="Just a simple skill")
        tool_fn = _make_skill_tool(skill)
        assert tool_fn.__doc__ == "Just a simple skill"


class TestMakeSkillToolPermissions:
    def test_permissions_appear_in_docstring(self):
        skill = _make_skill(
            name="net_skill",
            description="Network skill",
            permissions={"network": True, "subprocess": False, "file_write": False},
        )
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        assert "Permissions: network" in doc

    def test_multiple_permissions_in_docstring(self):
        skill = _make_skill(
            name="dangerous",
            description="Dangerous skill",
            permissions={"network": True, "subprocess": True, "file_write": False},
        )
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        assert "Permissions:" in doc
        assert "network" in doc
        assert "subprocess" in doc

    def test_no_permissions_not_in_docstring(self):
        skill = _make_skill(
            name="safe",
            description="Safe skill",
            permissions={"network": False, "subprocess": False, "file_write": False},
        )
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        assert "Permissions" not in doc

    def test_permissions_after_args_section(self):
        skill = _make_skill(
            name="combo",
            description="Combined",
            meta={
                "name": "combo",
                "description": "Combined",
                "parameters": {
                    "url": {"type": "string", "description": "URL to fetch"},
                },
            },
            permissions={"network": True, "subprocess": False, "file_write": False},
        )
        tool_fn = _make_skill_tool(skill)
        doc = tool_fn.__doc__
        args_pos = doc.find("Args:")
        perm_pos = doc.find("Permissions:")
        assert args_pos < perm_pos

    @pytest.mark.asyncio
    async def test_permissions_do_not_affect_execution(self):
        run_fn = AsyncMock(return_value="ran anyway")
        skill = _make_skill(
            name="perm_skill",
            description="Has perms",
            run_func=run_fn,
            permissions={"network": True, "subprocess": True, "file_write": True},
        )
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        result = await tool_fn(ctx, x="test")
        assert result == "ran anyway"


class TestMakeSkillToolMissingRunFunction:
    @pytest.mark.asyncio
    async def test_skill_with_none_run_func_returns_error_message(self):
        skill = Skill(
            name="broken",
            description="Broken skill",
            run_func=None,
            meta={"name": "broken", "description": "Broken skill"},
            permissions={"network": False, "subprocess": False, "file_write": False},
        )
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        result = await tool_fn(ctx)
        assert "Skill broken" in result

    @pytest.mark.asyncio
    async def test_skill_run_func_with_wrong_signature_gives_error_message(self):
        async def strict_run(required_arg):
            return str(required_arg)

        skill = _make_skill(
            name="strict",
            description="Strict signature",
            run_func=strict_run,
            meta={
                "name": "strict",
                "description": "Strict signature",
                "parameters": {
                    "required_arg": {"type": "string", "description": "Required"},
                },
            },
        )
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        result = await tool_fn(ctx, wrong_param="oops")
        assert "Skill strict" in result
        assert "Available parameters: required_arg" in result

    @pytest.mark.asyncio
    async def test_skill_run_func_type_error_returns_available_params(self):
        async def two_params(a, b):
            return f"{a}-{b}"

        skill = _make_skill(
            name="two_arg",
            description="Two args",
            run_func=two_params,
            meta={
                "name": "two_arg",
                "description": "Two args",
                "parameters": {
                    "a": {"type": "string", "description": "First"},
                    "b": {"type": "integer", "description": "Second"},
                },
            },
        )
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        result = await tool_fn(ctx, a="hello")
        assert "Skill two_arg" in result
        assert "Available parameters: a, b" in result


class TestMakeSkillToolKwargsExtraction:
    @pytest.mark.asyncio
    async def test_kwargs_forwarded_to_skill_execute(self):
        run_fn = AsyncMock(return_value="ok")
        skill = _make_skill(name="fwd", description="Forwarder", run_func=run_fn)
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        await tool_fn(ctx, foo="bar", baz=42)
        run_fn.assert_awaited_once_with(foo="bar", baz=42)

    @pytest.mark.asyncio
    async def test_no_kwargs_still_calls_execute(self):
        run_fn = AsyncMock(return_value="ok")
        skill = _make_skill(name="fwd_empty", description="Forwarder empty", run_func=run_fn)
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        await tool_fn(ctx)
        run_fn.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_ctx_not_passed_to_skill_execute(self):
        run_fn = AsyncMock(return_value="ok")
        skill = _make_skill(name="ctx_check", description="Ctx check", run_func=run_fn)
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        await tool_fn(ctx, key="value")
        call_kwargs = run_fn.call_args[1]
        assert "ctx" not in call_kwargs

    @pytest.mark.asyncio
    async def test_complex_kwargs_forwarded(self):
        run_fn = AsyncMock(return_value="ok")
        skill = _make_skill(name="complex", description="Complex", run_func=run_fn)
        tool_fn = _make_skill_tool(skill)
        ctx = _make_ctx()
        await tool_fn(ctx, items=[1, 2, 3], config={"a": True})
        run_fn.assert_awaited_once_with(items=[1, 2, 3], config={"a": True})


class TestMakeSkillToolToolAcceptsRunContext:
    @pytest.mark.asyncio
    async def test_tool_first_param_is_run_context(self):
        import inspect
        skill = _make_skill(name="ctx_test", description="Ctx test")
        tool_fn = _make_skill_tool(skill)
        sig = inspect.signature(tool_fn)
        params = list(sig.parameters.keys())
        assert params[0] == "ctx"

    @pytest.mark.asyncio
    async def test_tool_second_param_is_kwargs(self):
        import inspect
        skill = _make_skill(name="kwargs_test", description="Kwargs test")
        tool_fn = _make_skill_tool(skill)
        sig = inspect.signature(tool_fn)
        params = list(sig.parameters.keys())
        assert params[1] == "kwargs"