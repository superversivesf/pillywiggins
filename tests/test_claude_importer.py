"""Tests for Claude skill importer."""

from pathlib import Path

import pytest

from pillywiggins.skills.claude_importer import (
    claude_to_pillywiggins,
    import_claude_skill,
    import_claude_skills,
    parse_claude_skill,
)


class TestParseClaudeSkill:
    def test_parse_basic_skill(self):
        content = """---
name: my-skill
description: A test skill
---

## Instructions
- Do this
- Do that

## Tools
- tool1: Description of tool1
- tool2: Description of tool2
"""
        result = parse_claude_skill(content)
        assert result["frontmatter"]["name"] == "my-skill"
        assert result["frontmatter"]["description"] == "A test skill"
        assert "instructions" in result["sections"]
        assert "Do this" in result["sections"]["instructions"]
        assert "tools" in result["sections"]
        assert "tool1" in result["sections"]["tools"]

    def test_parse_skill_with_parameters(self):
        content = """---
name: calc
description: Calculator
---

## Parameters
- `expression` (string): The math expression to evaluate (default: "2+2")
- `precision` (integer): Decimal places (default: "2")
"""
        result = parse_claude_skill(content)
        params_text = result["sections"]["parameters"]
        assert "expression" in params_text
        assert "precision" in params_text

    def test_parse_skill_no_frontmatter(self):
        content = """# Some skill

## Instructions
- Step 1
"""
        result = parse_claude_skill(content)
        assert result["frontmatter"] == {}
        assert "instructions" in result["sections"]

    def test_parse_empty_content(self):
        result = parse_claude_skill("")
        assert result["frontmatter"] == {}
        assert result["sections"] == {}

    def test_parse_skill_with_tools_section(self):
        content = """---
name: fetcher
description: Fetches things
---

## Tools
- fetch_url: Fetches a URL
- parse_json: Parses JSON response
"""
        result = parse_claude_skill(content)
        assert "tools" in result["sections"]
        assert "fetch_url" in result["sections"]["tools"]


class TestConvertToPillywiggins:
    def test_convert_tools_to_parameters(self):
        parsed = {
            "frontmatter": {"name": "fetcher", "description": "Fetches URLs"},
            "sections": {
                "instructions": "Fetch URLs and parse responses",
                "tools": "- fetch_url: The URL to fetch\n- timeout: Request timeout",
            },
        }
        source = claude_to_pillywiggins(parsed)
        assert '"""Fetches URLs"""' in source
        assert "'fetcher'" in source
        assert 'SKILL_META' in source
        assert 'async def run' in source
        assert '"fetch_url"' in source
        assert '"timeout"' in source
        assert 'NotImplementedError' in source

    def test_convert_with_explicit_parameters(self):
        parsed = {
            "frontmatter": {"name": "calc", "description": "Calculator"},
            "sections": {
                "instructions": "Do math",
                "parameters": '- `expr` (string): Expression (default: "")\n- `prec` (integer): Precision (default: "2")',
            },
        }
        source = claude_to_pillywiggins(parsed)
        assert '"expr"' in source
        assert '"prec"' in source
        assert '"type": "integer"' in source

    def test_convert_empty_skill(self):
        parsed = {"frontmatter": {}, "sections": {}}
        source = claude_to_pillywiggins(parsed)
        assert 'SKILL_META' in source
        assert 'async def run' in source

    def test_generated_source_is_valid_python(self):
        parsed = {
            "frontmatter": {"name": "test_skill", "description": "Test"},
            "sections": {"instructions": "Do things", "parameters": ""},
        }
        source = claude_to_pillywiggins(parsed)
        compile(source, "test_skill.py", "exec")


class TestImportToFile:
    def test_import_single_skill(self, tmp_path):
        skill_md = tmp_path / "weather.skill.md"
        skill_md.write_text(
            "---\nname: weather\ndescription: Weather lookup\n---\n\n"
            "## Instructions\n- Look up weather\n\n"
            "## Parameters\n"
            "- `city` (string): City name (default: \"London\")\n"
        )
        result = import_claude_skill(skill_md, tmp_path / "output")
        assert result.exists()
        content = result.read_text()
        assert "weather" in content
        assert "Weather lookup" in content

    def test_import_directory_of_skills(self, tmp_path):
        skill_dir = tmp_path / "skills_dir"
        skill_dir.mkdir()
        (skill_dir / "math.skill.md").write_text(
            "---\nname: math\ndescription: Math ops\n---\n"
            "## Parameters\n- `expr` (string): Expression (default: \"\")\n"
        )
        (skill_dir / "hello.skill.md").write_text(
            "---\nname: hello\ndescription: Greetings\n---\n"
        )
        out_dir = tmp_path / "converted"
        results = import_claude_skills(skill_dir, out_dir)
        assert len(results) == 2
        assert (out_dir / "math.py").exists()
        assert (out_dir / "hello.py").exists()

    def test_import_non_skill_md_skipped(self, tmp_path):
        skill_dir = tmp_path / "mixed"
        skill_dir.mkdir()
        (skill_dir / "readme.md").write_text("# README\nNot a skill")
        (skill_dir / "valid.skill.md").write_text(
            "---\nname: valid\ndescription: OK\n---\n"
        )
        results = import_claude_skills(skill_dir, tmp_path / "out")
        assert len(results) == 1
        assert "valid" in str(results[0])

    def test_import_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            import_claude_skill(tmp_path / "does_not_exist.md")

    def test_import_wrong_extension_raises(self, tmp_path):
        f = tmp_path / "thing.txt"
        f.write_text("hello")
        with pytest.raises(ValueError):
            import_claude_skill(f)
