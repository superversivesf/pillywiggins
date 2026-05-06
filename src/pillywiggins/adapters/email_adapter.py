"""Email adapter using aiosmtplib (send) + imap-tools (receive)."""
import asyncio
import email
import logging
import re
import signal
from datetime import datetime, timezone
from typing import Any

import aiosmtplib
from imap_tools import MailBox, AND

from pillywiggins.adapters.base import BaseAdapter
from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.config import Settings
from pillywiggins.messaging.unified import ChannelType, UnifiedMessage

logger = logging.getLogger(__name__)

# Strip Re:/Fwd: prefixes to find thread subject
_RE_PREFIX = re.compile(r"^(Re|Fw|Fwd|RE|FW|FWD)\s*:\s*", re.IGNORECASE)


def _normalize_subject(subject: str) -> str:
    """Strip reply/fwd prefixes for thread matching."""
    s = subject.strip()
    while True:
        m = _RE_PREFIX.match(s)
        if not m:
            break
        s = s[m.end() :].strip()
    return s


class EmailAdapter(BaseAdapter):
    command_prefix = "!"

    def __init__(
        self,
        agent: PillywigginAgent,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        imap_host: str,
        imap_port: int,
        imap_user: str,
        imap_password: str,
        settings: Settings,
        poll_interval: int = 30,
    ):
        super().__init__(agent, settings)
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.imap_user = imap_user
        self.imap_password = imap_password
        self.settings = settings
        self.poll_interval = poll_interval
        self._shutdown_event = asyncio.Event()
        # Thread-local conversation context: thread_key -> list of last 3 messages
        self._thread_contexts: dict[str, list[dict[str, Any]]] = {}

    def _get_thread_key(self, msg) -> str:
        """Build a stable thread key from message references or subject."""
        # Prefer In-Reply-To / References for threading
        refs = []
        if msg.headers.get("in-reply-to"):
            refs.extend(msg.headers["in-reply-to"])
        if msg.headers.get("references"):
            refs.extend(msg.headers["references"])
        if refs:
            return f"ref:{refs[0].strip()}"
        # Fallback to normalized subject
        return f"subj:{_normalize_subject(msg.subject or '')}"

    def _update_thread_context(self, thread_key: str, sender: str, content: str) -> list[dict[str, Any]]:
        """Keep last 3 messages in a thread for context."""
        ctx = self._thread_contexts.setdefault(thread_key, [])
        ctx.append({"sender": sender, "content": content, "timestamp": datetime.now(timezone.utc).isoformat()})
        # Keep only last 3
        self._thread_contexts[thread_key] = ctx[-3:]
        return self._thread_contexts[thread_key]

    async def connect(self) -> None:
        """Verify SMTP connectivity by sending a NOOP or just logging in."""
        try:
            async with aiosmtplib.SMTP(
                hostname=self.smtp_host,
                port=self.smtp_port,
                use_tls=self.smtp_port == 465,
            ) as client:
                if self.smtp_port != 465:
                    await client.starttls()
                await client.login(self.smtp_user, self.smtp_password)
                logger.info("Email SMTP connected (%s:%s as %s)", self.smtp_host, self.smtp_port, self.smtp_user)
        except Exception:
            logger.warning("Email SMTP connection test failed", exc_info=True)

    async def listen(self) -> None:
        """Poll IMAP inbox every poll_interval seconds."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                asyncio.get_running_loop().add_signal_handler(sig, self._shutdown_event.set)
            except (NotImplementedError, ValueError):
                pass

        logger.info("Email adapter polling inbox every %s seconds...", self.poll_interval)
        while not self._shutdown_event.is_set():
            try:
                await self._poll_inbox()
            except Exception:
                logger.exception("Email poll error")
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass

    async def _poll_inbox(self) -> None:
        """Fetch unread emails and process them."""
        # imap-tools is synchronous; run in thread
        def _fetch():
            new_messages = []
            try:
                with MailBox(self.imap_host, port=self.imap_port).login(
                    self.imap_user, self.imap_password
                ) as mailbox:
                    # Fetch unseen messages
                    for msg in mailbox.fetch(AND(seen=False), mark_seen=True, bulk=True):
                        new_messages.append(msg)
            except Exception:
                logger.exception("IMAP fetch error")
            return new_messages

        messages = await asyncio.to_thread(_fetch)
        for msg in messages:
            asyncio.create_task(self._handle_email(msg))

    async def _handle_email(self, msg) -> None:
        sender = msg.from_ or "unknown@localhost"
        if not self._is_authorized(sender):
            logger.info("Unauthorized email sender: %s", sender)
            return

        # Build body from text parts
        body_parts = []
        if msg.text:
            body_parts.append(msg.text)
        if not body_parts and msg.html:
            # Very basic HTML-to-text: strip tags
            import html

            text = html.unescape(re.sub(r"<[^>]+>", "", msg.html))
            body_parts.append(text)
        content = "\n\n".join(body_parts).strip()

        thread_key = self._get_thread_key(msg)
        context = self._update_thread_context(thread_key, sender, content)

        # Build conversation_key from thread for context window
        conversation_key = f"email:{thread_key}"

        unified = self.normalize({
            "sender": sender,
            "to": msg.to or [],
            "subject": msg.subject or "",
            "body": content,
            "thread_key": thread_key,
            "message_id": msg.uid or msg.headers.get("message-id", [""])[0],
            "date": msg.date,
        })

        if not self.agent.should_process_message(unified):
            return

        # Commands
        if content.startswith(self.command_prefix):
            response = await self.dispatch_command(content, conversation_key)
            if response:
                reply_subject = f"Re: {msg.subject or 'Pillywiggins Response'}"
                await self._send_email(sender, reply_subject, response, in_reply_to=msg.headers.get("message-id", [None])[0])
            return

        # Include thread context in the message for the agent
        context_text = ""
        if len(context) > 1:
            context_text = "\n\nPrevious messages in this thread:\n"
            for entry in context[:-1]:
                context_text += f"- {entry['sender']}: {entry['content'][:200]}\n"

        full_content = content + context_text

        try:
            reply = await self.agent.handle_message(unified)
            if reply:
                reply_subject = f"Re: {msg.subject or 'Pillywiggins Response'}"
                await self._send_email(sender, reply_subject, reply, in_reply_to=msg.headers.get("message-id", [None])[0])
        except Exception:
            logger.exception("Error handling email")
            await self._send_email(
                sender,
                f"Re: {msg.subject or 'Error'}",
                "Sorry, something went wrong processing your email.",
            )

    async def _send_email(
        self,
        to: str | list[str],
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> None:
        """Send an email via aiosmtplib."""
        if isinstance(to, str):
            to = [to]

        msg = email.message.EmailMessage()
        msg["From"] = self.smtp_user
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)

        try:
            async with aiosmtplib.SMTP(
                hostname=self.smtp_host,
                port=self.smtp_port,
                use_tls=self.smtp_port == 465,
            ) as client:
                if self.smtp_port != 465:
                    await client.starttls()
                await client.login(self.smtp_user, self.smtp_password)
                await client.send_message(msg)
            logger.info("Email sent to %s: %s", to, subject)
        except Exception:
            logger.exception("Failed to send email to %s", to)

    async def send(self, channel_id: str, content: str, metadata: dict | None = None) -> None:
        """Send an email reply. channel_id is the recipient email."""
        subject = "Pillywiggins Response"
        if metadata and metadata.get("subject"):
            subject = f"Re: {metadata['subject']}"
        in_reply_to = metadata.get("in_reply_to") if metadata else None
        await self._send_email(channel_id, subject, content, in_reply_to=in_reply_to)

    def normalize(self, raw_message: dict) -> UnifiedMessage:
        return UnifiedMessage(
            channel=ChannelType.EMAIL,
            channel_user_id=raw_message["sender"],
            content=raw_message["body"],
            conversation_key=f"email:{raw_message['thread_key']}",
            timestamp=datetime.now(timezone.utc),
            metadata={
                "sender": raw_message["sender"],
                "to": raw_message.get("to", []),
                "subject": raw_message.get("subject", ""),
                "message_id": raw_message.get("message_id"),
                "date": raw_message.get("date"),
            },
        )