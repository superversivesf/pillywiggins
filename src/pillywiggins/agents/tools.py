import inspect
import json
import logging
import time

from pydantic_ai import RunContext

from pillywiggins.agents.deps import AgentDeps
from pillywiggins.security.prompt_sanitizer import sanitize_or_default

logger = logging.getLogger(__name__)

_retry_counts: dict[str, int] = {}


def _get_retry_key(ctx: RunContext[AgentDeps], tool_name: str) -> str:
    return f"{ctx.deps.conversation_key}:{tool_name}"


def _check_and_increment_retries(
    ctx: RunContext[AgentDeps],
    tool_name: str,
    max_retries: int = 2,
) -> tuple[bool, str]:
    key = _get_retry_key(ctx, tool_name)
    count = _retry_counts.get(key, 0)
    if count > max_retries:
        return (
            False,
            f"Max retries reached for {tool_name}. Please try a different skill name or approach.",
        )
    _retry_counts[key] = count + 1
    return True, ""


def _format_correction_prompt(
    tool_name: str,
    schema_errors: list[str],
    remaining: int,
) -> str:
    lines = ["Skill validation failed. Corrections needed:"]
    for i, err in enumerate(schema_errors, 1):
        lines.append(f"{i}. Schema error: {err}")
    lines.append("")
    lines.append(
        f"Fix these issues and call {tool_name} again. You have {remaining} retries remaining."
    )
    return "\n".join(lines)


def _format_current_time(tz_name: str) -> str:
    """Format the current time for a given timezone."""
    from zoneinfo import ZoneInfo as _ZoneInfo
    from datetime import datetime as _datetime

    try:
        tz = _ZoneInfo(tz_name)
    except (KeyError, ValueError):
        tz = _ZoneInfo("UTC")
    now = _datetime.now(tz)
    return now.strftime("%A, %B %d, %Y at %I:%M %p %Z")


async def _embed_text(
    text: str,
    *,
    base_url: str = "",
    api_key: str = "",
    provider: str = "",
    model: str = "",
    expected_dimension: int = 0,
) -> list[float] | None:
    """Generate an embedding for the given text using the provided config."""
    from pillywiggins.memory.embeddings import embed

    return await embed(
        text,
        base_url=base_url,
        api_key=api_key,
        provider=provider,
        model=model,
        expected_dimension=expected_dimension if expected_dimension > 0 else None,
    )


async def _draft_and_test(name: str, code: str, test_cases_json: str, tool_name: str, ctx: RunContext[AgentDeps]) -> tuple:
    """Parse test cases, create a draft, and run tests.

    Returns (draft, test_cases, error_string). If error_string is set,
    the caller should return it directly.
    """
    from pillywiggins.skills.builder import draft_skill, test_skill, DraftStatus

    allowed, message = _check_and_increment_retries(ctx, tool_name)
    if not allowed:
        return None, None, message

    try:
        test_cases = json.loads(test_cases_json)
    except json.JSONDecodeError as e:
        return None, None, f"Skill test cases JSON is invalid: {e}."

    if not isinstance(test_cases, list):
        return None, None, "Skill test cases must be a JSON array of test case objects."

    try:
        draft = draft_skill(name, code)
    except Exception as e:
        return None, None, f"Skill generation failed: {type(e).__name__}: {e}. Please fix and try again."

    if draft.status == DraftStatus.ERROR:
        error_msg = draft.test_results[0].get("error") if draft.test_results else "Unknown error"
        schema_errors = draft.meta.get("schema_errors")
        if schema_errors:
            key = _get_retry_key(ctx, tool_name)
            count = _retry_counts.get(key, 0)
            remaining = max(0, 2 - count + 1)
            return None, None, _format_correction_prompt(tool_name, schema_errors, remaining)
        return None, None, f"Skill generation failed: {error_msg}. Please fix and try again."

    try:
        draft = await test_skill(draft, test_cases)
    except Exception as e:
        return None, None, f"Skill '{name}' has test failures: {type(e).__name__}: {e}. Please fix the code and try again."

    if draft.test_results:
        failed = [r for r in draft.test_results if not r["passed"]]
        if failed:
            errors = "; ".join(str(r.get("error")) for r in failed if r.get("error"))
            return None, None, f"Skill '{name}' has test failures: {errors}. Please fix the code and try again."

    return draft, test_cases, ""


def _should_sandbox(skill_name: str, settings: "Settings | None" = None) -> bool:
    from pillywiggins.config import Settings

    if settings is None:
        settings = Settings()
    if settings.should_sandbox_all():
        return True
    return skill_name in settings.get_sandbox_skill_names()


async def _run_sandboxed_skill(skill, kwargs: dict, agent_id: str, channel: str, council_memory=None) -> str:
    from pillywiggins.skills.sandbox import run_sandboxed
    from pillywiggins.skills.logger import log_skill_execution

    if skill.file_path is None:
        err = f"Skill {skill.name} has no source file for sandbox execution."
        log_skill_execution(agent_id, channel, skill.name, kwargs, result=None, exception=err)
        return err

    try:
        code = skill.file_path.read_text()
    except Exception as e:
        err = f"Skill {skill.name} could not read source file: {e}."
        log_skill_execution(agent_id, channel, skill.name, kwargs, result=None, exception=err)
        return err

    sandbox_result = await run_sandboxed(
        code=code,
        args=kwargs,
        permissions=skill.permissions,
    )

    if not sandbox_result.success:
        err = f"Sandbox failed for {skill.name}: {sandbox_result.error}."
        log_skill_execution(
            agent_id, channel, skill.name, kwargs, result=None, exception=err
        )
        return err

    result = sandbox_result.result
    log_skill_execution(
        agent_id, channel, skill.name, kwargs, result=result
    )
    if isinstance(result, str):
        return result
    return json.dumps(result)


async def query_council_memory(ctx: RunContext[AgentDeps], query: str) -> str:
    """Search council memory for relevant shared insights from all agents.

    Args:
        query: What to search for in the shared council memory.

    Returns:
        Relevant shared insights or a message that nothing was found.
    """
    if ctx.deps.council_memory is None:
        return "Council memory is not available."

    query_embedding = await _embed_text(
        query,
        base_url=ctx.deps.llm_base_url,
        api_key=ctx.deps.llm_api_key,
        provider=ctx.deps.llm_provider,
        model=ctx.deps.embedding_model,
        expected_dimension=ctx.deps.embedding_dimension,
    )
    if query_embedding is None:
        return "Council memory could not generate embedding for search."
    results = await ctx.deps.council_memory.search(query_embedding, limit=5)
    if not results:
        return "No council insights found matching that query."
    lines = []
    for r in results:
        agent = r.get("contributing_agent", "unknown")
        content = r.get("content", "")
        mtype = r.get("message_type", "")
        lines.append(f"- [{mtype}] {content} (from {agent})")
    return sanitize_or_default("\n".join(lines), default="[Content blocked due to security policy]")


async def share_to_council(
    ctx: RunContext[AgentDeps], content: str, tags: str = "", message_type: str = "insight"
) -> str:
    """Share an insight to the shared council memory for all agents to see.

    Args:
        content: The insight or information to share. Be concise and specific.
        tags: Comma-separated tags to categorize this insight (e.g. "idea,learning").
        message_type: Type of message — one of: insight, skill_announcement, question, proposal.

    Returns:
        Confirmation that the insight was shared, or an error message.
    """
    if ctx.deps.council_memory is None:
        return "Council memory is not available."

    embedding = await _embed_text(
        content,
        base_url=ctx.deps.llm_base_url,
        api_key=ctx.deps.llm_api_key,
        provider=ctx.deps.llm_provider,
        model=ctx.deps.embedding_model,
        expected_dimension=ctx.deps.embedding_dimension,
    )
    if embedding is None:
        return "Council memory could not generate embedding."
    parsed_tags = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    result = await ctx.deps.council_memory.write_entry(
        content=content,
        tags=parsed_tags,
        embedding=embedding,
        message_type=message_type,
    )
    if not result.get("success"):
        return f"Council memory could not share insight: {result.get('error', 'unknown error')}."
    if ctx.deps.nats_bus is not None:
        try:
            await ctx.deps.nats_bus.publish_broadcast(
                "insight", {"content": content, "tags": parsed_tags, "embedding": embedding}
            )
        except Exception:
            pass
    return sanitize_or_default(f"Shared to council: {content}", default="[Content blocked due to security policy]")


async def recall_private_memory(ctx: RunContext[AgentDeps], query: str) -> str:
    """Search your private memory for relevant past experiences or notes.

    Args:
        query: What to search for in your memories.

    Returns:
        Relevant memories or a message that nothing was found.
    """
    if ctx.deps.private_memory is None:
        return "Private memory is not available."

    query_embedding = await _embed_text(
        query,
        base_url=ctx.deps.llm_base_url,
        api_key=ctx.deps.llm_api_key,
        provider=ctx.deps.llm_provider,
        model=ctx.deps.embedding_model,
        expected_dimension=ctx.deps.embedding_dimension,
    )
    if query_embedding is None:
        return "Private memory could not generate embedding for search."
    results = await ctx.deps.private_memory.search(query_embedding, limit=5)
    if not results:
        return "No memories found matching that query."
    lines = []
    for r in results:
        lines.append(f"- {r['content']} (similarity: {r['similarity']:.2f})")
    return sanitize_or_default("\n".join(lines), default="[Content blocked due to security policy]")


