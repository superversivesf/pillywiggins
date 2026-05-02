"""Write a test entry to council memory, then search and list to verify visibility."""

SKILL_META = {
    "name": "debug_council_memory",
    "description": "Test council memory read/write. Writes a test insight, searches for it, and lists recent entries.",
    "tags": ["debug", "diagnostic", "memory", "council"],
    "permissions": {
        "network": False,
        "subprocess": False,
        "file_write": False,
    },
}


async def run(**kwargs) -> dict:
    import time

    from pillywiggins.config import Settings

    settings = Settings()
    deps = kwargs.get("deps")

    if deps is not None and getattr(deps, "council_memory", None) is not None:
        council_memory = deps.council_memory
        agent_id = getattr(deps, "agent_id", settings.agent_id)
    else:
        from pillywiggins.memory.council import CouncilMemory

        agent_id = settings.agent_id
        council_memory = CouncilMemory(
            database_url=settings.database_url,
            agent_id=agent_id,
            embedding_dimension=settings.embedding_dimension,
        )
        await council_memory.connect()

    from pillywiggins.memory.embeddings import embed

    test_text = f"Debug council memory test at {time.time()}"

    embedding = await embed(
        text=test_text,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        provider=settings.llm_provider,
        model=settings.embedding_model,
        expected_dimension=settings.embedding_dimension,
    )

    if embedding is None:
        return {
            "success": False,
            "error": "Failed to generate embedding for council memory test.",
        }

    # Write test entry
    write_result = await council_memory.write_entry(
        content=test_text,
        tags=["general"],
        embedding=embedding,
        message_type="insight",
    )

    # Search for it
    search_results = await council_memory.search(query_embedding=embedding, limit=5)
    found_in_search = any(test_text in r.get("content", "") for r in search_results)

    # List recent entries
    list_results = await council_memory.list_entries(limit=10)
    found_in_list = any(test_text in r.get("content", "") for r in list_results)

    # Cleanup local connection if we instantiated it
    if deps is None or getattr(deps, "council_memory", None) is None:
        await council_memory.close()

    return {
        "success": write_result.get("success", False),
        "write_error": write_result.get("error"),
        "entry_id": write_result.get("id"),
        "agent_id": agent_id,
        "found_in_search": found_in_search,
        "search_results_count": len(search_results),
        "found_in_list": found_in_list,
        "list_entries_count": len(list_results),
    }
