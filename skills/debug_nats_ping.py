"""Check NATS connection status and send a broadcast test message."""

SKILL_META = {
    "name": "debug_nats_ping",
    "description": "Test NATS connection. Checks is_connected, publishes a broadcast test message, and reports status.",
    "tags": ["debug", "diagnostic", "nats", "messaging"],
    "permissions": {
        "network": False,
        "subprocess": False,
        "file_write": False,
    },
}


async def run(**kwargs) -> dict:
    import time

    deps = kwargs.get("deps")

    if deps is not None and getattr(deps, "nats_bus", None) is not None:
        nats_bus = deps.nats_bus
        agent_id = getattr(deps, "agent_id", "unknown")
    else:
        from pillywiggins.config import Settings
        from pillywiggins.messaging.nats_bus import NatsBus

        settings = Settings()
        agent_id = settings.agent_id
        nats_bus = NatsBus(
            nats_url=settings.nats_url,
            agent_id=agent_id,
        )
        try:
            await nats_bus.connect()
        except Exception as e:
            return {
                "success": False,
                "connected": False,
                "error": f"Failed to connect to NATS: {e}",
            }

    connected = nats_bus.is_connected
    publish_error = None

    if connected:
        try:
            await nats_bus.publish_broadcast(
                "debug_ping",
                {
                    "message": "NATS broadcast test from debug agent",
                    "timestamp": time.time(),
                },
            )
        except Exception as e:
            publish_error = str(e)
    else:
        publish_error = "NATS not connected, skipping broadcast"

    return {
        "success": connected and publish_error is None,
        "connected": connected,
        "agent_id": agent_id,
        "broadcast_published": connected and publish_error is None,
        "publish_error": publish_error,
    }