async def save_to_private_memory(ctx: RunContext[AgentDeps], content: str) -> str:
    """Save something to your private memory for later recall.

    Use this to remember important facts, user preferences, or key moments
    from the conversation that you might want to reference later.

    Args:
        content: What to remember. Be concise and specific.

    Returns:
        Confirmation that the memory was saved, or an error message.
    """
    if ctx.deps.private_memory is None:
        return "Private memory is not available."

    embedding = await _embed_text(
        content,
        base_url=ctx.deps.llm_base_url,
        api_key=ctx.deps.llm_api_key,
        provider=ctx.deps.llm_provider,
        model=ctx.deps.embedding_model,
        expected_dimension=ctx.deps.embedding_dimension,
    )
    if embedding is None:
        return "Private memory could not generate embedding."
    saved = await ctx.deps.private_memory.save(content, embedding)
    if not saved:
        return "Private memory failed to save. This can happen when the database is unreachable or the embedding dimension is mis-configured (check EMBEDDING_DIMENSION)."
    return sanitize_or_default(f"Remembered: {content}", default="[Content blocked due to security policy]")


async def summarize_conversation(ctx: RunContext[AgentDeps]) -> str:
    """Generate a brief summary of the conversation so far to save context window space.

    Use this when the conversation history is getting long.  You (the LLM) have the
    full history in your context — produce a concise summary of the key topics,
    decisions, and user preferences discussed, then call this tool to record it.

    Returns:
        Confirmation that the summary was recorded, or an error message.
    """
    agent = getattr(ctx.deps, "agent", None)
    if agent is None:
        return "Cannot summarize: agent not available."

    try:
        info = ctx.deps.conversation_info()
        message_count = info.get("message_count", 0)
        estimated_tokens = info.get("estimated_tokens", 0)
        return (
            f"Conversation summary checkpoint recorded. "
            f"Current conversation has {message_count} messages "
            f"(~{estimated_tokens} tokens). "
            f"The summary you provided will be included in future context windows."
        )
    except Exception as exc:
        logger.exception("summarize_conversation failed")
        return f"Summarization failed: {exc}"


async def consolidate_memory(ctx: RunContext[AgentDeps]) -> str:
    """Manually trigger memory consolidation — compact conversation history and save the summary.

    Returns a summary of what was consolidated.
    """
    agent = getattr(ctx.deps, "agent", None)
    if agent is None:
        return "Cannot consolidate: agent not available."

    try:
        result = await agent.compact_history()
        return f"Memory consolidated: {result}"
    except Exception as exc:
        logger.exception("consolidate_memory failed")
        return f"Memory consolidation failed: {exc}"


async def test_driven_skill(
    ctx: RunContext[AgentDeps], name: str, code: str, test_code: str
) -> str:
    """**DEPRECATED** — Use ``build_and_publish_skill`` instead.

    Validate both skill code and test code, then run tests in the sandbox.

    .. deprecated::
        This requires multiple tool calls to complete the full pipeline.
        Use ``build_and_publish_skill`` which handles draft, test, and publish
        in a single call.

    This is the TDD (test-driven development) path: the user provides both
    the skill implementation and the test assertions.  The system validates that
    both parse cleanly, then injects the test code into a sandbox alongside
    the skill code and reports pass / fail results.

    Args:
        name: The skill name.
        code: The Python source code for the skill. Must contain SKILL_META
            and an async def run() function.
        test_code: Python test code.  It runs in the same module scope as the
            skill code, so it can call ``run()`` directly.  Use standard
            Python ``assert`` statements for checks.

    Returns:
        Pass / fail results, including any validation or execution errors.
    """
    from pillywiggins.skills.builder import test_driven_skill as _test_driven, DraftStatus

    try:
        draft = await _test_driven(name, code, test_code)
    except Exception as e:
        return f"TDD skill validation failed: {type(e).__name__}: {e}. Please fix and try again."

    if draft.status == DraftStatus.ERROR:
        error_msg = draft.test_results[0].get("error") if draft.test_results else "Unknown error"
        return f"TDD skill validation failed: {error_msg}. Please fix and try again."

    lines = []
    lines.append(f"TDD skill '{draft.name}' passed validation")
    if draft.test_results:
        elapsed = draft.test_results[0].get("execution_time_ms", 0.0)
        lines.append(f"Tests completed in {elapsed:.1f}ms")
    lines.append("Status: draft (ready for review and publish)")
    lines.append("")
    lines.append("Use build_and_publish_skill for the complete single-call pipeline (recommended).")
    return "\n".join(lines)


