"""Search the web using local SearXNG metasearch engine."""

SKILL_META = {
    "name": "web_search",
    "description": "Search the web using a local SearXNG instance. Returns top results with titles, URLs, and snippets. Configure categories, engines, and max results via environment variables.",
    "author": "system",
    "version": "1.0",
    "parameters": {
        "query": {"type": "string", "description": "Search query"},
        "categories": {"type": "string", "description": "Comma-separated categories: general, news, images, videos, it, science (default: uses SEARXNG_CATEGORIES env var or 'general')", "default": ""},
        "max_results": {"type": "integer", "description": "Maximum number of results to return (default: uses SEARXNG_MAX_RESULTS env var or 5)", "default": 0},
        "engines": {"type": "string", "description": "Comma-separated engines to use. General: google, bing, duckduckgo, wikipedia. Academic: arxiv, google scholar, pubmed. Social: reddit. Images: bing images, google images. Video: youtube. Math/facts: wolframalpha. (default: all enabled engines)", "default": ""},
    },
    "returns": "dict with results list (title, url, snippet, engine) and query",
    "permissions": {
        "network": True,
        "subprocess": False,
        "file_write": False,
    },
}

import aiohttp


async def run(
    query: str,
    categories: str = "",
    max_results: int = 0,
    engines: str = "",
) -> dict:
    from pillywiggins.config import Settings

    settings = Settings()
    base_url = settings.searxng_url.rstrip("/")
    default_max = settings.searxng_max_results
    default_cats = settings.get_searxng_categories()

    limit = max_results if max_results > 0 else default_max
    cats = [c.strip() for c in categories.split(",") if c.strip()] if categories else default_cats

    params = {
        "q": query,
        "format": "json",
        "pageno": 1,
    }
    if cats:
        params["categories"] = ",".join(cats)
    if engines:
        params["engines"] = engines

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(f"{base_url}/search", params=params) as resp:
                if resp.status != 200:
                    return {
                        "results": [],
                        "query": query,
                        "error": f"SearXNG returned status {resp.status}",
                    }
                data = await resp.json()

    except aiohttp.ClientConnectorError:
        return {
            "results": [],
            "query": query,
            "error": f"Cannot connect to SearXNG at {base_url}. Is the searxng service running?",
        }
    except Exception as e:
        return {"results": [], "query": query, "error": str(e)}

    results = []
    for item in data.get("results", [])[:limit]:
        entry = {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
            "engine": item.get("engine", ""),
        }
        if entry["title"] or entry["url"]:
            results.append(entry)

    return {"results": results, "query": query, "total_available": len(data.get("results", []))}