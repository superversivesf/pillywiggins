import asyncio
import logging
import signal
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from pillywiggins.adapters.base import BaseAdapter
from pillywiggins.adapters.models import list_models
from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.config import Settings
from pillywiggins.messaging.unified import ChannelType, UnifiedMessage

logger = logging.getLogger(__name__)

HELP_TEXT = """*Pillywiggins Commands*
/help — Show this message
/status — Show agent status (model, context size, etc.)
/models — List available LLM models
/model <name> — Switch to a different model
/skills — List loaded skills
/compact — Summarize conversation history to free context
/reset — Clear conversation history"""


class TelegramAdapter(BaseAdapter):
    def __init__(self, agent: PillywigginAgent, token: str, settings: Settings):
        super().__init__(agent)
        self.token = token
        self.settings = settings
        self._allowed_user_ids = settings.get_allowed_user_ids()
        self._allow_all = settings.allowed_user_ids.strip().lower() == "all"
        self._app: Application | None = None
        self._bot_chat_counts: dict[str, int] = {}

    def _is_authorized(self, user_id: int) -> bool:
        if self._allow_all:
            return True
        return user_id in self._allowed_user_ids

    def _should_respond_to_bot(self, chat_id: str, is_bot: bool) -> bool:
        if not is_bot:
            self._bot_chat_counts[chat_id] = 0
            return True
        limit = getattr(self.agent.personality, "bot_chat_limit", 3)
        if not isinstance(limit, int):
            limit = 3
        if limit < 0:
            return True
        if limit == 0:
            return False
        count = self._bot_chat_counts.get(chat_id, 0)
        if count >= limit:
            logger.info("Bot chat limit reached (%d) in chat %s, staying quiet", limit, chat_id)
            return False
        return True

    async def connect(self) -> None:
        self._app = Application.builder().token(self.token).build()
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("models", self._cmd_models))
        self._app.add_handler(CommandHandler("model", self._cmd_model))
        self._app.add_handler(CommandHandler("skills", self._cmd_skills))
        self._app.add_handler(CommandHandler("compact", self._cmd_compact))
        self._app.add_handler(CommandHandler("reset", self._cmd_reset))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))

    async def listen(self) -> None:
        if not self._app:
            await self.connect()
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
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
        chat_id = kwargs.get("chat_id")
        if chat_id is None and metadata is not None:
            chat_id = metadata.get("chat_id")
        if chat_id is None:
            chat_id = channel_id
        await self._app.bot.send_message(chat_id=int(chat_id), text=content)

    def normalize(self, raw_update: Update) -> UnifiedMessage:
        message = raw_update.message
        chat_id = str(message.chat_id)
        is_group = message.chat.type in ("group", "supergroup")
        conversation_key = str(message.from_user.id) if is_group else chat_id
        metadata = {
            "username": message.from_user.username
            or message.from_user.first_name
            or str(message.from_user.id),
            "is_bot": message.from_user.is_bot,
            "is_group": is_group,
        }
        if is_group:
            metadata["chat_id"] = chat_id
        return UnifiedMessage(
            channel=ChannelType.TELEGRAM,
            channel_user_id=str(message.from_user.id),
            content=message.text or "",
            conversation_key=conversation_key,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata,
        )

    async def _cmd_help(self, update: Update, context) -> None:
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

    async def _cmd_status(self, update: Update, context) -> None:
        chat_id = update.message.chat_id
        is_group = update.message.chat.type in ("group", "supergroup")
        conversation_key = str(update.message.from_user.id) if is_group else str(chat_id)
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
            f"*Agent:* `{self.agent.agent_id}`",
            f"*Channel:* `{self.agent.personality.channel}`",
            f"*Model:* `{model}`",
            f"*Messages:* {message_count}",
            f"*Est. tokens:* ~{estimated_tokens}",
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_models(self, update: Update, context) -> None:
        models = await list_models(
            self.settings.llm_base_url,
            self.settings.llm_api_key,
            self.settings.llm_provider,
        )
        if not models:
            await update.message.reply_text("Could not fetch model list.")
            return
        models = sorted(models, key=lambda m: m.id)
        current = self.agent.model_name
        lines = ["*Available models:*"]
        for m in models:
            marker = " ✅" if m.id == current else ""
            lines.append(f"• `{m.id}`{marker}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_model(self, update: Update, context) -> None:
        if not context.args:
            await update.message.reply_text(
                f"Current model: `{self.agent.model_name}`", parse_mode="Markdown"
            )
            return
        new_model = " ".join(context.args)
        self.agent.switch_model(new_model)
        await update.message.reply_text(f"Switched to `{new_model}`", parse_mode="Markdown")

    async def _cmd_reset(self, update: Update, context) -> None:
        chat_id = update.message.chat_id
        is_group = update.message.chat.type in ("group", "supergroup")
        conversation_key = str(update.message.from_user.id) if is_group else str(chat_id)
        await self.agent.clear_history(conversation_key=conversation_key)
        await update.message.reply_text("Conversation history cleared.")

    async def _cmd_compact(self, update: Update, context) -> None:
        chat_id = update.message.chat_id
        is_group = update.message.chat.type in ("group", "supergroup")
        conversation_key = str(update.message.from_user.id) if is_group else str(chat_id)
        result = await self.agent.compact_history(conversation_key=conversation_key)
        await update.message.reply_text(result)

    async def _cmd_skills(self, update: Update, context) -> None:
        skills = self.agent._skill_registry.list_skills()
        if not skills:
            await update.message.reply_text("No skills loaded.")
            return
        lines = ["*Loaded skills:*"]
        for skill in skills:
            desc = (
                skill.description[:60] + "..." if len(skill.description) > 60 else skill.description
            )
            perm_list = [k for k, v in skill.permissions.items() if v]
            perm_str = f" [{', '.join(perm_list)}]" if perm_list else ""
            lines.append(f"• `{skill.name}` — {desc}{perm_str}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _keep_typing(self, chat_id: str, done: asyncio.Event) -> None:
        while not done.is_set():
            await self._app.bot.send_chat_action(chat_id=chat_id, action="typing")
            try:
                await asyncio.wait_for(done.wait(), timeout=4)
            except TimeoutError:
                pass

    async def _on_message(self, update: Update, context) -> None:
        if not update.message or not update.message.text:
            return
        if not self._is_authorized(update.message.from_user.id):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        unified = self.normalize(update)
        if not self.agent.should_process_message(unified):
            return
        logger.info(
            "Message from %s: %s", unified.metadata.get("username", "?"), unified.content[:80]
        )
        try:
            chat_id = unified.metadata.get("chat_id", unified.conversation_key)
            done = asyncio.Event()
            typing_task = asyncio.create_task(self._keep_typing(chat_id, done))
            try:
                response = await self.agent.handle_message(unified)
            finally:
                done.set()
                typing_task.cancel()
            send_kwargs = {}
            if "chat_id" in unified.metadata:
                send_kwargs["chat_id"] = unified.metadata["chat_id"]
            await self.send(
                unified.conversation_key,
                response,
                metadata=send_kwargs or None,
            )
        except Exception:
            logger.exception("Error handling Telegram message")

    async def shutdown(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
