"""Claude skill importer — converts Claude-style skill markdown to Pillywiggins skill Python files.

Claude skill format::

    ---
    name: skill-name
    description: What this skill does
    ---

    ## Instructions
    - Step 1: Do X
    - Step 2: Do Y

    ## Tools
    - tool1: description1
    - tool2: description2

    ## Parameters
    - `param_name` (string): Description of the parameter (default: "value")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

SKILL_TEMPLATE = '''"""{description}"""

SKILL_META = {{
    "name": {name!r},
    "description": {description!r},
    "author": "imported",
    "version": "1.0",
    "parameters": {params},
    "permissions": {{"network": False, "subprocess": False, "file_write": False}},
}}

{instructions}

async def run(**kwargs):
    """Skill logic — fill in after import."""
    {stubs}
'''

RE_SECTION = re.compile(r"^\s*##\s+(.+)$", re.MULTILINE)
RE_PARAM_DEF = re.compile(
    r"^\s*-\s*`(\w+)`\s*\((\w+)\)\s*:\s*(.+?)(?:\s*\(default:\s*(.+?)\))?\s*$"
)
RE_TOOL_DEF = re.compile(r"^\s*-\s*`?(\w+)`?\s*:\s*(.+)$")


def _type_to_python(typ: str) -> str:
    mapping = {"string": "str", "integer": "int", "boolean": "bool", "float": "float", "number": "float"}
    return mapping.get(typ.lower(), typ)


def parse_claude_skill(content: str) -> dict[str, Any]:
    frontmatter: dict[str, Any] = {}
    sections: dict[str, str] = {}
    body = content

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                frontmatter = {}
            body = parts[2]

    split_body = RE_SECTION.split(body)

    for i in range(1, len(split_body) - 1, 2):
        name = split_body[i].strip().lower()
        text = split_body[i + 1].strip() if i + 1 < len(split_body) else ""
        sections[name] = text

    return {"frontmatter": frontmatter, "sections": sections}


def _parse_parameters(params_text: str) -> dict[str, dict[str, str]]:
    params: dict[str, dict[str, str]] = {}
    for line in params_text.strip().splitlines():
        m = RE_PARAM_DEF.match(line.rstrip())
        if m:
            name, ptype, desc, default = m.groups()
            params[name] = {
                "type": ptype,
                "description": desc.strip(),
                "default": default.strip() if default else "",
            }
    return params


def _parse_tools(tools_text: str) -> dict[str, dict[str, str]]:
    params: dict[str, dict[str, str]] = {}
    for line in tools_text.strip().splitlines():
        m = RE_TOOL_DEF.match(line.rstrip())
        if m:
            name, desc = m.groups()
            params[name] = {
                "type": "string",
                "description": desc.strip(),
                "default": "",
            }
    return params


def claude_to_pillywiggins(parsed: dict[str, Any]) -> str:
    fm = parsed.get("frontmatter", {})
    sections = parsed.get("sections", {})

    name: str = fm.get("name", "unnamed_skill")
    description: str = fm.get("description", "Imported Claude skill")
    instructions_text: str = sections.get("instructions", "")
    params_text: str = sections.get("parameters", "")
    tools_text: str = sections.get("tools", "")

    params = _parse_parameters(params_text)
    if not params and tools_text:
        params = _parse_tools(tools_text)

    param_repr = _format_params_repr(params)

    instructions_block = f"# Instructions:\n"
    if instructions_text:
        for line in instructions_text.strip().splitlines():
            if line.strip():
                instructions_block += f"# {line.strip()}\n"
        instructions_block += "#"

    stubs_block = "# TODO: implement this skill"
    for pname in params:
        stubs_block += f"\n    raise NotImplementedError(\"Implement '{pname}' and others\")"
        break

    return SKILL_TEMPLATE.format(
        name=name,
        description=description,
        params=param_repr,
        instructions=instructions_block,
        stubs=stubs_block,
    )


def _format_params_repr(params: dict[str, dict[str, str]]) -> str:
    if not params:
        return "{}"
    lines = ["{"]
    for pname, pdef in params.items():
        lines.append(f'        "{pname}": {{')
        lines.append(f'            "type": "{pdef["type"]}",')
        lines.append(f'            "description": {pdef["description"]!r},')
        lines.append(f'            "default": {pdef.get("default", "")!r},')
        lines.append("        },")
    lines.append("    }")
    return "\n".join(lines)


def import_claude_skill(
    path: str | Path,
    output_dir: str | Path | None = None,
) -> Path:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.suffix in (".md", ".skill.md"):
        raise ValueError(f"Expected .md or .skill.md file, got {path.suffix}")

    content = path.read_text(encoding="utf-8")
    parsed = parse_claude_skill(content)
    source = claude_to_pillywiggins(parsed)

    name = parsed["frontmatter"].get("name", path.stem.removesuffix(".skill"))
    out_dir = Path(output_dir) if output_dir else Path("skills")
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{name}.py"
    out_path.write_text(source, encoding="utf-8")
    return out_path


def import_claude_skills(
    source: str | Path,
    output_dir: str | Path | None = None,
) -> list[Path]:
    source = Path(source)
    results: list[Path] = []

    if source.is_file():
        results.append(import_claude_skill(source, output_dir))
    elif source.is_dir():
        for f in sorted(source.glob("*.skill.md")):
            results.append(import_claude_skill(f, output_dir))
    else:
        raise FileNotFoundError(f"Source not found: {source}")

    return results
