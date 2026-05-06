import asyncio
import logging
import signal
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

try:
    from telegram.error import TimedOut
except Exception:  # pragma: no cover
    class TimedOut(Exception):  # type: ignore[no-redef]
        pass

from pillywiggins.adapters.base import BaseAdapter
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
    command_prefix = "/"

    def __init__(self, agent: PillywigginAgent, token: str, settings: Settings):
        super().__init__(agent, settings)
        self.token = token
        self.settings = settings
        self._app: Application | None = None

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
            try:
                asyncio.get_running_loop().add_signal_handler(sig, event.set)
            except (NotImplementedError, ValueError):
                pass
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

    def _conversation_key(self, update: Update) -> str:
        chat_id = update.message.chat_id
        is_group = update.message.chat.type in ("group", "supergroup")
        return str(update.message.from_user.id) if is_group else str(chat_id)

    async def _cmd_help(self, update: Update, context) -> None:
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

    async def _cmd_status(self, update: Update, context) -> None:
        response = await self.dispatch_command("/status", self._conversation_key(update))
        if response:
            await update.message.reply_text(response, parse_mode="Markdown")

    async def _cmd_models(self, update: Update, context) -> None:
        response = await self.dispatch_command("/models", self._conversation_key(update))
        if response:
            await update.message.reply_text(response, parse_mode="Markdown")

    async def _cmd_model(self, update: Update, context) -> None:
        args_text = " ".join(context.args) if context.args else ""
        cmd = "/model" if not args_text else f"/model {args_text}"
        response = await self.dispatch_command(cmd, self._conversation_key(update))
        if response:
            await update.message.reply_text(response, parse_mode="Markdown")

    async def _cmd_reset(self, update: Update, context) -> None:
        response = await self.dispatch_command("/reset", self._conversation_key(update))
        if response:
            await update.message.reply_text(response)

    async def _cmd_compact(self, update: Update, context) -> None:
        response = await self.dispatch_command("/compact", self._conversation_key(update))
        if response:
            await update.message.reply_text(response)

    async def _cmd_skills(self, update: Update, context) -> None:
        response = await self.dispatch_command("/skills", self._conversation_key(update))
        if response:
            await update.message.reply_text(response, parse_mode="Markdown")

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
            try:
                await self.send(
                    unified.conversation_key,
                    response,
                    metadata=send_kwargs or None,
                )
            except TimedOut:
                logger.warning(
                    "Timed out sending reply to Telegram chat %s; message may be retried automatically",
                    chat_id,
                )
        except Exception:
            logger.exception("Error handling Telegram message")

    async def shutdown(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()