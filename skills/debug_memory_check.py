"""Write a test entry to private memory, then search for it."""

SKILL_META = {
    "name": "debug_memory_check",
    "description": "Test private memory read/write. Saves a test entry, searches for it, and reports dimension and embedding model.",
    "tags": ["debug", "diagnostic", "memory", "private"],
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

    # Try to use injected deps first, otherwise instantiate from settings
    if deps is not None and getattr(deps, "private_memory", None) is not None:
        private_memory = deps.private_memory
        agent_id = getattr(deps, "agent_id", settings.agent_id)
    else:
        from pillywiggins.memory.private import PrivateMemory

        agent_id = settings.agent_id
        private_memory = PrivateMemory(
            database_url=settings.database_url,
            agent_id=agent_id,
            embedding_dimension=settings.embedding_dimension,
        )
        await private_memory.connect()

    # Generate a test embedding
    from pillywiggins.memory.embeddings import embed

    test_text = f"Debug memory test at {time.time()}"
    test_topic = "diagnostic"

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
            "error": "Failed to generate embedding for memory test.",
            "embedding_model": settings.embedding_model,
            "embedding_dimension": settings.embedding_dimension,
        }

    # Save test entry
    start = time.monotonic()
    await private_memory.save(content=test_text, embedding=embedding, metadata={"topic": test_topic})
    save_time_ms = round((time.monotonic() - start) * 1000, 2)

    # Search for it
    start = time.monotonic()
    results = await private_memory.search(query_embedding=embedding, limit=5)
    search_time_ms = round((time.monotonic() - start) * 1000, 2)

    found = any(test_text in r.get("content", "") for r in results)

    # If we instantiated locally, clean up
    if deps is None or getattr(deps, "private_memory", None) is None:
        await private_memory.close()

    return {
        "success": True,
        "agent_id": agent_id,
        "write_time_ms": save_time_ms,
        "search_time_ms": search_time_ms,
        "found_test_entry": found,
        "search_results": len(results),
        "embedding_model": settings.embedding_model,
        "embedding_dimension": settings.embedding_dimension,
    }
