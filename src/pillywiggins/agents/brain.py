import os

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


def create_brain(
    personality_prompt: str,
    model_name: str,
    provider: str,
    base_url: str,
    api_key: str,
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
    return agent