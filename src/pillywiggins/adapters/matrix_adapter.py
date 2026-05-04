"""Matrix adapter using matrix-nio."""
import asyncio
import logging
import signal
from datetime import datetime, timezone

from nio import AsyncClient, RoomMessageText, SyncResponse

from pillywiggins.adapters.base import BaseAdapter
from pillywiggins.adapters.models import list_models
from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.config import Settings
from pillywiggins.messaging.unified import ChannelType, UnifiedMessage

logger = logging.getLogger(__name__)

HELP_TEXT = """**Pillywiggins Commands**
!help — Show this message
!status — Show agent status (model, context size, etc.)
!models — List available LLM models
!model <name> — Switch to a different model
!skills — List loaded skills
!compact — Summarize conversation history to free context
!reset — Clear conversation history"""


class MatrixAdapter(BaseAdapter):
    def __init__(self, agent: PillywigginAgent, homeserver: str, user_id: str, access_token: str, settings: Settings):
        super().__init__(agent)
        self.homeserver = homeserver
        self.user_id = user_id
        self.access_token = access_token
        self.settings = settings
        self._allowed_user_ids = settings.get_allowed_user_ids()
        self._allow_all = settings.allowed_user_ids.strip().lower() == "all"
        self._client: AsyncClient | None = None
        self._bot_chat_counts: dict[str, int] = {}
        self._shutdown_event = asyncio.Event()

    def _is_authorized(self, sender: str) -> bool:
        if self._allow_all:
            return True
        # Matrix user IDs are strings like @user:server
        # ALLOWED_USER_IDS expects numeric IDs — for Matrix we compare the full MXID
        allowed = {str(uid) for uid in self._allowed_user_ids}
        return sender in allowed

    def _should_respond_to_bot(self, room_id: str, is_bot: bool) -> bool:
        if not is_bot:
            self._bot_chat_counts[room_id] = 0
            return True
        limit = getattr(self.agent.personality, "bot_chat_limit", 3)
        if not isinstance(limit, int):
            limit = 3
        if limit < 0:
            return True
        if limit == 0:
            return False
        count = self._bot_chat_counts.get(room_id, 0)
        if count >= limit:
            logger.info("Bot chat limit reached (%d) in room %s, staying quiet", limit, room_id)
            return False
        return True

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

        # Slash commands
        text = msg.content.strip()
        if text.startswith("!"):
            response = await self._handle_command(text, room_id)
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

    async def _handle_command(self, text: str, room_id: str) -> str | None:
        parts = text[1:].split(None, 1)
        if not parts:
            return None
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("help", "h"):
            return HELP_TEXT

        if cmd == "status":
            status = self.agent.get_status()
            return (
                f"**Status**\n"
                f"Model: `{status['model_name']}`\n"
                f"Messages: {status['message_count']}\n"
                f"Est. tokens: {status['estimated_tokens']}\n"
                f"Agent: {status['agent_id']}\n"
                f"Channel: {status['channel']}"
            )

        if cmd == "models":
            try:
                models = await list_models(self.settings)
                if not models:
                    return "No models available."
                lines = [f"`{m['id']}` — {m.get('name', 'Unknown')}" for m in models[:20]]
                return "**Available Models**\n" + "\n".join(lines)
            except Exception as exc:
                return f"Could not list models: {exc}"

        if cmd == "model":
            if not arg:
                return "Usage: `!model <name>`"
            self.agent.switch_model(arg.strip())
            return f"Switched to model `{self.agent.model_name}`"

        if cmd == "skills":
            registry = getattr(self.agent, "_skill_registry", None)
            if registry is None:
                return "No skill registry loaded."
            skills = registry.list_skills()
            if not skills:
                return "No skills loaded."
            lines = [f"`{s.name}` — {s.description or 'No description'}" for s in skills]
            return "**Loaded Skills**\n" + "\n".join(lines)

        if cmd == "compact":
            result = await self.agent.compact_history(room_id)
            return f"Compacted: {result}"

        if cmd == "reset":
            await self.agent.clear_history(room_id)
            return "Conversation history cleared."

        return None

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
