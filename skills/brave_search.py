"""Search the web using Brave Search API. Privacy-focused with its own web index."""

SKILL_META = {
    "name": "brave_search",
    "description": "Search the web using Brave Search API. Returns top results with titles, URLs, snippets, and optional AI-generated summaries. Requires BRAVE_API_KEY environment variable.",
    "author": "system",
    "version": "1.0",
    "parameters": {
        "query": {"type": "string", "description": "Search query"},
        "count": {"type": "integer", "description": "Number of results (1-20, default 10)", "default": 10},
        "offset": {"type": "integer", "description": "Result offset for pagination (default 0)", "default": 0},
        "search_lang": {"type": "string", "description": "Language code (default 'en')", "default": "en"},
        "country": {"type": "string", "description": "Country code (default 'us')", "default": "us"},
        "freshness": {"type": "string", "description": "Time filter: 'all', 'day', 'week', 'month', 'year' (default 'all')", "default": "all"},
        "extra_snippets": {"type": "boolean", "description": "Include extra result snippets (default True)", "default": True},
    },
    "returns": "dict with results list (title, url, snippet, score) and query",
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

MAX_RETRIES = 2
BACKOFF_BASE = 1.0
BASE_URL = "https://api.search.brave.com/res/v1/web/search"


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
    count: int = 10,
    offset: int = 0,
    search_lang: str = "en",
    country: str = "us",
    freshness: str = "all",
    extra_snippets: bool = True,
) -> dict:
    api_key = os.environ.get("BRAVE_API_KEY", "")
    if not api_key:
        return {
            "results": [],
            "query": query,
            "error": (
                "Brave Search API key not configured. "
                "Set BRAVE_API_KEY in your .env file or environment. "
                "Get a free key at https://brave.com/search/api/"
            ),
        }

    params = {
        "q": query,
        "count": max(1, min(count, 20)),
        "offset": max(0, offset),
        "search_lang": search_lang,
        "country": country,
    }
    if freshness != "all":
        params["freshness"] = freshness
    if extra_snippets:
        params["extra_snippets"] = "true"

    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }

    data = None
    try:
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as session:
                    async with session.get(
                        BASE_URL, headers=headers, params=params
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            break
                        if resp.status == 429:
                            msg = "Brave Search rate limit exceeded (too many requests)."
                            if attempt >= MAX_RETRIES:
                                return {"results": [], "query": query, "error": msg}
                            raise ConnectionError(msg)
                        if resp.status == 401:
                            return {
                                "results": [],
                                "query": query,
                                "error": "Brave Search API key invalid or expired.",
                            }
                        if resp.status == 403:
                            return {
                                "results": [],
                                "query": query,
                                "error": "Brave Search API key quota exceeded or access denied.",
                            }
                        raise RuntimeError(f"Brave Search returned HTTP {resp.status}")
            except ConnectionError as exc:
                if attempt >= MAX_RETRIES:
                    return {
                        "results": [],
                        "query": query,
                        "error": f"Brave Search temporarily unavailable after {MAX_RETRIES} retries. {exc}",
                    }
                delay = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
            except aiohttp.ClientConnectorError:
                msg = "Cannot connect to Brave Search API. Network issue?"
                if attempt >= MAX_RETRIES:
                    return {"results": [], "query": query, "error": msg}
                delay = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
            except asyncio.TimeoutError:
                msg = "Request to Brave Search timed out after 15s"
                if attempt >= MAX_RETRIES:
                    return {"results": [], "query": query, "error": msg}
                delay = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
            except Exception as exc:
                msg = f"Brave Search failed unexpectedly: {_safe_str(exc)}"
                if attempt >= MAX_RETRIES:
                    return {"results": [], "query": query, "error": msg}
                delay = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
    except Exception as exc:
        return {"results": [], "query": query, "error": f"Brave Search failed unexpectedly: {_safe_str(exc)}"}

    if data is None:
        return {
            "results": [],
            "query": query,
            "error": "Brave Search returned no data after multiple attempts.",
        }

    raw_results = []
    if isinstance(data, dict):
        raw_results = data.get("web", {}).get("results", [])
        if not isinstance(raw_results, list):
            raw_results = []

    results = []
    for item in raw_results[:count]:
        try:
            entry = {
                "title": item.get("title", "") if isinstance(item, dict) else "",
                "url": item.get("url", "") if isinstance(item, dict) else "",
                "snippet": item.get("description", "") if isinstance(item, dict) else "",
                "score": item.get("score", 0) if isinstance(item, dict) else 0,
            }
            # Include extra_snippets if available
            extra = item.get("extra_snippets", []) if isinstance(item, dict) else []
            if extra and isinstance(extra, list):
                entry["extra_snippets"] = extra
            if entry["title"] or entry["url"]:
                results.append(entry)
        except (KeyError, TypeError, AttributeError):
            continue

    if not results:
        return {"results": [], "query": query, "error": "No results found for your query."}

    response = {"results": results, "query": query, "total_available": len(raw_results)}
    return response
