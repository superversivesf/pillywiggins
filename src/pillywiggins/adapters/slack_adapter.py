"""Slack adapter using slack-bolt."""
import asyncio
import logging
import signal
from datetime import datetime, timezone

from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from pillywiggins.adapters.base import BaseAdapter
from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.config import Settings
from pillywiggins.messaging.unified import ChannelType, UnifiedMessage

logger = logging.getLogger(__name__)


class SlackAdapter(BaseAdapter):
    command_prefix = "!"

    @staticmethod
    def _mask_token(token: str | None) -> str:
        """Redact a Slack token for safe logging.

        Returns a string showing only the first 5 and last 4 characters.
        """
        if not token:
            return ""
        if len(token) <= 12:
            return "***"
        return f"{token[:5]}****{token[-4:]}"

    def __init__(self, agent: PillywigginAgent, bot_token: str, settings: Settings):
        super().__init__(agent, settings)
        self.bot_token = bot_token
        self.settings = settings
        self._app: AsyncApp | None = None
        self._web_client: AsyncWebClient | None = None
        self._shutdown_event = asyncio.Event()

    async def connect(self) -> None:
        self._app = AsyncApp(token=self.bot_token)
        self._web_client = AsyncWebClient(token=self.bot_token)
        # Register message handler
        self._app.message()(self._on_message)
        logger.info("Slack adapter connected (token: %s)", self._mask_token(self.bot_token))

    async def listen(self) -> None:
        """Start the Slack Socket Mode connection."""
        if self._app is None:
            raise RuntimeError("Slack adapter not connected. Call connect() first.")

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                asyncio.get_running_loop().add_signal_handler(sig, self._shutdown_event.set)
            except (NotImplementedError, ValueError):
                pass

        # slack-bolt's Socket Mode handler runs as an async task
        handler = AsyncSocketModeHandler(self._app, self.bot_token)
        await handler.start_async()

        logger.info("Slack adapter listening via Socket Mode...")
        await self._shutdown_event.wait()
        await handler.close_async()

    async def _on_message(self, body: dict, say, client: AsyncWebClient) -> None:
        """Handle incoming Slack message."""
        event = body.get("event", {})
        user = event.get("user", "")
        text = event.get("text", "")
        channel = event.get("channel", "")
        ts = event.get("ts", "")

        # Skip our own messages
        bot_user_id = await self._get_bot_user_id(client)
        if user == bot_user_id:
            return

        if not self._is_authorized(user):
            logger.info("Unauthorized Slack user: %s", user)
            return

        # Normalize to UnifiedMessage
        msg = self.normalize({
            "user": user,
            "text": text,
            "channel": channel,
            "ts": ts,
            "thread_ts": event.get("thread_ts"),
            "is_group": event.get("channel_type") in ("channel", "group"),
            "is_bot": event.get("bot_id") is not None,
        })

        if not self.agent.should_process_message(msg):
            return

        # Commands
        if text.strip().startswith(self.command_prefix):
            response = await self.dispatch_command(text.strip(), channel)
            if response:
                await say(response)
            return

        # Normal message
        try:
            reply = await self.agent.handle_message(msg)
            if reply:
                await say(reply)
        except Exception:
            logger.exception("Error handling Slack message")
            await say("Sorry, something went wrong processing your message.")

    async def _get_bot_user_id(self, client: AsyncWebClient) -> str:
        """Cache and return our bot's user ID."""
        if not hasattr(self, "_bot_user_id"):
            result = await client.auth_test()
            self._bot_user_id = result.get("user_id", "")
        return self._bot_user_id

    async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
        if self._web_client is None:
            logger.warning("Slack web client not connected, cannot send")
            return
        try:
            thread_ts = metadata.get("thread_ts") if metadata else None
            await self._web_client.chat_postMessage(
                channel=channel_id,
                text=content,
                thread_ts=thread_ts,
            )
        except Exception:
            logger.exception("Failed to send Slack message to %s", channel_id)

    def normalize(self, raw_message: dict) -> UnifiedMessage:
        return UnifiedMessage(
            channel=ChannelType.SLACK,
            channel_user_id=raw_message["user"],
            content=raw_message["text"],
            conversation_key=raw_message["ts"],
            timestamp=datetime.now(timezone.utc),
            metadata={
                "user": raw_message["user"],
                "channel": raw_message["channel"],
                "ts": raw_message["ts"],
                "thread_ts": raw_message.get("thread_ts"),
                "is_group": raw_message.get("is_group", False),
            },
        )


# Need to import AsyncSocketModeHandler at the bottom to avoid circular issues
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler