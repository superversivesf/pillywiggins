import os
from typing import Optional

from pydantic_ai import Agent, RunContext

from pillywiggins.agents.deps import AgentDeps


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
    )
    if embedding is None:
        return "Could not generate embedding — memory not saved."
    await ctx.deps.private_memory.save(content, embedding)
    return f"Remembered: {content}"


def _make_skill_tool(skill):
    params = skill.meta.get("parameters", {})
    if params:
        import inspect
        sig_params = {}
        annotations = {}
        defaults = {}
        for pname, pdef in params.items():
            ptype = {"string": str, "integer": int, "number": float, "boolean": bool}.get(pdef.get("type", "string"), str)
            annotations[pname] = ptype
            if "default" in pdef:
                defaults[pname] = pdef["default"]
            else:
                sig_params[pname] = inspect.Parameter(pname, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=ptype)
        for pname, default in defaults.items():
            sig_params[pname] = inspect.Parameter(pname, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=default, annotation=annotations[pname])

        async def skill_tool(ctx: RunContext[AgentDeps], **kwargs) -> str:
            import json
            try:
                result = await skill.execute(**kwargs)
            except TypeError as e:
                return f"Error calling skill {skill.name}: {e}. Available parameters: {', '.join(params.keys())}"
            if isinstance(result, str):
                return result
            return json.dumps(result)

        skill_tool.__signature__ = inspect.Signature(parameters=sig_params)
    else:
        async def skill_tool(ctx: RunContext[AgentDeps]) -> str:
            import json
            try:
                result = await skill.execute()
            except TypeError as e:
                return f"Error calling skill {skill.name}: {e}"
            if isinstance(result, str):
                return result
            return json.dumps(result)

    param_docs = "\n".join(
        f"    {k}: {v.get('description', v.get('type', 'any'))}"
        for k, v in params.items()
    ) if params else ""
    perm_list = [k for k, v in skill.permissions.items() if v]
    perm_str = f" Permissions: {', '.join(perm_list)}." if perm_list else ""
    doc = skill.description
    if param_docs:
        doc += f"\n\nArgs:\n{param_docs}"
    doc += perm_str
    skill_tool.__name__ = skill.name
    skill_tool.__doc__ = doc
    return skill_tool


def create_brain(
    personality_prompt: str,
    model_name: str,
    provider: str,
    base_url: str,
    api_key: str,
    skill_registry: Optional[object] = None,
) -> Agent:
    if provider == "ollama":
        os.environ["OLLAMA_BASE_URL"] = base_url or "http://localhost:11434"
        if api_key:
            os.environ["OLLAMA_API_KEY"] = api_key
        model = f"ollama:{model_name}"
    else:
        model = f"openai:{model_name}"
        os.environ["OPENAI_API_KEY"] = api_key
        if base_url:
            os.environ["OPENAI_BASE_URL"] = base_url

    agent = Agent(
        model=model,
        system_prompt=personality_prompt,
        deps_type=AgentDeps,
    )
    agent.tool(recall_private_memory)
    agent.tool(save_to_private_memory)

    if skill_registry is not None:
        for skill in skill_registry.list_skills():
            agent.tool(_make_skill_tool(skill))

    return agent