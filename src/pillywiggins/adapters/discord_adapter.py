import asyncio
import logging
import signal
from datetime import datetime, timezone

import discord

from pillywiggins.adapters.base import BaseAdapter
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


class DiscordAdapter(BaseAdapter):
    command_prefix = "!"

    def __init__(self, agent, token: str, settings: Settings):
        super().__init__(agent, settings)
        self.token = token
        self.settings = settings
        self._client: discord.Client | None = None

    async def connect(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        self._client.event(self._on_message)

    async def listen(self) -> None:
        if not self._client:
            await self.connect()
        await self._client.login(self.token)
        await self._client.connect()
        await self._idle()

    async def _idle(self) -> None:
        event = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                asyncio.get_running_loop().add_signal_handler(sig, event.set)
            except (NotImplementedError, ValueError):
                pass
        await event.wait()
        await self.shutdown()

    async def send(
        self, channel_id: str, content: str, metadata: dict | None = None, **kwargs
    ) -> None:
        if self._client is None:
            return
        cid = int(channel_id)
        channel = self._client.get_channel(cid)
        if channel is None:
            try:
                channel = await self._client.fetch_channel(cid)
            except Exception:
                logger.exception("Failed to fetch channel %s", channel_id)
                return
        if channel is None:
            logger.warning("Channel %s not found", channel_id)
            return
        try:
            await channel.send(content)
        except Exception:
            logger.exception("Failed to send message to channel %s", channel_id)

    def normalize(self, raw_message: discord.Message) -> UnifiedMessage:
        is_group = raw_message.guild is not None
        conversation_key = str(raw_message.channel.id)
        metadata = {
            "username": raw_message.author.name,
            "is_bot": raw_message.author.bot,
            "is_group": is_group,
        }
        if is_group and raw_message.guild:
            metadata["guild_id"] = str(raw_message.guild.id)
        return UnifiedMessage(
            channel=ChannelType.DISCORD,
            channel_user_id=str(raw_message.author.id),
            content=raw_message.content or "",
            conversation_key=conversation_key,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata,
        )

    async def _keep_typing(self, channel_id: str, done: asyncio.Event) -> None:
        if self._client is None:
            return
        channel = self._client.get_channel(int(channel_id))
        if channel is None:
            return
        while not done.is_set():
            try:
                async with channel.typing():
                    await asyncio.wait_for(done.wait(), timeout=4)
            except TimeoutError:
                pass

    async def _on_message(self, message: discord.Message) -> None:
        if self._client is None:
            return
        if message.author.id == self._client.user.id:
            return
        if not message.content:
            return
        if not self._is_authorized(message.author.id):
            await message.channel.send("You are not authorized to use this bot.")
            return
        unified = self.normalize(message)
        if not self.agent.should_process_message(unified):
            return
        logger.info(
            "Message from %s: %s", unified.metadata.get("username", "?"), unified.content[:80]
        )

        text = message.content.strip()
        # Command dispatch
        if text.startswith(self.command_prefix):
            response = await self.dispatch_command(text, unified.conversation_key)
            if response:
                await message.channel.send(response)
            return

        # Normal message
        try:
            done = asyncio.Event()
            typing_task = asyncio.create_task(self._keep_typing(unified.conversation_key, done))
            try:
                response = await self.agent.handle_message(unified)
            finally:
                done.set()
                typing_task.cancel()
            await self.send(unified.conversation_key, response, metadata=None)
        except Exception:
            logger.exception("Error handling Discord message")

    async def shutdown(self) -> None:
        if self._client:
            await self._client.close()