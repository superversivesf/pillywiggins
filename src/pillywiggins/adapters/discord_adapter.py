import asyncio
import logging
import signal
from datetime import datetime, timezone

import discord

from pillywiggins.adapters.base import BaseAdapter
from pillywiggins.adapters.models import list_models
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
    def __init__(self, agent, token: str, settings: Settings):
        super().__init__(agent)
        self.token = token
        self.settings = settings
        self._allowed_user_ids = settings.get_allowed_user_ids()
        self._allow_all = settings.allowed_user_ids.strip().lower() == "all"
        self._client: discord.Client | None = None
        self._bot_chat_counts: dict[str, int] = {}

    def _is_authorized(self, user_id: int) -> bool:
        if self._allow_all:
            return True
        return user_id in self._allowed_user_ids

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
            logger.info(
                "Bot chat limit reached (%d) in channel %s, staying quiet", limit, channel_id
            )
            return False
        return True

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
            asyncio.get_event_loop().add_signal_handler(sig, event.set)
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

    async def _cmd_help(self, message: discord.Message) -> None:
        await message.channel.send(HELP_TEXT)

    async def _cmd_status(self, message: discord.Message) -> None:
        conversation_key = str(message.channel.id)
        history = self.agent._get_history(conversation_key)
        message_count = len(history)
        total_chars = sum(
            len(getattr(p, "content", "")) if hasattr(p, "content") else len(str(p))
            for msg in history
            for p in (msg.parts if hasattr(msg, "parts") else [])
        )
        estimated_tokens = round(total_chars / 4)
        model = self.agent.model_name
        lines = [
            f"**Agent:** `{self.agent.agent_id}`",
            f"**Channel:** `{self.agent.personality.channel}`",
            f"**Model:** `{model}`",
            f"**Messages:** {message_count}",
            f"**Est. tokens:** ~{estimated_tokens}",
        ]
        await message.channel.send("\n".join(lines))

    async def _cmd_models(self, message: discord.Message) -> None:
        models = await list_models(
            self.settings.llm_base_url,
            self.settings.llm_api_key,
            self.settings.llm_provider,
        )
        if not models:
            await message.channel.send("Could not fetch model list.")
            return
        models = sorted(models, key=lambda m: m.id)
        current = self.agent.model_name
        lines = ["**Available models:**"]
        for m in models:
            marker = " ✅" if m.id == current else ""
            lines.append(f"• `{m.id}`{marker}")
        await message.channel.send("\n".join(lines))

    async def _cmd_model(self, message: discord.Message) -> None:
        parts = message.content.strip().split(None, 1)
        if len(parts) < 2:
            await message.channel.send(f"Current model: `{self.agent.model_name}`")
            return
        new_model = parts[1].strip()
        self.agent.switch_model(new_model)
        await message.channel.send(f"Switched to `{new_model}`")

    async def _cmd_reset(self, message: discord.Message) -> None:
        conversation_key = str(message.channel.id)
        await self.agent.clear_history(conversation_key=conversation_key)
        await message.channel.send("Conversation history cleared.")

    async def _cmd_compact(self, message: discord.Message) -> None:
        conversation_key = str(message.channel.id)
        result = await self.agent.compact_history(conversation_key=conversation_key)
        await message.channel.send(result)

    async def _cmd_skills(self, message: discord.Message) -> None:
        skills = self.agent._skill_registry.list_skills()
        if not skills:
            await message.channel.send("No skills loaded.")
            return
        lines = ["**Loaded skills:**"]
        for skill in skills:
            desc = (
                skill.description[:60] + "..." if len(skill.description) > 60 else skill.description
            )
            perm_list = [k for k, v in skill.permissions.items() if v]
            perm_str = f" [{', '.join(perm_list)}]" if perm_list else ""
            lines.append(f"• `{skill.name}` — {desc}{perm_str}")
        await message.channel.send("\n".join(lines))

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
        channel_id = unified.conversation_key
        is_bot = unified.metadata.get("is_bot", False)
        if not self._should_respond_to_bot(channel_id, is_bot):
            return
        if is_bot:
            self._bot_chat_counts[channel_id] = self._bot_chat_counts.get(channel_id, 0) + 1
        logger.info(
            "Message from %s: %s", unified.metadata.get("username", "?"), unified.content[:80]
        )
        try:
            done = asyncio.Event()
            typing_task = asyncio.create_task(self._keep_typing(channel_id, done))
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
