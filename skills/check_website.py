"""Check if a website is reachable and return status code and response time."""

SKILL_META = {
    "name": "check_website",
    "description": "Check if a URL is reachable and return the status code and response time in milliseconds.",
    "author": "system",
    "version": "1.0",
    "parameters": {
        "url": {"type": "string", "description": "The URL to check"},
        "timeout": {"type": "number", "description": "Timeout in seconds", "default": 10},
    },
    "returns": "dict with reachable, status_code, response_time_ms, body",
    "permissions": {
        "network": True,
        "subprocess": False,
        "file_write": False,
    },
}

import time

import aiohttp


async def run(url: str, timeout: float = 10) -> dict:
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
        return {"reachable": False, "status_code": None, "response_time_ms": None, "error": str(e)}