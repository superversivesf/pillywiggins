"""Standard skill boilerplate generation and validation."""

import ast
import logging
from typing import Any

logger = logging.getLogger(__name__)

VALID_PERMISSIONS = {"network", "subprocess", "file_write"}
REQUIRED_META_KEYS = {"name", "description", "version"}

_TYPE_MAP = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}

# ---------------------------------------------------------------------------
# Boilerplate constants
# ---------------------------------------------------------------------------

_SKILL_BOILERPLATE = '''import logging
from typing import Any

logger = logging.getLogger(__name__)

SKILL_META = {{
    "name": "{name}",
    "description": "{description}",
    "version": "{version}",
    "author": "{author}",
    "permissions": {{
        "network": False,
        "subprocess": False,
        "file_write": False,
    }},
}}

async def run(**kwargs) -> dict[str, Any]:
    """Execute the {name} skill.

    Args:
        **kwargs: Key-word arguments passed by the agent framework.

    Returns:
        A dict with the skill result.

    Raises:
        Exception: Propagates unexpected errors after logging.
    """
    try:
        # TODO: Implement skill logic
        pass
    except Exception:
        logger.exception("Skill {name} failed")
        raise
'''


def _quote(s: str) -> str:
    return s.replace('"', '\\"')


def _to_py_type(param_type: str) -> str:
    """Map JSON-schema-ish type strings to Python type annotations."""
    return _TYPE_MAP.get(param_type, param_type)


class _ValidationResult:
    def __init__(self):
        self.errors: list[str] = []

    def add(self, msg: str) -> None:
        self.errors.append(msg)

    def ok(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        return "; ".join(self.errors)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate_skill_boilerplate(
    name: str,
    description: str,
    version: str = "0.1.0",
    author: str = "agent",
) -> str:
    """Generate a standard skill scaffold.

    Returns a string of valid Python code that can be loaded by
    :class:`pillywiggins.skills.registry.SkillRegistry`.
    """
    return _SKILL_BOILERPLATE.format(
        name=_quote(name),
        description=_quote(description),
        version=_quote(version),
        author=_quote(author),
    )


def generate_skill_template(
    name: str,
    description: str,
    *,
    parameters: dict[str, dict[str, Any]] | None = None,
    returns: str = "dict",
    permissions: dict[str, bool] | None = None,
    version: str = "1.0",
    author: str = "system",
) -> str:
    """Generate a skill template matching the real skill format (e.g. roll_dice.py).

    Args:
        name: Skill name (snake_case).
        description: Short description.
        parameters: Mapping of param name to dict with keys like type, description, default.
            Example: ``{"num_dice": {"type": "integer", "description": "...", "default": 1}}``
        returns: Return type description string.
        permissions: Dict of permission booleans.
        version: Semantic version string.
        author: Author identifier.

    Returns:
        Valid Python skill file content.
    """
    perms = permissions or {
        "network": False,
        "subprocess": False,
        "file_write": False,
    }
    params = parameters or {}

    # Build parameters JSON block
    param_lines = []
    for pname, pmeta in params.items():
        pmeta_str = ", ".join(f"{k!r}: {v!r}" for k, v in pmeta.items())
        param_lines.append(f'        "{_quote(pname)}": {{{pmeta_str}}},')
    parameters_block = "\n".join(param_lines) if param_lines else "        # no parameters"

    # Build run() signature from parameters
    run_params_list = []
    for pname, pmeta in params.items():
        ptype = _to_py_type(pmeta.get("type", "Any"))
        default = pmeta.get("default", ...)
        if default is not ...:
            run_params_list.append(f"{pname}: {ptype} = {default!r}")
        else:
            run_params_list.append(f"{pname}: {ptype}")
    if not run_params_list:
        run_params = "**kwargs"
    else:
        run_params = ", ".join(run_params_list)

    # Determine return type annotation
    return_type = returns.split()[0] if returns else "dict"

    lines = [
        f'"""{_quote(description)}"""',
        "",
        "SKILL_META = {",
        f'    "name": "{_quote(name)}",',
        f'    "description": "{_quote(description)}",',
        f'    "author": "{_quote(author)}",',
        f'    "version": "{_quote(version)}",',
        '    "parameters": {',
        parameters_block,
        "    },",
        f'    "returns": "{_quote(returns)}",',
        '    "permissions": {',
        f'        "network": {perms.get("network", False)!s},',
        f'        "subprocess": {perms.get("subprocess", False)!s},',
        f'        "file_write": {perms.get("file_write", False)!s},',
        "    },",
        "}",
        "",
        "import logging",
        "",
        "logger = logging.getLogger(__name__)",
        "",
        "",
        f"async def run({run_params}) -> {return_type}:",
        f'    """{_quote(description)}"""',
        "    try:",
        "        # TODO: Implement skill logic",
        "        pass",
        "    except Exception:",
        f'        logger.exception("Skill {_quote(name)} failed")',
        "        raise",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_skill_meta(meta: dict) -> tuple[bool, str]:
    """Validate that a SKILL_META dict conforms to the standard schema.

    Checks:
    - ``meta`` is a dict.
    - Required keys: ``name``, ``description``, ``version``.
    - ``permissions`` (if present) only contains valid keys.

    Returns:
        ``(True, "")`` if valid, otherwise ``(False, "error message")``.
    """
    result = _ValidationResult()

    if not isinstance(meta, dict):
        return False, "SKILL_META must be a dict"

    missing = REQUIRED_META_KEYS - set(meta.keys())
    if missing:
        result.add(f"SKILL_META missing required keys: {sorted(missing)}")

    if "permissions" in meta:
        perms = meta["permissions"]
        if not isinstance(perms, dict):
            result.add("SKILL_META['permissions'] must be a dict")
        else:
            invalid = set(perms.keys()) - VALID_PERMISSIONS
            if invalid:
                result.add(f"Invalid permission keys: {sorted(invalid)}")

    if result.ok():
        return True, ""
    return False, result.summary()


def validate_run_signature(code: str) -> tuple[bool, str]:
    """Validate that *code* contains a valid ``async def run(...)`` signature.

    Checks:
    - ``run`` is declared ``async``.
    - ``run`` exists as a top-level function.

    Returns:
        ``(True, "")`` if valid, otherwise ``(False, "error message")``.
    """
    result = _ValidationResult()

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"Syntax error: {exc}"

    run_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run"
    ]

    if not run_nodes:
        sync_run_nodes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        ]
        if sync_run_nodes:
            result.add("run() must be declared async (async def run)")
        else:
            result.add("Code must contain an async def run() function")

    if result.ok():
        return True, ""
    return False, result.summary()


