import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from pillywiggins.agents.deps import AgentDeps
from pillywiggins.logging_utils import AgentLogger


def _should_sandbox(skill_name: str) -> bool:
    from pillywiggins.config import Settings

    settings = Settings()
    if settings.should_sandbox_all():
        return True
    return skill_name in settings.get_sandbox_skill_names()


async def _run_sandboxed_skill(skill, kwargs: dict, agent_id: str, channel: str, council_memory=None) -> str:
    import json
    from pillywiggins.skills.sandbox import run_sandboxed
    from pillywiggins.skills.logger import log_skill_execution

    if skill.file_path is None:
        err = f"Error: skill {skill.name} has no source file for sandbox execution"
        log_skill_execution(agent_id, channel, skill.name, kwargs, result=None, exception=err)
        return err

    try:
        code = skill.file_path.read_text()
    except Exception as e:
        err = f"Error reading skill source for {skill.name}: {e}"
        log_skill_execution(agent_id, channel, skill.name, kwargs, result=None, exception=err)
        return err

    sandbox_result = await run_sandboxed(
        code=code,
        args=kwargs,
        permissions=skill.permissions,
    )

    if not sandbox_result.success:
        err = f"Sandbox error in {skill.name}: {sandbox_result.error}"
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
    from pillywiggins.memory.embeddings import embed
    from pillywiggins.config import Settings

    settings = Settings()
    query_embedding = await embed(
        query,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        provider=settings.llm_provider,
        model=settings.embedding_model,
        expected_dimension=settings.embedding_dimension,
    )
    if query_embedding is None:
        return "Could not generate embedding for council search."
    results = await ctx.deps.council_memory.search(query_embedding, limit=5)
    if not results:
        return "No council insights found matching that query."
    lines = []
    for r in results:
        agent = r.get("contributing_agent", "unknown")
        content = r.get("content", "")
        mtype = r.get("message_type", "")
        lines.append(f"- [{mtype}] {content} (from {agent})")
    return "\n".join(lines)


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
    from pillywiggins.memory.embeddings import embed
    from pillywiggins.config import Settings

    settings = Settings()
    embedding = await embed(
        content,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        provider=settings.llm_provider,
        model=settings.embedding_model,
        expected_dimension=settings.embedding_dimension,
    )
    if embedding is None:
        return "Could not generate embedding — council insight not shared."
    parsed_tags = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    result = await ctx.deps.council_memory.write_entry(
        content=content,
        tags=parsed_tags,
        embedding=embedding,
        message_type=message_type,
    )
    if not result.get("success"):
        return f"Could not share to council: {result.get('error', 'unknown error')}"
    if ctx.deps.nats_bus is not None:
        try:
            await ctx.deps.nats_bus.publish_broadcast(
                "insight", {"content": content, "tags": parsed_tags, "embedding": embedding}
            )
        except Exception:
            pass
    return f"Shared to council: {content}"


async def recall_private_memory(ctx: RunContext[AgentDeps], query: str) -> str:
    """Search your private memory for relevant past experiences or notes.

    Args:
        query: What to search for in your memories.

    Returns:
        Relevant memories or a message that nothing was found.
    """
    if ctx.deps.private_memory is None:
        return "Private memory is not available."
    from pillywiggins.memory.embeddings import embed
    from pillywiggins.config import Settings

    settings = Settings()
    query_embedding = await embed(
        query,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        provider=settings.llm_provider,
        model=settings.embedding_model,
        expected_dimension=settings.embedding_dimension,
    )
    if query_embedding is None:
        return "Could not generate embedding for search."
    results = await ctx.deps.private_memory.search(query_embedding, limit=5)
    if not results:
        return "No memories found matching that query."
    lines = []
    for r in results:
        lines.append(f"- {r['content']} (similarity: {r['similarity']:.2f})")
    return "\n".join(lines)


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
    from pillywiggins.memory.embeddings import embed
    from pillywiggins.config import Settings

    settings = Settings()
    embedding = await embed(
        content,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        provider=settings.llm_provider,
        model=settings.embedding_model,
        expected_dimension=settings.embedding_dimension,
    )
    if embedding is None:
        return "Could not generate embedding \u2014 memory not saved."
    saved = await ctx.deps.private_memory.save(content, embedding)
    if not saved:
        return "Memory save failed. This can happen when the database is unreachable or the embedding dimension is mis-configured (check EMBEDDING_DIMENSION)."
    return f"Remembered: {content}"