async def build_skill(ctx: RunContext[AgentDeps], name: str, code: str) -> str:
    """Create a skill draft from code. Validates the code and returns draft info or validation errors.

    The code must conform to the skill schema:
    - SKILL_META must be a top-level dict assignment with keys: name, description, parameters, permissions.
    - permissions must be a dict like {"network": False, "subprocess": False, "file_write": False}.
    - Must contain an async def run() function at the top level.
    - No disallowed imports (e.g. requests).
    - No dangerous patterns (os.system, eval, exec, subprocess.Popen) unless permitted.

    Args:
        name: The skill name (used for the filename and registry entry).
        code: The Python source code for the skill.

    Returns:
        Draft info including name and meta, or a validation error / retry message.
    """
    from pillywiggins.skills.builder import draft_skill, DraftStatus, get_progress_message

    allowed, message = _check_and_increment_retries(ctx, "build_skill")
    if not allowed:
        return message

    progress = get_progress_message("drafting")

    try:
        draft = draft_skill(name, code)
    except Exception as e:
        return progress + "\n" + f"Skill generation failed: {type(e).__name__}: {e}. Please fix and try again."

    if draft.status == DraftStatus.ERROR:
        error_msg = draft.test_results[0].get("error") if draft.test_results else "Unknown error"
        schema_errors = draft.meta.get("schema_errors")
        if schema_errors:
            key = _get_retry_key(ctx, "build_skill")
            count = _retry_counts.get(key, 0)
            remaining = max(0, 2 - count + 1)  # current call is already counted
            return progress + "\n" + _format_correction_prompt("build_skill", schema_errors, remaining)
        return progress + "\n" + f"Skill generation failed: {error_msg}. Please fix and try again."

    lines = []
    lines.append(progress)
    lines.append(f"Draft created: {draft.name}")
    lines.append(f"Status: {draft.status.value}")
    lines.append(f"Description: {draft.meta.get('description', '(none)')}")
    permissions = draft.permissions
    perms = [k for k, v in permissions.items() if v]
    if perms:
        lines.append(f"Permissions requested: {', '.join(perms)}")
    else:
        lines.append("Permissions: none")
    lines.append("")
    lines.append("Use test_skill_code to run tests, or review_skill_code to review.")
    return sanitize_or_default("\n".join(lines), default="[Content blocked due to security policy]")


async def test_skill_code(
    ctx: RunContext[AgentDeps], name: str, code: str, test_cases_json: str
) -> str:
    """Run test cases against a skill draft. Creates a draft, then executes each test case in the sandbox.

    The code must conform to the skill schema:
    - SKILL_META must be a top-level dict assignment with keys: name, description, parameters, permissions.
    - permissions must be a dict like {"network": False, "subprocess": False, "file_write": False}.
    - Must contain an async def run() function at the top level.
    - No disallowed imports (e.g. requests).
    - No dangerous patterns (os.system, eval, exec, subprocess.Popen) unless permitted.

    Args:
        name: The skill name.
        code: The Python source code for the skill.
        test_cases_json: A JSON array of test cases. Each test case is an object with "args" (dict of kwargs for run()) and "expected" (the expected return value, or omit to only check for no errors).

    Returns:
        Pass/fail results for each test case, or a retry / correction message.
    """
    draft, test_cases, error = await _draft_and_test(name, code, test_cases_json, "test_skill_code", ctx)
    if error:
        from pillywiggins.skills.builder import get_progress_message
        return get_progress_message("testing") + "\n" + error

    from pillywiggins.skills.builder import get_progress_message
    passed_count = sum(1 for r in draft.test_results if r["passed"])
    total_count = len(draft.test_results)
    lines = []
    lines.append(get_progress_message("testing"))
    lines.append(f"Test results for '{name}': {passed_count}/{total_count} passed")
    lines.append("")

    for i, result in enumerate(draft.test_results, 1):
        status = "PASS" if result["passed"] else "FAIL"
        lines.append(f"  Test {i}: [{status}]")
        lines.append(f"    Args: {result['args']}")
        if result.get("expected") is not None:
            lines.append(f"    Expected: {result['expected']}")
        lines.append(f"    Actual: {result.get('actual')}")
        if result.get("error"):
            lines.append(f"    Error: {result['error']}")
        lines.append(f"    Time: {result.get('execution_time_ms', 0):.1f}ms")

    return sanitize_or_default("\n".join(lines), default="[Content blocked due to security policy]")


