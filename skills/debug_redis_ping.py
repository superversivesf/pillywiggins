"""Test Redis connectivity with SET/GET/DEL and report round-trip time."""

SKILL_META = {
    "name": "debug_redis_ping",
    "description": "Test Redis connectivity. SET a test key with TTL, GET it back, DEL it, and report round-trip time.",
    "tags": ["debug", "diagnostic", "redis", "cache"],
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

    try:
        import redis.asyncio as aioredis
    except ImportError:
        return {
            "success": False,
            "error": "redis.asyncio not available",
        }

    start = time.monotonic()
    try:
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await redis_client.ping()
        connect_time_ms = round((time.monotonic() - start) * 1000, 2)
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to connect to Redis: {e}",
            "redis_url": settings.redis_url,
        }

    test_key = f"pillywiggins:debug:redis_ping:{time.time()}"
    test_value = "pong"

    # SET with TTL
    set_start = time.monotonic()
    try:
        await redis_client.set(test_key, test_value, ex=60)
        set_time_ms = round((time.monotonic() - set_start) * 1000, 2)
    except Exception as e:
        await redis_client.close()
        return {
            "success": False,
            "error": f"SET failed: {e}",
            "connect_time_ms": connect_time_ms,
        }

    # GET
    get_start = time.monotonic()
    try:
        got_value = await redis_client.get(test_key)
        get_time_ms = round((time.monotonic() - get_start) * 1000, 2)
    except Exception as e:
        await redis_client.close()
        return {
            "success": False,
            "error": f"GET failed: {e}",
            "connect_time_ms": connect_time_ms,
            "set_time_ms": set_time_ms,
        }

    # DEL
    del_start = time.monotonic()
    try:
        await redis_client.delete(test_key)
        del_time_ms = round((time.monotonic() - del_start) * 1000, 2)
    except Exception as e:
        await redis_client.close()
        return {
            "success": False,
            "error": f"DEL failed: {e}",
            "connect_time_ms": connect_time_ms,
            "set_time_ms": set_time_ms,
            "get_time_ms": get_time_ms,
        }

    await redis_client.close()

    total_time_ms = round((time.monotonic() - start) * 1000, 2)

    return {
        "success": True,
        "connected": True,
        "redis_url": settings.redis_url,
        "connect_time_ms": connect_time_ms,
        "set_time_ms": set_time_ms,
        "get_time_ms": get_time_ms,
        "del_time_ms": del_time_ms,
        "total_time_ms": total_time_ms,
        "value_matches": got_value == test_value,
        "got_value": got_value,
    }
