"""Slack adapter using slack-bolt."""
import asyncio
import logging
import signal
from datetime import datetime, timezone

from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from pillywiggins.adapters.base import BaseAdapter
from pillywiggins.adapters.models import list_models
from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.config import Settings
from pillywiggins.messaging.unified import ChannelType, UnifiedMessage

logger = logging.getLogger(__name__)

HELP_TEXT = """*Pillywiggins Commands*

!help — Show this message
!status — Show agent status (model, context size, etc.)
!models — List available LLM models
!model <name> — Switch to a different model
!skills — List loaded skills
!compact — Summarize conversation history to free context
!reset — Clear conversation history"""


class SlackAdapter(BaseAdapter):
    def __init__(self, agent: PillywigginAgent, bot_token: str, settings: Settings):
        super().__init__(agent)
        self.bot_token = bot_token
        self.settings = settings
        self._allowed_user_ids = settings.get_allowed_user_ids()
        self._allow_all = settings.allowed_user_ids.strip().lower() == "all"
        self._app: AsyncApp | None = None
        self._web_client: AsyncWebClient | None = None
        self._bot_chat_counts: dict[str, int] = {}
        self._shutdown_event = asyncio.Event()

    def _is_authorized(self, user_id: str) -> bool:
        if self._allow_all:
            return True
        allowed = {str(uid) for uid in self._allowed_user_ids}
        return user_id in allowed

    def _should_respond_to_bot(self, channel_id: str, is_bot: bool) -> bool:
        if not is_bot:
            self._bot_chat_counts[channel_id] = 0
            return True
        limit = getattr(self.agent.personality, "bot_chat_limit", 3)
        if not isinstance(limit, int):
            limit = 3
        if limit < 0:
            return True
        if limit == 0:
            return False
        count = self._bot_chat_counts.get(channel_id, 0)
        if count >= limit:
            logger.info("Bot chat limit reached (%d) in channel %s, staying quiet", limit, channel_id)
            return False
        return True

    async def connect(self) -> None:
        self._app = AsyncApp(token=self.bot_token)
        self._web_client = AsyncWebClient(token=self.bot_token)
        # Register message handler
        self._app.message()(self._on_message)
        logger.info("Slack adapter connected (token starts with %s...)", self.bot_token[:10])

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

        is_bot = event.get("bot_id") is not None
        if not self._should_respond_to_bot(channel, is_bot):
            return
        if is_bot:
            self._bot_chat_counts[channel] = self._bot_chat_counts.get(channel, 0) + 1

        # Normalize to UnifiedMessage
        msg = self.normalize({
            "user": user,
            "text": text,
            "channel": channel,
            "ts": ts,
            "thread_ts": event.get("thread_ts"),
            "is_group": event.get("channel_type") in ("channel", "group"),
        })

        # Slash commands
        if text.strip().startswith("!"):
            response = await self._handle_command(text.strip(), channel)
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

    async def _handle_command(self, text: str, channel_id: str) -> str | None:
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
                f"*Status*\n"
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
                return "*Available Models*\n" + "\n".join(lines)
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
            return "*Loaded Skills*\n" + "\n".join(lines)

        if cmd == "compact":
            result = await self.agent.compact_history(channel_id)
            return f"Compacted: {result}"

        if cmd == "reset":
            await self.agent.clear_history(channel_id)
            return "Conversation history cleared."

        return None

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