async def test_driven_skill(
    ctx: RunContext[AgentDeps], name: str, code: str, test_code: str
) -> str:
    """Validate both skill code and test code, then run tests in the sandbox.

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
    lines.append("Use review_skill_code to review, then publish_skill_code to publish.")
    return "\n".join(lines)


async def build_skill(ctx: RunContext[AgentDeps], name: str, code: str) -> str:
    """Create a skill draft from code. Validates the code and returns draft info or validation errors.

    Args:
        name: The skill name (used for the filename and registry entry).
        code: The Python source code for the skill. Must contain SKILL_META and an async def run() function.

    Returns:
        Draft info including name and meta, or a validation error message.
    """
    from pillywiggins.skills.builder import draft_skill, DraftStatus

    try:
        draft = draft_skill(name, code)
    except Exception as e:
        return f"Skill generation failed: {type(e).__name__}: {e}. Please fix and try again."

    if draft.status == DraftStatus.ERROR:
        error_msg = draft.test_results[0].get("error") if draft.test_results else "Unknown error"
        return f"Skill generation failed: {error_msg}. Please fix and try again."

    lines = []
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
    return "\n".join(lines)


async def test_skill_code(
    ctx: RunContext[AgentDeps], name: str, code: str, test_cases_json: str
) -> str:
    """Run test cases against a skill draft. Creates a draft, then executes each test case in the sandbox.

    Args:
        name: The skill name.
        code: The Python source code for the skill.
        test_cases_json: A JSON array of test cases. Each test case is an object with "args" (dict of kwargs for run()) and "expected" (the expected return value, or omit to only check for no errors).

    Returns:
        Pass/fail results for each test case.
    """
    import json
    from pillywiggins.skills.builder import draft_skill, test_skill, DraftStatus

    try:
        test_cases = json.loads(test_cases_json)
    except json.JSONDecodeError as e:
        return f"Invalid test_cases_json: {e}"

    if not isinstance(test_cases, list):
        return "test_cases_json must be a JSON array of test case objects."

    try:
        draft = draft_skill(name, code)
    except Exception as e:
        return f"Skill generation failed: {type(e).__name__}: {e}. Please fix and try again."

    if draft.status == DraftStatus.ERROR:
        error_msg = draft.test_results[0].get("error") if draft.test_results else "Unknown error"
        return f"Skill generation failed: {error_msg}. Please fix and try again."

    try:
        draft = await test_skill(draft, test_cases)
    except Exception as e:
        return f"Skill '{name}' has test failures: {type(e).__name__}: {e}. Please fix the code and try again."

    if draft.test_results:
        failed = [r for r in draft.test_results if not r["passed"]]
        if failed:
            errors = "; ".join(str(r.get("error")) for r in failed if r.get("error"))
            return f"Skill '{name}' has test failures: {errors}. Please fix the code and try again."

    passed_count = sum(1 for r in draft.test_results if r["passed"])
    total_count = len(draft.test_results)
    lines = []
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

    return "\n".join(lines)


async def review_skill_code(
    ctx: RunContext[AgentDeps], name: str, code: str, test_cases_json: str
) -> str:
    """Format skill code for user review. Creates a draft, runs tests, then produces a review summary.

    Args:
        name: The skill name.
        code: The Python source code for the skill.
        test_cases_json: A JSON array of test cases (same format as test_skill_code).

    Returns:
        Formatted review output with code, test results, and an approval request.
    """
    import json
    from pillywiggins.skills.builder import draft_skill, test_skill, review_skill, DraftStatus

    try:
        test_cases = json.loads(test_cases_json)
    except json.JSONDecodeError as e:
        return f"Invalid test_cases_json: {e}"

    if not isinstance(test_cases, list):
        return "test_cases_json must be a JSON array of test case objects."

    try:
        draft = draft_skill(name, code)
    except Exception as e:
        return f"Skill generation failed: {type(e).__name__}: {e}. Please fix and try again."

    if draft.status == DraftStatus.ERROR:
        error_msg = draft.test_results[0].get("error") if draft.test_results else "Unknown error"
        return f"Skill generation failed: {error_msg}. Please fix and try again."

    try:
        draft = await test_skill(draft, test_cases)
    except Exception as e:
        return f"Skill '{name}' has test failures: {type(e).__name__}: {e}. Please fix the code and try again."

    if draft.test_results:
        failed = [r for r in draft.test_results if not r["passed"]]
        if failed:
            errors = "; ".join(str(r.get("error")) for r in failed if r.get("error"))
            return f"Skill '{name}' has test failures: {errors}. Please fix the code and try again."

    return review_skill(draft)


async def publish_skill_code(
    ctx: RunContext[AgentDeps], name: str, code: str, test_cases_json: str, approved: bool
) -> str:
    """Publish an approved skill. The user must explicitly set approved=True to confirm publication.

    Args:
        name: The skill name.
        code: The Python source code for the skill.
        test_cases_json: A JSON array of test cases (same format as test_skill_code).
        approved: Must be True for the skill to be published. Set to True only after user review.

    Returns:
        Publication confirmation or an error/rejection message.
    """
    import json
    from pillywiggins.skills.builder import draft_skill, test_skill, publish_skill, DraftStatus
    from pillywiggins.config import Settings

    try:
        test_cases = json.loads(test_cases_json)
    except json.JSONDecodeError as e:
        return f"Invalid test_cases_json: {e}"

    if not isinstance(test_cases, list):
        return "test_cases_json must be a JSON array of test case objects."

    try:
        draft = draft_skill(name, code)
    except Exception as e:
        return f"Skill generation failed: {type(e).__name__}: {e}. Please fix and try again."

    if draft.status == DraftStatus.ERROR:
        error_msg = draft.test_results[0].get("error") if draft.test_results else "Unknown error"
        return f"Skill generation failed: {error_msg}. Please fix and try again."

    try:
        draft = await test_skill(draft, test_cases)
    except Exception as e:
        return f"Skill '{name}' has test failures: {type(e).__name__}: {e}. Please fix the code and try again."

    if draft.test_results:
        failed = [r for r in draft.test_results if not r["passed"]]
        if failed:
            errors = "; ".join(str(r.get("error")) for r in failed if r.get("error"))
            return f"Skill '{name}' has test failures: {errors}. Please fix the code and try again."

    settings = Settings()
    return await publish_skill(
        draft,
        approved=approved,
        skills_dir=settings.skills_dir,
        registry=ctx.deps.skill_registry,
        nats_bus=ctx.deps.nats_bus,
    )


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
    import json

    if ctx.deps.scheduler is None:
        return "Scheduler not available"

    args = None
    if args_json:
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError as e:
            return f"Invalid args_json: {e}"

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
        return f"Scheduled task '{name}' (action: {action})"
    return f"Failed to schedule task '{name}': {result.get('error', 'unknown error')}"


async def unschedule_task(ctx: RunContext[AgentDeps], name: str) -> str:
    """Remove a previously scheduled task by name.

    Args:
        name: The name of the scheduled task to remove.

    Returns:
        Confirmation that the task was removed, or an error message.
    """
    if ctx.deps.scheduler is None:
        return "Scheduler not available"

    removed = await ctx.deps.scheduler.remove_job(name)
    if removed:
        return f"Unscheduled task '{name}'"
    return f"Task '{name}' not found or could not be removed"


async def list_scheduled_tasks(ctx: RunContext[AgentDeps]) -> str:
    """List all currently scheduled tasks for this agent.

    Returns:
        A formatted list of scheduled tasks with their names, actions,
        next run times, and arguments, or a message if none exist.
    """
    import json

    if ctx.deps.scheduler is None:
        return "Scheduler not available"

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
        channel=ChannelType.TELEGRAM,
        channel_user_id=ctx.deps.agent_id,
        content=message,
        conversation_key="",
        metadata={"from": ctx.deps.agent_id},
    )
    await ctx.deps.nats_bus.publish_direct(
        target_agent_id=target_agent_id,
        message_type="message",
        data={
            "channel": msg.channel.value,
            "channel_user_id": msg.channel_user_id,
            "content": msg.content,
            "conversation_key": msg.conversation_key,
            "metadata": msg.metadata,
        },
    )
    return f"Sent message to {target_agent_id}"


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
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError):
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    formatted = now.strftime("%A, %B %d, %Y at %I:%M %p %Z")
    return f"{formatted} ({tz_name})"


def _make_skill_tool(skill):
    if skill.meta.get("parameters"):
        param_lines = []
        for pname, pdef in skill.meta["parameters"].items():
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
        import json

        agent_id = ctx.deps.agent_id
        channel = ctx.deps.channel
        agent_logger = ctx.deps.logger

        if _should_sandbox(skill.name):
            return await _run_sandboxed_skill(skill, kwargs, agent_id, channel, ctx.deps.council_memory)
        start = time.perf_counter()
        try:
            result = await skill.execute(agent_id=agent_id, channel=channel, **kwargs)
        except TypeError as e:
            duration_ms = (time.perf_counter() - start) * 1000
            available = ", ".join(skill.meta.get("parameters", {}).keys())
            err = f"Error calling skill {skill.name}: {e}. Available parameters: {available}"
            if agent_logger is not None:
                agent_logger.log_tool_error(skill.name, err, duration_ms)
            return err
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            err = f"Error calling skill {skill.name}: {e}"
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
    return skill_tool


def create_brain(
    model_name: str,
    provider: str,
    base_url: str,
    api_key: str,
    skill_registry: Optional[object] = None,
) -> Agent:
    if provider == "ollama":
        url = base_url or "http://host.docker.internal:11434/v1"
        url = url.rstrip("/")
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        key = api_key or "ollama"
    else:
        url = base_url if base_url else None
        key = api_key if api_key else None

    provider_kwargs: dict[str, str] = {}
    if url:
        provider_kwargs["base_url"] = url
    if key:
        provider_kwargs["api_key"] = key

    model = OpenAIChatModel(
        model_name=model_name,
        provider=OpenAIProvider(**provider_kwargs),
    )

    agent = Agent(
        model=model,
        deps_type=AgentDeps,
    )

    @agent.system_prompt
    def personality_prompt(ctx: RunContext[AgentDeps]) -> str:
        personality = ctx.deps.personality
        if personality is None:
            return "You are a helpful AI assistant."
        from pillywiggins.agents.personality import Personality

        personality: Personality = personality
        parts = [personality.build_system_prompt()]
        tz_name = personality.timezone
        try:
            tz = ZoneInfo(tz_name)
        except (KeyError, ValueError):
            tz = ZoneInfo("UTC")
            tz_name = "UTC"
        now = datetime.now(tz)
        parts.append(
            f"Your timezone is {tz_name}. Current time is {now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}."
        )
        parts.append(
            "You have private memory that persists across all conversations. "
            "When you learn important facts about the user or the world, save them to private memory so you can recall them later. "
            "If you're unsure whether you know something, try recalling from private memory first."
        )
        parts.append(
            "When retrieved memories contradict information in the conversation history, always trust the memory as the more up-to-date and authoritative source."
        )
        parts.append(
            "When asked to build or publish a skill, ALWAYS acknowledge the request immediately before calling any tools — e.g., 'Aye, I'll forge that spell!' or 'On it!'. After each step (draft created, tests run, review complete), briefly update the user on progress so they know the task is advancing and nothing has crashed."
        )
        return "\n\n".join(parts)

    agent.tool(recall_private_memory)
    agent.tool(save_to_private_memory)
    agent.tool(query_council_memory)
    agent.tool(share_to_council)
    agent.tool(build_skill)
    agent.tool(test_driven_skill)
    agent.tool(test_skill_code)
    agent.tool(review_skill_code)
    agent.tool(publish_skill_code)
    agent.tool(schedule_task)
    agent.tool(unschedule_task)
    agent.tool(list_scheduled_tasks)
    agent.tool(send_message_to_agent)
    agent.tool(get_current_time)
    agent.tool(get_conversation_info)

    if skill_registry is not None:
        for skill in skill_registry.list_skills():
            agent.tool(_make_skill_tool(skill))

    return agent