def validate_permissions(permissions: dict) -> tuple[bool, str]:
    """Validate a permissions dict.

    Checks:
    - All keys are in :data:`VALID_PERMISSIONS`.
    - All values are booleans.

    Returns:
        ``(True, "")`` if valid, otherwise ``(False, "error message")``.
    """
    result = _ValidationResult()

    if not isinstance(permissions, dict):
        return False, "permissions must be a dict"

    invalid_keys = set(permissions.keys()) - VALID_PERMISSIONS
    if invalid_keys:
        result.add(f"Invalid permission keys: {sorted(invalid_keys)}")

    for key, value in permissions.items():
        if not isinstance(value, bool):
            result.add(
                f"Permission '{key}' must be a boolean, got {type(value).__name__}"
            )

    if result.ok():
        return True, ""
    return False, result.summary()


# ---------------------------------------------------------------------------
# Legacy compound validator
# ---------------------------------------------------------------------------


def validate_skill_code(code: str) -> tuple[bool, str]:
    """Validate that *code* conforms to the standard skill boilerplate.

    Currently checks:
    1.  Python is syntactically valid.
    2.  A ``SKILL_META`` assignment exists.
    3.  An ``async def run`` function exists.
    4.  ``run`` is ``async`` (not sync ``def run``).
    5.  ``run`` contains at least one ``try`` / ``except`` block.
    6.  ``logging.getLogger`` is called somewhere in the module.

    Returns:
        ``(True, "")`` if valid, otherwise ``(False, "error message")``.
    """
    result = _ValidationResult()

    # 1. Syntax check
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"Syntax error: {exc}"

    # 2. SKILL_META assignment
    meta_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "SKILL_META"
            for target in node.targets
        )
    ]
    if not meta_nodes:
        result.add("Code must contain a SKILL_META dict assignment")

    # 3 & 4. async def run()
    run_valid, run_error = validate_run_signature(code)
    if not run_valid:
        result.add(run_error)

    run_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run"
    ]

    # 5. run() must accept **kwargs
    if run_nodes:
        run_node = run_nodes[0]
        if run_node.args.kwarg is None:
            result.add("run() must accept **kwargs")

    # 6. try/except inside run
    if run_nodes:
        run_node = run_nodes[0]
        try_nodes = [node for node in ast.walk(run_node) if isinstance(node, ast.Try)]
        if not try_nodes:
            result.add("run() must contain a try/except block for error handling")

    # 6. logging.getLogger call
    logger_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "logging"
        and node.func.attr == "getLogger"
    ]
    if not logger_calls:
        result.add("Code must set up a logger (logging.getLogger(__name__))")

    if result.ok():
        return True, ""
    return False, result.summary()
