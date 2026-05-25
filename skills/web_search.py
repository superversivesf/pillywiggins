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
        "engines": {"type": "string", "description": "Comma-separated engines to use. General: google, bing, duckduckgo, wikipedia. Academic: arxiv, google scholar, pubmed. Social: reddit. Images: bing images, google images. Video: youtube. Math/facts: wolframalpha. (default: all enabled engines, excluding known unreliable ones unless overridden here)", "default": ""},
    },
    "returns": "dict with results list (title, url, snippet, engine) and query",
    "permissions": {
        "network": True,
        "subprocess": False,
        "file_write": False,
    },
}

import asyncio
import os
import random

import aiohttp

MAX_RETRIES = 3
BACKOFF_BASE = 2.0
RETRYABLE_HTTP_STATUSES = frozenset({429, 502, 503, 504})
SAFE_DEFAULT_ENGINES = "google,bing,duckduckgo,wikipedia"


def _safe_str(exc: Exception) -> str:
    try:
        return str(exc)
    except Exception:
        try:
            return repr(exc)
        except Exception:
            return "Unknown error occurred."


async def run(
    query: str,
    categories: str = "",
    max_results: int = 0,
    engines: str = "",
) -> dict:
    base_url = os.environ.get("SEARXNG_URL", "http://searxng:8080").rstrip("/")
    default_max = int(os.environ.get("SEARXNG_MAX_RESULTS", "5"))
    default_cats = os.environ.get("SEARXNG_CATEGORIES", "general")

    if "," in default_cats:
        default_cats = [c.strip() for c in default_cats.split(",") if c.strip()]
    else:
        default_cats = [default_cats.strip()] if default_cats.strip() else ["general"]

    limit = max_results if max_results > 0 else default_max
    cats = [c.strip() for c in categories.split(",") if c.strip()] if categories else default_cats

    # Use safe default engines if none specified, avoiding known unreliable ones.
    # Users can override via the `engines` parameter or the SEARXNG_ENGINES env var.
    resolved_engines = engines.strip() if engines else os.environ.get("SEARXNG_ENGINES", SAFE_DEFAULT_ENGINES).strip()

    params = {
        "q": query,
        "format": "json",
        "pageno": 1,
    }
    if cats:
        params["categories"] = ",".join(cats)
    if resolved_engines:
        params["engines"] = resolved_engines

    data = None

    try:
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                    async with session.get(f"{base_url}/search", params=params) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            break
                        if resp.status in RETRYABLE_HTTP_STATUSES:
                            raise ConnectionError(f"SearXNG returned HTTP {resp.status}")
                        raise RuntimeError(f"SearXNG returned status {resp.status}")
            except ConnectionError as exc:
                if attempt >= MAX_RETRIES:
                    return {
                        "results": [],
                        "query": query,
                        "error": f"Search service is temporarily unavailable after {MAX_RETRIES} retries. {exc}",
                    }
                delay = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
            except aiohttp.ClientConnectorError:
                msg = f"Cannot connect to SearXNG at {base_url}. Is the searxng service running?"
                if attempt >= MAX_RETRIES:
                    return {"results": [], "query": query, "error": msg}
                delay = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
            except asyncio.TimeoutError:
                msg = "Request to SearXNG timed out after 15s"
                if attempt >= MAX_RETRIES:
                    return {"results": [], "query": query, "error": msg}
                delay = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
            except Exception as exc:
                msg = f"Search failed unexpectedly: {_safe_str(exc)}"
                if attempt >= MAX_RETRIES:
                    return {"results": [], "query": query, "error": msg}
                delay = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
    except Exception as exc:
        return {"results": [], "query": query, "error": f"Search failed unexpectedly: {_safe_str(exc)}"}

    if data is None:
        return {
            "results": [],
            "query": query,
            "error": "Search service returned no data after multiple attempts.",
        }

    # Parse response with defensive error handling so one bad engine result
    # (e.g. WolframAlpha KeyError) doesn't crash the whole search.
    raw_results = []
    if isinstance(data, dict):
        raw_results = data.get("results", [])
        if not isinstance(raw_results, list):
            raw_results = []

    results = []
    for item in raw_results[:limit]:
        try:
            entry = {
                "title": item.get("title", "") if isinstance(item, dict) else "",
                "url": item.get("url", "") if isinstance(item, dict) else "",
                "snippet": item.get("content", "") if isinstance(item, dict) else "",
                "engine": item.get("engine", "") if isinstance(item, dict) else "",
            }
            if entry["title"] or entry["url"]:
                results.append(entry)
        except (KeyError, TypeError, AttributeError):
            # Gracefully skip malformed items (e.g. from engine crashes)
            continue

    unresponsive = []
    if isinstance(data, dict):
        unresponsive = data.get("unresponsive_engines", [])
        if not isinstance(unresponsive, list):
            unresponsive = []

    if not results:
        friendly = "No results found for your query."
        if unresponsive:
            friendly += (
                f" Some search engines were unresponsive: {', '.join(str(e) for e in unresponsive)}."
            )
        return {"results": [], "query": query, "error": friendly}

    response = {"results": results, "query": query, "total_available": len(raw_results)}
    if unresponsive:
        response["unresponsive_engines"] = unresponsive

    return response
