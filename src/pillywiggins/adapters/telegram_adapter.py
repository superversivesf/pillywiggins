import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import Application, MessageHandler, filters

from pillywiggins.adapters.base import BaseAdapter
from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.messaging.unified import ChannelType, UnifiedMessage

logger = logging.getLogger(__name__)


class TelegramAdapter(BaseAdapter):
    def __init__(self, agent: PillywigginAgent, token: str):
        super().__init__(agent)
        self.token = token
        self._app: Application | None = None

    async def connect(self) -> None:
        self._app = Application.builder().token(self.token).build()
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))

    async def listen(self) -> None:
        if not self._app:
            await self.connect()
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def send(self, conversation_key: str, text: str, **kwargs) -> None:
        chat_id = int(conversation_key)
        await self._app.bot.send_message(chat_id=chat_id, text=text)

    def normalize(self, raw_update: Update) -> UnifiedMessage:
        message = raw_update.message
        return UnifiedMessage(
            channel=ChannelType.TELEGRAM,
            channel_user_id=str(message.from_user.id),
            content=message.text or "",
            conversation_key=str(message.chat_id),
            timestamp=datetime.now(timezone.utc),
            metadata={"username": message.from_user.username},
        )

    async def _on_message(self, update: Update, context) -> None:
        if not update.message or not update.message.text:
            return
        unified = self.normalize(update)
        try:
            response = await self.agent.handle_message(unified)
            await self.send(unified.conversation_key, response)
        except Exception:
            logger.exception("Error handling Telegram message")

    async def shutdown(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()