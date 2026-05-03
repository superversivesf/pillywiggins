"""Tests for email_adapter.py."""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-populate mock modules for aiosmtplib and imap_tools so the adapter
# can be imported even when the optional deps are not installed.
for mod_name in ("aiosmtplib", "imap_tools"):
    if mod_name not in sys.modules:
        mock_mod = MagicMock()
        mock_mod.MailBox = MagicMock()
        mock_mod.AND = MagicMock()
        sys.modules[mod_name] = mock_mod

from pillywiggins.adapters.email_adapter import (
    EmailAdapter,
    _normalize_subject,
)


@pytest.fixture
def adapter():
    agent = MagicMock()
    agent.personality = MagicMock()
    agent.personality.bot_chat_limit = 0
    agent.agent_id = "test-agent"
    settings = MagicMock()
    settings.allowed_user_ids = ""
    settings.get_allowed_user_ids.return_value = set()
    return EmailAdapter(
        agent=agent,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="bot@example.com",
        smtp_password="secret",
        imap_host="imap.example.com",
        imap_port=993,
        imap_user="bot@example.com",
        imap_password="secret",
        settings=settings,
        poll_interval=30,
    )


def test_normalize_subject_strips_re():
    assert _normalize_subject("Re: Hello") == "Hello"
    assert _normalize_subject("RE: Fwd: Test") == "Test"
    assert _normalize_subject("Hello") == "Hello"


def test_email_adapter_init(adapter):
    assert adapter.smtp_host == "smtp.example.com"
    assert adapter.smtp_port == 587
    assert adapter.poll_interval == 30


@pytest.mark.asyncio
async def test_send_email_calls_smtp(adapter):
    """send() should trigger SMTP send_message."""
    mock_client = AsyncMock()
    aiosmtplib_mod = sys.modules["aiosmtplib"]
    aiosmtplib_mod.SMTP.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    aiosmtplib_mod.SMTP.return_value.__aexit__ = AsyncMock(return_value=False)

    await adapter.send("user@example.com", "Hello!", {"subject": "Test"})

    mock_client.login.assert_awaited_once()
    mock_client.send_message.assert_awaited_once()


def test_normalize_creates_unified_message(adapter):
    msg = adapter.normalize({
        "sender": "user@example.com",
        "to": ["bot@example.com"],
        "subject": "Hello",
        "body": "World",
        "thread_key": "subj:Hello",
        "message_id": "abc123",
        "date": "2024-01-01",
    })
    assert msg.channel.value == "email"
    assert msg.channel_user_id == "user@example.com"
    assert msg.content == "World"
    assert msg.conversation_key == "email:subj:Hello"
    assert msg.metadata["subject"] == "Hello"


def test_thread_context_keeps_last_three(adapter):
    """Thread context should keep only last 3 messages."""
    adapter._update_thread_context("t1", "a", "msg1")
    adapter._update_thread_context("t1", "b", "msg2")
    adapter._update_thread_context("t1", "a", "msg3")
    adapter._update_thread_context("t1", "b", "msg4")
    ctx = adapter._thread_contexts["t1"]
    assert len(ctx) == 3
    assert ctx[0]["content"] == "msg2"


def test_is_authorized_all(adapter):
    """When ALLOWED_USER_IDS is 'all', any sender is authorized."""
    adapter._allow_all = True
    assert adapter._is_authorized("anyone@example.com") is True


def test_is_authorized_specific(adapter):
    """Only specific emails are authorized when configured."""
    adapter._allow_all = False
    adapter._allowed_user_ids = {"user@example.com"}
    assert adapter._is_authorized("user@example.com") is True
    assert adapter._is_authorized("other@example.com") is False
