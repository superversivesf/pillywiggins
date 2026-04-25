"""Standard skill boilerplate generation and validation."""

import ast
import logging
from typing import Any

logger = logging.getLogger(__name__)

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
        name=name,
        description=description,
        version=version,
        author=author,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class _ValidationResult:
    def __init__(self):
        self.errors: list[str] = []

    def add(self, msg: str) -> None:
        self.errors.append(msg)

    def ok(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        return "; ".join(self.errors)


def validate_skill_code(code: str) -> tuple[bool, str]:
    """Validate that *code* conforms to the standard skill boilerplate.

    Currently checks:
    1.  Python is syntactically valid.
    2.  A ``SKILL_META`` assignment exists.
    3.  An ``async def run`` function exists.
    4.  ``run`` is ``async`` (not sync ``def run``).
    5.  ``run`` accepts ``**kwargs``.
    6.  ``run`` contains at least one ``try`` / ``except`` block.
    7.  ``logging.getLogger`` is called somewhere in the module.

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

    # 5. run(**kwargs)
    if run_nodes:
        run_node = run_nodes[0]
        if run_node.args.kwarg is None:
            result.add("run() must accept **kwargs")

    # 6. try/except inside run
    if run_nodes:
        run_node = run_nodes[0]
        try_nodes = [
            node
            for node in ast.walk(run_node)
            if isinstance(node, ast.Try)
        ]
        if not try_nodes:
            result.add("run() must contain a try/except block for error handling")

    # 7. logging.getLogger call
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