async def review_skill_code(
    ctx: RunContext[AgentDeps], name: str, code: str, test_cases_json: str
) -> str:
    """Format skill code for user review. Creates a draft, runs tests, then produces a review summary.

    The code must conform to the skill schema:
    - SKILL_META must be a top-level dict assignment with keys: name, description, parameters, permissions.
    - permissions must be a dict like {"network": False, "subprocess": False, "file_write": False}.
    - Must contain an async def run() function at the top level.
    - No disallowed imports (e.g. requests).
    - No dangerous patterns (os.system, eval, exec, subprocess.Popen) unless permitted.

    Args:
        name: The skill name.
        code: The Python source code for the skill.
        test_cases_json: A JSON array of test cases (same format as test_skill_code).

    Returns:
        Formatted review output with code, test results, and an approval request, or a retry / correction message.
    """
    from pillywiggins.skills.builder import review_skill, get_progress_message

    draft, test_cases, error = await _draft_and_test(name, code, test_cases_json, "review_skill_code", ctx)
    if error:
        return get_progress_message("reviewing") + "\n" + error

    return sanitize_or_default(get_progress_message("reviewing") + "\n" + review_skill(draft), default="[Content blocked due to security policy]")


async def publish_skill_code(
    ctx: RunContext[AgentDeps], name: str, code: str, test_cases_json: str, approved: bool
) -> str:
    """Publish an approved skill. The user must explicitly set approved=True to confirm publication.

    The code must conform to the skill schema:
    - SKILL_META must be a top-level dict assignment with keys: name, description, parameters, permissions.
    - permissions must be a dict like {"network": False, "subprocess": False, "file_write": False}.
    - Must contain an async def run() function at the top level.
    - No disallowed imports (e.g. requests).
    - No dangerous patterns (os.system, eval, exec, subprocess.Popen) unless permitted.

    Args:
        name: The skill name.
        code: The Python source code for the skill.
        test_cases_json: A JSON array of test cases (same format as test_skill_code).
        approved: Must be True for the skill to be published. Set to True only after user review.

    Returns:
        Publication confirmation or an error/rejection / retry message.
    """
    from pillywiggins.skills.builder import publish_skill, get_progress_message

    draft, test_cases, error = await _draft_and_test(name, code, test_cases_json, "publish_skill_code", ctx)
    if error:
        return get_progress_message("publishing") + "\n" + error

    settings = ctx.deps.settings
    skills_dir = settings.skills_dir if settings is not None else "/app/skills"
    result = await publish_skill(
        draft,
        approved=approved,
        skills_dir=skills_dir,
        registry=ctx.deps.skill_registry,
        nats_bus=ctx.deps.nats_bus,
    )
    return sanitize_or_default(get_progress_message("publishing") + "\n" + result, default="[Content blocked due to security policy]")


