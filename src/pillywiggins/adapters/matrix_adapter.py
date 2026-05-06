"""Matrix adapter using matrix-nio."""
import asyncio
import logging
import signal
from datetime import datetime, timezone

from nio import AsyncClient, RoomMessageText, SyncResponse

from pillywiggins.adapters.base import BaseAdapter
from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.config import Settings
from pillywiggins.messaging.unified import ChannelType, UnifiedMessage

logger = logging.getLogger(__name__)


class MatrixAdapter(BaseAdapter):
    command_prefix = "!"

    def __init__(self, agent: PillywigginAgent, homeserver: str, user_id: str, access_token: str, settings: Settings):
        super().__init__(agent, settings)
        self.homeserver = homeserver
        self.user_id = user_id
        self.access_token = access_token
        self.settings = settings
        self._client: AsyncClient | None = None
        self._shutdown_event = asyncio.Event()

    async def connect(self) -> None:
        self._client = AsyncClient(self.homeserver, self.user_id)
        self._client.access_token = self.access_token
        # Verify token by doing a quick sync
        resp = await self._client.sync(timeout_ms=30000, full_state=True)
        if isinstance(resp, SyncResponse):
            logger.info("Matrix client connected as %s on %s", self.user_id, self.homeserver)
        else:
            logger.warning("Matrix sync returned non-success: %s", resp)

    async def listen(self) -> None:
        """Listen for Matrix messages via sync loop."""
        if self._client is None:
            raise RuntimeError("Matrix client not connected. Call connect() first.")

        # Set up signal handlers for graceful shutdown
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                asyncio.get_running_loop().add_signal_handler(sig, self._shutdown_event.set)
            except (NotImplementedError, ValueError):
                pass

        logger.info("Matrix adapter listening for messages...")
        while not self._shutdown_event.is_set():
            try:
                resp = await self._client.sync(timeout_ms=30000)
                if isinstance(resp, SyncResponse):
                    for room_id, room_info in resp.rooms.join.items():
                        for event in room_info.timeline.events:
                            if isinstance(event, RoomMessageText):
                                # Skip our own messages
                                if event.sender == self.user_id:
                                    continue
                                msg = self.normalize({
                                    "room_id": room_id,
                                    "sender": event.sender,
                                    "body": event.body,
                                    "event_id": event.event_id,
                                    "timestamp": event.server_timestamp,
                                })
                                asyncio.create_task(self._handle_message(msg, room_id))
            except Exception:
                logger.exception("Matrix sync error")
                await asyncio.sleep(5)

    async def _handle_message(self, msg: UnifiedMessage, room_id: str) -> None:
        sender = msg.metadata.get("sender", "")
        if not self._is_authorized(sender):
            logger.info("Unauthorized Matrix user: %s", sender)
            return

        if not self.agent.should_process_message(msg):
            return

        # Commands
        text = msg.content.strip()
        if text.startswith(self.command_prefix):
            response = await self.dispatch_command(text, room_id)
            if response:
                await self.send(room_id, response)
            return

        # Normal message — route to agent
        try:
            reply = await self.agent.handle_message(msg)
            if reply:
                await self.send(room_id, reply)
        except Exception:
            logger.exception("Error handling Matrix message")
            await self.send(room_id, "Sorry, something went wrong processing your message.")

    async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
        if self._client is None:
            logger.warning("Matrix client not connected, cannot send")
            return
        try:
            await self._client.room_send(
                room_id=channel_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": content,
                    "format": "org.matrix.custom.html",
                    "formatted_body": content,
                },
            )
        except Exception:
            logger.exception("Failed to send Matrix message to %s", channel_id)

    def normalize(self, raw_message: dict) -> UnifiedMessage:
        return UnifiedMessage(
            channel=ChannelType.MATRIX,
            channel_user_id=raw_message["sender"],
            content=raw_message["body"],
            conversation_key=raw_message["room_id"],
            timestamp=datetime.now(timezone.utc),
            metadata={
                "sender": raw_message["sender"],
                "event_id": raw_message.get("event_id"),
                "server_timestamp": raw_message.get("timestamp"),
                "is_group": True,
                "is_bot": raw_message["sender"].startswith("@bot") or raw_message["sender"].endswith(":bot"),
            },
        )