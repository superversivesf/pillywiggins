"""Telegram test harness using python-telegram-bot.

Provides AgentHarness for black-box testing of Pillywiggins Telegram agents.
Uses python-telegram-bot's Bot API for message sending and response listening.

Usage:
    harness = AgentHarness(bot_token="...")
    async with harness:
        response = await harness.ask("chat_id_here", "Hello!")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from telegram import Bot
from telegram.ext import Application, MessageHandler, filters
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

__all__ = ["AgentHarness"]


class AgentHarness:
    """Test harness for interacting with pillywiggins agents via Telegram Bot API."""

    def __init__(self, bot_token: str) -> None:
        self._bot_token = bot_token
        self._application: Optional[Application] = None
        self._bot: Optional[Bot] = None
        self._response_queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    async def _message_handler(self, update, context):
        """Collect incoming messages into the response queue."""
        if update.message and update.message.text:
            await self._response_queue.put({
                "chat_id": update.message.chat_id,
                "from_id": update.message.from_user.id,
                "text": update.message.text,
            })

    async def connect(self) -> None:
        """Create and start the Application, begin polling for messages."""
        if self._application is not None:
            return  # already connected

        self._application = Application.builder().token(self._bot_token).build()
        self._application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._message_handler)
        )
        await self._application.initialize()
        await self._application.start()
        await self._application.updater.start_polling()
        self._bot = self._application.bot
        me = await self._bot.get_me()
        logger.info("Harness connected as @%s", me.username)
        self._running = True

    async def disconnect(self) -> None:
        """Clean shutdown of the Application."""
        self._running = False
        if self._application:
            await self._application.updater.stop()
            await self._application.stop()
            await self._application.shutdown()
            self._application = None
            self._bot = None
            # Drain the queue
            while not self._response_queue.empty():
                self._response_queue.get_nowait()

    # ── core operations ────────────────────────────────────────────────

    async def send_message(self, chat_id: str, text: str):
        """Send a message to a chat.

        Args:
            chat_id: The Telegram chat ID (string or int).
            text: The message text.

        Returns:
            The sent Message object.

        Raises:
            RuntimeError: If harness is not connected.
        """
        if not self._bot:
            raise RuntimeError("Not connected — call connect() first")
        return await self._bot.send_message(chat_id=chat_id, text=text)

    async def wait_for_response(self, timeout: float = 30.0) -> Optional[str]:
        """Wait for one incoming message from any agent.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            The message text, or None if the timeout expires.
        """
        try:
            msg = await asyncio.wait_for(self._response_queue.get(), timeout=timeout)
            return msg["text"]
        except asyncio.TimeoutError:
            return None

    # ── convenience ────────────────────────────────────────────────────

    async def ask(
        self,
        chat_id: str,
        question: str,
        timeout: float = 30.0,
        wait_between: float = 1.0,
    ) -> Optional[str]:
        """Send a question to a chat and wait for the response.

        Args:
            chat_id: The Telegram chat ID to send to.
            question: The question to ask.
            timeout: Maximum seconds to wait for a response.
            wait_between: Seconds to wait after sending before listening
                          (avoids catching the sent message echo).

        Returns:
            The response text, or None if no response within timeout.
        """
        await self.send_message(chat_id, question)
        await asyncio.sleep(wait_between)
        return await self.wait_for_response(timeout)

    # ── context manager ────────────────────────────────────────────────

    async def __aenter__(self) -> "AgentHarness":
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.disconnect()