async def build_and_publish_skill(
    ctx: RunContext[AgentDeps],
    name: str,
    description: str,
    code: str,
) -> str:
    """Build, test, and publish a skill in a single call. This is the **recommended** tool.

    Unlike the multi-step pipeline (build_skill → test_skill_code → review_skill_code →
    publish_skill_code), this tool does everything in one async call.  The LLM must
    provide the skill name, description, and full Python source code.  The tool will:

    1. Draft the skill (validate schema, extract SKILL_META)
    2. Run a smoke test in the sandbox (calls ``run()`` with empty args)
    3. If the smoke test passes, auto-publish: write the file, register with the
       registry, and broadcast via NATS
    4. Return a comprehensive result showing each stage outcome

    The code must conform to the skill schema:
    - SKILL_META must be a top-level dict assignment with keys: name, description, parameters, permissions.
    - permissions must be a dict like {"network": False, "subprocess": False, "file_write": False}.
    - Must contain an async def run() function at the top level.
    - No disallowed imports (e.g. requests).
    - No dangerous patterns (os.system, eval, exec, subprocess.Popen) unless permitted.

    Args:
        name: The skill name (used for the filename and registry entry).
        description: A human-readable description of what the skill does.
        code: The complete Python source code for the skill, including SKILL_META.

    Returns:
        Comprehensive result showing draft, test, and publish outcomes.
    """
    from pillywiggins.skills.builder import (
        draft_skill,
        publish_skill,
        get_progress_message,
        DraftStatus,
    )
    from pillywiggins.skills.sandbox import run_sandboxed

    lines: list[str] = []

    # —— Stage 1: Draft ——
    lines.append(get_progress_message("drafting"))
    try:
        draft = draft_skill(name, code)
    except Exception as exc:
        lines.append(f"❌ Draft failed: {type(exc).__name__}: {exc}")
        return "\n".join(lines)

    if draft.status == DraftStatus.ERROR:
        error_msg = draft.test_results[0].get("error", "Unknown error") if draft.test_results else "Unknown error"
        lines.append(f"❌ Draft validation failed: {error_msg}")
        schema_errors = draft.meta.get("schema_errors")
        if schema_errors:
            for err in schema_errors:
                lines.append(f"  • Schema error: {err}")
        return "\n".join(lines)

    lines.append(f"✅ Draft created: {draft.name}")
    lines.append(f"   Description: {draft.meta.get('description', description)}")
    perms = [k for k, v in draft.permissions.items() if v]
    if perms:
        lines.append(f"   Permissions: {', '.join(perms)}")
    else:
        lines.append("   Permissions: none")

    # —— Stage 2: Smoke Test ——
    lines.append("")
    lines.append(get_progress_message("testing"))
    try:
        sandbox_result = await run_sandboxed(
            draft.code,
            args={},
            permissions=draft.permissions,
        )
    except Exception as exc:
        lines.append(f"❌ Smoke test failed (exception): {type(exc).__name__}: {exc}")
        return "\n".join(lines)

    if not sandbox_result.success:
        lines.append(f"❌ Smoke test failed: {sandbox_result.error}")
        lines.append(f"   Execution time: {sandbox_result.execution_time_ms:.1f}ms")
        lines.append("")
        lines.append("→ Fix the skill code and call build_and_publish_skill again.")
        return "\n".join(lines)

    draft.test_results = [
        {
            "args": {},
            "expected": None,
            "passed": True,
            "actual": str(sandbox_result.result)[:200] if sandbox_result.result else None,
            "error": None,
            "timed_out": False,
            "execution_time_ms": sandbox_result.execution_time_ms,
        }
    ]
    draft.status = DraftStatus.TESTED
    lines.append(f"✅ Smoke test passed in {sandbox_result.execution_time_ms:.1f}ms")
    if sandbox_result.result is not None:
        result_preview = str(sandbox_result.result)[:200]
        lines.append(f"   Result preview: {result_preview}")

    # —— Stage 3: Publish ——
    lines.append("")
    lines.append(get_progress_message("publishing"))
    settings = ctx.deps.settings
    skills_dir = settings.skills_dir if settings is not None else "/app/skills"
    pub_result = await publish_skill(
        draft,
        approved=True,
        skills_dir=skills_dir,
        registry=ctx.deps.skill_registry,
        nats_bus=ctx.deps.nats_bus,
    )
    if "successfully" in pub_result:
        lines.append(f"✅ {pub_result}")
    else:
        lines.append(f"❌ Publish failed: {pub_result}")
        return "\n".join(lines)

    # —— Summary ——
    lines.append("")
    lines.append("─" * 40)
    lines.append(f"Skill '{name}' built, tested, and published in one call.")
    return sanitize_or_default("\n".join(lines), default="[Content blocked due to security policy]")


async def schedule_task(
    ctx: RunContext[AgentDeps],
    name: str,
    action: str,
    interval_seconds: int = 0,
    cron_expr: str = "",
    args_json: str = "",
) -> str:
    """Add a scheduled task that runs periodically or on a cron schedule.

    Args:
        name: A unique name for this scheduled task.
        action: The action to perform. Available actions:
            - "send_message": Send a proactive message to the current chat. The conversation_key
              is automatically set from the current conversation. Optionally provide args_json with
              {"prompt": "<instruction for LLM>"}. Do NOT ask the user for their chat ID.
            - "heartbeat": Broadcast heartbeat via NATS.
            - "memory_review": Log a memory review.
            - "skill_reload": Log a skill reload.
            - "custom": Run a custom action with arbitrary args.
        interval_seconds: Run every N seconds. Use 0 if using cron_expr instead.
        cron_expr: A 5-field cron expression (e.g. "0 * * * *"). Use empty string if using interval_seconds.
        args_json: Optional JSON object of arguments to pass to the action handler.

    Returns:
        Confirmation that the task was scheduled, or an error message.
    """

    if ctx.deps.scheduler is None:
        return "Scheduler is not available."

    args = None
    if args_json:
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError as e:
            return f"Scheduler received invalid args_json: {e}."

    if action == "send_message" and args:
        if not args.get("conversation_key") and ctx.deps.conversation_key:
            args["conversation_key"] = ctx.deps.conversation_key
        if not args.get("chat_id") and ctx.deps.conversation_key:
            args["chat_id"] = ctx.deps.conversation_key

    interval = interval_seconds if interval_seconds > 0 else None
    cron = cron_expr if cron_expr else None

    result = await ctx.deps.scheduler.add_job(
        name=name,
        action=action,
        interval_seconds=interval,
        cron_expr=cron,
        args=args,
    )

    if result.get("success"):
        return sanitize_or_default(f"Scheduled task '{name}' (action: {action})", default="[Content blocked due to security policy]")
    return sanitize_or_default(f"Failed to schedule task '{name}': {result.get('error', 'unknown error')}", default="[Content blocked due to security policy]")


