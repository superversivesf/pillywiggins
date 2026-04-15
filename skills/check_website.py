"""Check if a website is reachable and return status code and response time."""

SKILL_META = {
    "name": "check_website",
    "description": "Fetch a URL and return its status code, response time, and page body content.",
    "author": "system",
    "version": "1.0",
    "parameters": {
        "url": {"type": "string", "description": "The URL to check"},
        "timeout": {"type": "number", "description": "Timeout in seconds", "default": 10},
    },
    "returns": "dict with reachable, status_code, response_time_ms, body. Blocks private/local network addresses.",
    "permissions": {
        "network": True,
        "subprocess": False,
        "file_write": False,
    },
}

import time

import aiohttp

from pillywiggins.skills.url_filter import is_safe_url


async def run(url: str, timeout: float = 10) -> dict:
    if not is_safe_url(url):
        return {"reachable": False, "status_code": None, "response_time_ms": None, "body": None, "error": "URL points to a private or local network address"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            start = time.monotonic()
            async with session.get(url) as resp:
                elapsed = (time.monotonic() - start) * 1000
                body = await resp.text()
                if len(body) > 50000:
                    body = body[:50000] + f"\n... [truncated, {len(body)} bytes total]"
                return {
                    "reachable": True,
                    "status_code": resp.status,
                    "response_time_ms": round(elapsed, 1),
                    "body": body,
                }
    except Exception as e:
        return {"reachable": False, "status_code": None, "response_time_ms": None, "body": None, "error": str(e)}