import json
import logging
from datetime import datetime, timezone

import nats
from nats.js.api import StreamConfig

logger = logging.getLogger(__name__)

COUNCIL_STREAM = "COUNCIL"
BROADCAST_SUBJECT = "council.broadcast"
DIRECT_SUBJECT_PREFIX = "council.direct"


class NatsBus:
    def __init__(self, nats_url: str, agent_id: str):
        self._nats_url = nats_url
        self._agent_id = agent_id
        self._nc: nats.NATS | None = None
        self._js = None
        self._subs = []

    async def connect(self):
        try:
            self._nc = await nats.connect(servers=[self._nats_url])
            self._js = self._nc.jetstream()
            try:
                await self._js.add_stream(
                    name=COUNCIL_STREAM,
                    subjects=[BROADCAST_SUBJECT, f"{DIRECT_SUBJECT_PREFIX}.>"],
                    config=StreamConfig(
                        name=COUNCIL_STREAM,
                        subjects=[BROADCAST_SUBJECT, f"{DIRECT_SUBJECT_PREFIX}.>"],
                    ),
                )
            except Exception:
                pass
            logger.info("NATS connected for agent %s", self._agent_id)
        except Exception:
            logger.warning("Failed to connect to NATS at %s, continuing without messaging", self._nats_url, exc_info=True)
            self._nc = None
            self._js = None

    def _make_payload(self, message_type: str, data: dict) -> bytes:
        payload = {
            "type": message_type,
            "from": self._agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        return json.dumps(payload).encode()

    def _parse_payload(self, msg) -> tuple[str, dict]:
        raw = msg.data
        payload = json.loads(raw)
        return payload["type"], payload["data"]

    async def publish_broadcast(self, message_type: str, data: dict):
        if self._js is None:
            logger.warning("NATS not connected, skipping broadcast publish for %s", message_type)
            return
        payload = self._make_payload(message_type, data)
        await self._js.publish(BROADCAST_SUBJECT, payload)

    async def publish_direct(self, target_agent_id: str, message_type: str, data: dict):
        if self._js is None:
            logger.warning("NATS not connected, skipping direct publish for %s", message_type)
            return
        subject = f"{DIRECT_SUBJECT_PREFIX}.{target_agent_id}"
        payload = self._make_payload(message_type, data)
        await self._js.publish(subject, payload)

    async def subscribe_broadcast(self, handler):
        if self._js is None:
            logger.warning("NATS not connected, skipping broadcast subscribe")
            return

        async def _cb(msg):
            msg_type, data = self._parse_payload(msg)
            await handler(msg_type, data)

        durable = f"pillywiggins-{self._agent_id}-broadcast"
        sub = await self._js.subscribe(
            subject=BROADCAST_SUBJECT,
            queue=durable,
            durable=durable,
            cb=_cb,
        )
        self._subs.append(sub)

    async def subscribe_direct(self, handler):
        if self._js is None:
            logger.warning("NATS not connected, skipping direct subscribe")
            return

        async def _cb(msg):
            msg_type, data = self._parse_payload(msg)
            await handler(msg_type, data)

        subject = f"{DIRECT_SUBJECT_PREFIX}.{self._agent_id}"
        durable = f"pillywiggins-{self._agent_id}-direct"
        sub = await self._js.subscribe(
            subject=subject,
            queue=durable,
            durable=durable,
            cb=_cb,
        )
        self._subs.append(sub)

    async def close(self):
        if self._nc is not None:
            try:
                await self._nc.drain()
                await self._nc.close()
            except Exception:
                logger.warning("Error closing NATS connection", exc_info=True)
            self._nc = None
            self._js = None
            self._subs.clear()