async def unschedule_task(ctx: RunContext[AgentDeps], name: str) -> str:
    """Remove a previously scheduled task by name.

    Args:
        name: The name of the scheduled task to remove.

    Returns:
        Confirmation that the task was removed, or an error message.
    """
    if ctx.deps.scheduler is None:
        return "Scheduler is not available."

    removed = await ctx.deps.scheduler.remove_job(name)
    if removed:
        return sanitize_or_default(f"Unscheduled task '{name}'", default="[Content blocked due to security policy]")
    return sanitize_or_default(f"Scheduler task '{name}' is not found.", default="[Content blocked due to security policy]")


async def list_scheduled_tasks(ctx: RunContext[AgentDeps]) -> str:
    """List all currently scheduled tasks for this agent.

    Returns:
        A formatted list of scheduled tasks with their names, actions,
        next run times, and arguments, or a message if none exist.
    """

    if ctx.deps.scheduler is None:
        return "Scheduler is not available."

    jobs = await ctx.deps.scheduler.list_jobs()
    if not jobs:
        return "No scheduled tasks"

    lines = [f"Scheduled tasks ({len(jobs)}):"]
    for i, job in enumerate(jobs, 1):
        name = job.get("name", "unnamed")
        action = job.get("action", "unknown")
        next_run = job.get("next_run_time", "N/A")
        parts = [f"{i}. {name} (action: {action}, next: {next_run}"]
        args = job.get("args")
        if args:
            parts.append(f", args: {json.dumps(args)}")
        parts.append(")")
        lines.append("".join(parts))
    return "\n".join(lines)


async def get_conversation_info(ctx: RunContext[AgentDeps]) -> str:
    """Get information about the current conversation.

    Returns the number of messages and estimated token count.
    """
    info = ctx.deps.conversation_info()
    message_count = info.get("message_count", 0)
    estimated_tokens = info.get("estimated_tokens", 0)
    return f"Conversation has {message_count} messages (approximately {estimated_tokens} tokens)."


async def send_message_to_agent(
    ctx: RunContext[AgentDeps],
    target_agent_id: str,
    message: str,
) -> str:
    """Send a direct message to another agent via NATS.

    Args:
        target_agent_id: The ID of the agent to send the message to.
        message: The message content to send.

    Returns:
        Confirmation that the message was sent, or an error message.
    """
    if ctx.deps.nats_bus is None:
        return "NATS bus is not available."
    from pillywiggins.messaging.unified import ChannelType, UnifiedMessage

    msg = UnifiedMessage(
        channel=ChannelType(ctx.deps.channel) if ctx.deps.channel else ChannelType.TELEGRAM,
        channel_user_id=ctx.deps.channel_user_id or ctx.deps.agent_id,
        content=message,
        conversation_key=ctx.deps.conversation_key or "",
        metadata=ctx.deps.metadata or {"from": ctx.deps.agent_id},
    )
    nats_data = {
        "channel": msg.channel.value,
        "channel_user_id": msg.channel_user_id,
        "content": msg.content,
        "conversation_key": msg.conversation_key,
        "metadata": msg.metadata,
        "routing_info": {
            "original_channel": ctx.deps.channel,
            "original_channel_user_id": ctx.deps.channel_user_id,
            "original_conversation_key": ctx.deps.conversation_key,
            "original_metadata": ctx.deps.metadata or {},
        },
    }
    await ctx.deps.nats_bus.publish_direct(
        target_agent_id=target_agent_id,
        message_type="message",
        data=nats_data,
    )
    return sanitize_or_default(f"Sent message to {target_agent_id}", default="[Content blocked due to security policy]")


async def remove_skill(ctx: RunContext[AgentDeps], name: str) -> str:
    """Remove a skill by name. Deletes the skill file and unregisters it from the registry.

    Args:
        name: The name of the skill to remove (e.g. 'get_london_weather').

    Returns:
        Confirmation that the skill was removed, or an error message.
    """
    if ctx.deps.skill_registry is None:
        return "No skill registry available."
    if not name:
        return "Please provide a skill name to remove."
    removed = ctx.deps.skill_registry.unregister_skill(name)
    if removed:
        return sanitize_or_default(f"Skill '{name}' has been removed.", default="[Content blocked due to security policy]")
    return f"Skill '{name}' not found in the registry."


