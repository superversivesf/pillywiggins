import asyncio
import json
import logging
from datetime import datetime, timezone

import nats
from nats.js.api import ConsumerConfig, StreamConfig

logger = logging.getLogger(__name__)

COUNCIL_STREAM = "pillywiggins"
OLD_COUNCIL_STREAM = "COUNCIL"
BROADCAST_SUBJECT = "council.broadcast"
DIRECT_SUBJECT_PREFIX = "council.direct"

DEFAULT_CONNECT_TIMEOUT = 5  # seconds
DEFAULT_RECONNECT_ATTEMPTS = 5
DEFAULT_RETRY_DELAY = 1.0  # seconds (initial)
DEFAULT_RETRY_MAX_DELAY = 60.0  # seconds


class NatsConnectError(Exception):
    """Raised when NATS connection fails after all retry attempts."""

    def __init__(self, url: str, attempts: int, last_error: Exception | None = None):
        self.url = url
        self.attempts = attempts
        self.last_error = last_error
        msg = f"Failed to connect to NATS at {url} after {attempts} attempts"
        if last_error:
            msg += f": {last_error}"
        super().__init__(msg)


class NatsBus:
    def __init__(
        self,
        nats_url: str,
        agent_id: str,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        reconnect_attempts: int = DEFAULT_RECONNECT_ATTEMPTS,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        retry_max_delay: float = DEFAULT_RETRY_MAX_DELAY,
    ):
        self._nats_url = nats_url
        self._agent_id = agent_id
        self._connect_timeout = connect_timeout
        self._reconnect_attempts = reconnect_attempts
        self._retry_delay = retry_delay
        self._retry_max_delay = retry_max_delay
        self._nc: nats.NATS | None = None
        self._js: nats.js.JetStreamContext | None = None
        self._subs = []
        self._connected = False
        self._broadcast_handler = None
        self._direct_handler = None
        self._monitor_task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        """Check whether the NATS connection is currently active."""
        if self._nc is None:
            return False
        return self._nc.is_connected

    async def connect(self) -> None:
        """Connect to NATS with retry logic and exponential backoff.

        Raises NatsConnectError if all retry attempts are exhausted.
        The caller can catch this to decide whether to continue
        without messaging or abort.
        """
        last_error: Exception | None = None
        for attempt in range(1, self._reconnect_attempts + 1):
            try:
                logger.info(
                    "NATS connect attempt %d/%d for %s at %s",
                    attempt, self._reconnect_attempts, self._agent_id, self._nats_url,
                )
                nc = await nats.connect(
                    servers=[self._nats_url],
                    connect_timeout=self._connect_timeout,
                )
                js = nc.jetstream()
                await self._ensure_stream(js)
                self._nc = nc
                self._js = js
                self._connected = True
                if self._monitor_task is None or self._monitor_task.done():
                    self._monitor_task = asyncio.create_task(self._monitor())
                logger.info("NATS connected for agent %s at %s", self._agent_id, self._nats_url)
                return
            except Exception as e:
                last_error = e
                self._connected = False
                self._nc = None
                self._js = None
                if attempt < self._reconnect_attempts:
                    delay = min(self._retry_delay * (2 ** (attempt - 1)), self._retry_max_delay)
                    logger.warning(
                        "NATS connect attempt %d/%d failed for %s: %s — retrying in %.1fs",
                        attempt, self._reconnect_attempts, self._agent_id, e, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "NATS connect failed after %d attempts for %s: %s",
                        self._reconnect_attempts, self._agent_id, e, exc_info=True,
                    )

        raise NatsConnectError(self._nats_url, self._reconnect_attempts, last_error)

    async def _ensure_stream(self, js) -> None:
        """Ensure the pillywiggins JetStream stream exists, migrating from COUNCIL if needed."""
        # Check if the new stream already exists
        try:
            await js.stream_info(COUNCIL_STREAM)
            logger.info("JetStream stream %s already exists (OK)", COUNCIL_STREAM)
            return
        except nats.js.errors.NotFoundError:
            pass
        except Exception as e:
            logger.error("JetStream stream_info failed for %s: %s", self._agent_id, e, exc_info=True)
            return

        # If new stream doesn't exist, check for old "COUNCIL" stream and migrate subjects
        try:
            old_info = await js.stream_info(OLD_COUNCIL_STREAM)
            logger.info(
                "Found old stream '%s', creating '%s' with same subjects for %s",
                OLD_COUNCIL_STREAM, COUNCIL_STREAM, self._agent_id,
            )
            subjects = old_info.config.subjects if hasattr(old_info, "config") else [BROADCAST_SUBJECT, f"{DIRECT_SUBJECT_PREFIX}.>"]
        except nats.js.errors.NotFoundError:
            subjects = [BROADCAST_SUBJECT, f"{DIRECT_SUBJECT_PREFIX}.>"]
        except Exception as e:
            logger.error("JetStream old stream check failed for %s: %s", self._agent_id, e, exc_info=True)
            subjects = [BROADCAST_SUBJECT, f"{DIRECT_SUBJECT_PREFIX}.>"]

        # Create the new stream
        try:
            await js.add_stream(
                config=StreamConfig(
                    name=COUNCIL_STREAM,
                    subjects=subjects,
                ),
            )
            logger.info("JetStream stream %s created for %s", COUNCIL_STREAM, self._agent_id)
        except Exception as e:
            logger.error("JetStream add_stream failed for %s: %s", self._agent_id, e, exc_info=True)

    async def connect_or_log(self) -> bool:
        """Try to connect to NATS, logging a warning on failure.

        Returns True if connected, False otherwise. Does NOT raise.
        Use this from agent startup where you want graceful degradation.
        """
        try:
            await self.connect()
            return True
        except NatsConnectError as e:
            logger.warning(
                "NATS unavailable for %s — continuing without messaging: %s",
                self._agent_id, e,
            )
            return False

    async def _monitor(self) -> None:
        """Background health monitor that reconnects + re-subscribes on outage."""
        while True:
            try:
                await asyncio.sleep(10.0)
            except asyncio.CancelledError:
                return
            if not self.is_connected:
                logger.warning("NATS connection dropped for %s, attempting reconnect", self._agent_id)
                try:
                    await self.reconnect()
                    if self._broadcast_handler is not None:
                        await self.subscribe_broadcast(self._broadcast_handler)
                    if self._direct_handler is not None:
                        await self.subscribe_direct(self._direct_handler)
                    logger.info("NATS reconnected and re-subscribed for %s", self._agent_id)
                except Exception:
                    logger.warning("NATS reconnect failed for %s", self._agent_id, exc_info=True)

    async def reconnect(self) -> None:
        """Close existing connection (if any) and reconnect.

        Raises NatsConnectError if all retry attempts fail.
        """
        await self.close()
        await self.connect()

    def _make_payload(self, message_type: str, data: dict) -> bytes:
        payload = {
            "type": message_type,
            "from": self._agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        return json.dumps(payload, default=str).encode()

    def _parse_payload(self, msg) -> tuple[str, dict, str, str]:
        raw = msg.data
        payload = json.loads(raw)
        return (
            payload["type"],
            payload["data"],
            payload.get("from", ""),
            payload.get("timestamp", ""),
        )

    async def publish_broadcast(self, message_type: str, data: dict):
        if self._js is None:
            logger.warning("NATS not connected, skipping broadcast publish for %s", message_type)
            return
        payload = self._make_payload(message_type, data)
        try:
            ack = await self._js.publish(BROADCAST_SUBJECT, payload)
            logger.info(
                "Broadcast %s sent from %s — ack: stream=%s seq=%s",
                message_type,
                self._agent_id,
                ack.stream if ack else "(none)",
                ack.seq if ack else "(none)",
            )
        except Exception:
            logger.exception("Failed to publish broadcast %s from %s", message_type, self._agent_id)

    async def publish_direct(self, target_agent_id: str, message_type: str, data: dict):
        if self._js is None:
            logger.warning("NATS not connected, skipping direct publish for %s to %s", message_type, target_agent_id)
            return
        subject = f"{DIRECT_SUBJECT_PREFIX}.{target_agent_id}"
        payload = self._make_payload(message_type, data)
        try:
            ack = await self._js.publish(subject, payload)
            logger.info(
                "Direct %s sent from %s to %s on %s — ack: stream=%s seq=%s",
                message_type,
                self._agent_id,
                target_agent_id,
                subject,
                ack.stream if ack else "(none)",
                ack.seq if ack else "(none)",
            )
        except Exception:
            logger.exception("Failed to publish direct %s from %s to %s on %s", message_type, self._agent_id, target_agent_id, subject)

    async def subscribe_broadcast(self, handler):
        self._broadcast_handler = handler
        if self._js is None:
            logger.warning("NATS not connected, skipping broadcast subscribe")
            return

        async def _cb(msg):
            try:
                logger.debug("Broadcast message received on %s for %s", msg.subject, self._agent_id)
                msg_type, data, from_agent, timestamp = self._parse_payload(msg)
                logger.info("Broadcast %s received by %s from %s", msg_type, self._agent_id, from_agent or "?")
                await handler(msg_type, data, from_agent, timestamp)
                await msg.ack()
                logger.debug("Broadcast message acked by %s", self._agent_id)
            except Exception:
                logger.exception("Error handling broadcast message for %s", self._agent_id)
                try:
                    await msg.nak()
                except Exception:
                    pass

        durable = f"pillywiggins-{self._agent_id}-broadcast"
        sub = await self._js.subscribe(
            subject=BROADCAST_SUBJECT,
            queue=durable,
            durable=durable,
            cb=_cb,
            config=ConsumerConfig(max_deliver=3),
        )
        self._subs.append(sub)
        logger.info("Broadcast subscription created for %s (durable=%s)", self._agent_id, durable)

    async def subscribe_direct(self, handler):
        self._direct_handler = handler
        if self._js is None:
            logger.warning("NATS not connected, skipping direct subscribe")
            return

        async def _cb(msg):
            try:
                logger.debug("Direct message received on %s for %s", msg.subject, self._agent_id)
                msg_type, data, from_agent, timestamp = self._parse_payload(msg)
                logger.info("Direct %s received by %s from %s", msg_type, self._agent_id, from_agent or "?")
                await handler(msg_type, data, from_agent, timestamp)
                await msg.ack()
                logger.debug("Direct message acked by %s", self._agent_id)
            except Exception:
                logger.exception("Error handling direct message for %s", self._agent_id)
                try:
                    await msg.nak()
                except Exception:
                    pass

        subject = f"{DIRECT_SUBJECT_PREFIX}.{self._agent_id}"
        durable = f"pillywiggins-{self._agent_id}-direct"
        sub = await self._js.subscribe(
            subject=subject,
            queue=durable,
            durable=durable,
            cb=_cb,
            config=ConsumerConfig(max_deliver=3),
        )
        self._subs.append(sub)
        logger.info("Direct subscription created for %s on %s (durable=%s)", self._agent_id, subject, durable)

    async def close(self):
        self._connected = False
        if self._monitor_task is not None and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        if self._nc is not None:
            try:
                for sub in self._subs:
                    try:
                        await sub.unsubscribe()
                    except Exception:
                        pass
                self._subs.clear()
                await self._nc.drain()
                await self._nc.close()
            except Exception:
                logger.warning("Error closing NATS connection", exc_info=True)
            self._nc = None
            self._js = None
