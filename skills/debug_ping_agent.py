"""Send a NATS direct ping to another agent and wait up to 10s for a reply."""

SKILL_META = {
    "name": "debug_ping_agent",
    "description": "Send a NATS direct message to a target agent_id asking for a ping. Waits up to 10s for reply and reports round-trip time or timeout.",
    "tags": ["debug", "diagnostic", "nats", "messaging"],
    "permissions": {
        "network": False,
        "subprocess": False,
        "file_write": False,
    },
}


async def run(target_agent_id: str = "", **kwargs) -> dict:
    import asyncio
    import json
    import time

    from pillywiggins.config import Settings

    if not target_agent_id:
        return {
            "success": False,
            "error": "Missing required parameter: target_agent_id",
        }

    settings = Settings()
    deps = kwargs.get("deps")

    if deps is not None and getattr(deps, "nats_bus", None) is not None:
        nats_bus = deps.nats_bus
        agent_id = getattr(deps, "agent_id", settings.agent_id)
    else:
        from pillywiggins.messaging.nats_bus import NatsBus

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
                "error": f"Failed to connect to NATS: {e}",
            }

    if not nats_bus.is_connected:
        return {
            "success": False,
            "error": "NATS not connected",
        }

    # Try NATS core request-reply for a round-trip measurement
    # Fallback to JetStream direct publish if core is unavailable
    reply = None
    rtt_ms = None
    error = None

    try:
        nc = nats_bus._nc
        if nc is not None and hasattr(nc, "request"):
            subject = f"council.direct.{target_agent_id}"
            payload = json.dumps(
                {
                    "type": "ping",
                    "from": agent_id,
                    "timestamp": time.time(),
                    "data": {"message": "ping"},
                }
            ).encode()

            start = time.monotonic()
            msg = await nc.request(subject, payload, timeout=10)
            rtt_ms = round((time.monotonic() - start) * 1000, 2)
            reply_data = json.loads(msg.data.decode()) if msg.data else {}
            reply = {
                "type": reply_data.get("type"),
                "from": reply_data.get("from"),
                "data": reply_data.get("data"),
            }
        else:
            # Fallback: publish via JetStream and report publish-only
            await nats_bus.publish_direct(
                target_agent_id=target_agent_id,
                message_type="ping",
                data={"message": "ping", "from": agent_id},
            )
            reply = {"note": "Published via JetStream. No request-reply available."}
    except asyncio.TimeoutError:
        error = "Timeout waiting for reply (>10s)"
        rtt_ms = None
    except Exception as e:
        error = str(e)

    return {
        "success": error is None,
        "from_agent": agent_id,
        "to_agent": target_agent_id,
        "round_trip_ms": rtt_ms,
        "reply": reply,
        "error": error,
    }