async def get_current_time(ctx: RunContext[AgentDeps]) -> str:
    """Get the current date and time in your configured timezone.

    Use this to know what time it is for you right now, including the date,
    day of week, and whether it is morning, afternoon, or evening.

    Returns:
        The current date and time formatted for readability, e.g.
        "Wednesday, April 22, 2026 at 03:45 PM PDT (America/Los_Angeles)".
    """
    personality = ctx.deps.personality
    tz_name = personality.timezone if personality else "UTC"
    formatted = _format_current_time(tz_name)
    return f"{formatted} ({tz_name})"


def _make_skill_tool(skill):
    """Wrap a Skill as a PydanticAI-compatible tool function.

    Builds explicit __signature__ and __annotations__ from SKILL_META
    so PydanticAI can generate structured JSON schema for the LLM.
    Previously bare **kwargs meant small models (Qwen 3.5 8B) would
    occasionally omit required parameters like ``query``.
    """
    params = skill.meta.get("parameters", {})

    # Build inspect.Parameter objects from SKILL_META (same logic as
    # Skill.as_tool() in registry.py).
    sig_params: list[inspect.Parameter] = []
    for pname, pdef in params.items():
        ptype = pdef.get("type", "string")
        if ptype == "integer":
            annotation = int
        elif ptype == "boolean":
            annotation = bool
        elif ptype in ("number", "float"):
            annotation = float
        else:
            annotation = str

        default = pdef.get("default", inspect.Parameter.empty)
        sig_params.append(
            inspect.Parameter(
                pname,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=default,
                annotation=annotation,
            )
        )

    # Build docstring with parameter descriptions (Google-style).
    if params:
        param_lines = []
        for pname, pdef in params.items():
            ptype = pdef.get("type", "string")
            pdesc = pdef.get("description", "")
            pdefault = pdef.get("default")
            line = f"    {pname} ({ptype})"
            if pdesc:
                line += f": {pdesc}"
            if pdefault is not None:
                line += f" (default: {pdefault})"
            param_lines.append(line)
        param_str = "\n" + "\n".join(param_lines)
    else:
        param_str = ""

    perm_list = [k for k, v in skill.permissions.items() if v]
    perm_str = f" Permissions: {', '.join(perm_list)}." if perm_list else ""

    doc = skill.description
    if param_str:
        doc += f"\n\nArgs:{param_str}"
    doc += perm_str

    async def skill_tool(ctx: RunContext[AgentDeps], **kwargs) -> str:

        agent_id = ctx.deps.agent_id
        channel = ctx.deps.channel
        agent_logger = ctx.deps.logger

        if _should_sandbox(skill.name, settings=ctx.deps.settings):
            return await _run_sandboxed_skill(skill, kwargs, agent_id, channel, ctx.deps.council_memory)
        start = time.perf_counter()
        try:
            result = await skill.execute(agent_id=agent_id, channel=channel, **kwargs)
        except TypeError as e:
            duration_ms = (time.perf_counter() - start) * 1000
            available = ", ".join(skill.meta.get("parameters", {}).keys())
            err = f"Skill {skill.name} received invalid arguments: {e}. Available parameters: {available}."
            if agent_logger is not None:
                agent_logger.log_tool_error(skill.name, err, duration_ms)
            return err
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            err = f"Skill {skill.name} failed to execute: {e}."
            if agent_logger is not None:
                agent_logger.log_tool_error(skill.name, err, duration_ms)
            return err
        duration_ms = (time.perf_counter() - start) * 1000
        if agent_logger is not None:
            agent_logger.log_tool_result(skill.name, result, duration_ms)
        if isinstance(result, str):
            return result
        return json.dumps(result)

    skill_tool.__name__ = skill.name
    skill_tool.__doc__ = doc

    # Attach explicit __signature__ and __annotations__ so PydanticAI can
    # introspect structured parameters instead of bare **kwargs.
    # This is what Skill.as_tool() does, but we keep the full RunContext,
    # sandboxing, logging, and error-handling infrastructure.
    # We must also include ctx as the first parameter since PydanticAI
    # infers takes_ctx=True from the source-level annotations.
    full_sig_params = [
        inspect.Parameter(
            "ctx",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=RunContext[AgentDeps],
        ),
        *sig_params,
    ]
    skill_tool.__signature__ = inspect.Signature(full_sig_params)
    skill_tool.__annotations__ = {
        "ctx": RunContext[AgentDeps],
        **{p.name: p.annotation for p in sig_params},
        "return": str,
    }

    return skill_tool