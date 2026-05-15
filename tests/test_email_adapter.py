"""Tests for email_adapter.py."""
import asyncio
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
    _sanitize_header,
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


# ---------------------------------------------------------------------------
# Async I/O tests
# ---------------------------------------------------------------------------

def _make_imap_msg(
    from_="user@example.com",
    to=None,
    subject="Hello",
    uid="uid-123",
    text="Hello there",
    html=None,
    message_id="<abc@example.com>",
    date="2024-01-01",
):
    msg = MagicMock()
    msg.from_ = from_
    msg.to = to or ["bot@example.com"]
    msg.subject = subject
    msg.uid = uid
    msg.date = date
    msg.text = text
    msg.html = html
    msg.headers = {"message-id": [message_id]}
    return msg


@pytest.mark.asyncio
async def test_connect_smtp_success(adapter):
    mock_client = AsyncMock()
    aiosmtplib_mod = sys.modules["aiosmtplib"]
    aiosmtplib_mod.SMTP.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    aiosmtplib_mod.SMTP.return_value.__aexit__ = AsyncMock(return_value=False)

    await adapter.connect()

    aiosmtplib_mod.SMTP.assert_called_with(
        hostname="smtp.example.com", port=587, use_tls=False
    )
    mock_client.starttls.assert_awaited_once()
    mock_client.login.assert_awaited_once_with("bot@example.com", "secret")


@pytest.mark.asyncio
async def test_connect_smtp_failure_logs_warning(adapter, caplog):
    mock_client = AsyncMock()
    mock_client.starttls.side_effect = Exception("TLS failed")
    aiosmtplib_mod = sys.modules["aiosmtplib"]
    aiosmtplib_mod.SMTP.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    aiosmtplib_mod.SMTP.return_value.__aexit__ = AsyncMock(return_value=False)

    with caplog.at_level("WARNING", logger="pillywiggins.adapters.email_adapter"):
        await adapter.connect()

    assert "SMTP connection test failed" in caplog.text


@pytest.mark.asyncio
async def test_listen_polls_and_shuts_down(adapter):
    adapter.poll_interval = 0.01
    adapter._shutdown_event = asyncio.Event()
    poll_calls = 0

    async def mock_poll():
        nonlocal poll_calls
        poll_calls += 1
        if poll_calls >= 2:
            adapter._shutdown_event.set()

    with patch.object(adapter, "_poll_inbox", new=mock_poll):
        await adapter.listen()

    assert poll_calls >= 2


@pytest.mark.asyncio
async def test_poll_inbox_fetches_and_handles_email(adapter):
    mock_msg = _make_imap_msg()
    mock_mailbox = MagicMock()
    mock_mailbox.fetch.return_value = [mock_msg]
    mock_login_ctx = MagicMock()
    mock_login_ctx.__enter__ = MagicMock(return_value=mock_mailbox)
    mock_login_ctx.__exit__ = MagicMock(return_value=False)
    imap_tools_mod = sys.modules["imap_tools"]
    imap_tools_mod.MailBox.return_value.login.return_value = mock_login_ctx

    with patch.object(adapter, "_handle_email", new=AsyncMock()) as mock_handle:
        await adapter._poll_inbox()
        # Drain any background tasks created by asyncio.create_task
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    imap_tools_mod.MailBox.assert_called_once_with("imap.example.com", port=993)
    mock_handle.assert_awaited_once_with(mock_msg)


@pytest.mark.asyncio
async def test_handle_email_rejects_unauthorized(adapter):
    adapter._allow_all = False
    adapter._allowed_user_ids = set()
    mock_msg = _make_imap_msg()

    await adapter._handle_email(mock_msg)

    adapter.agent.handle_message.assert_not_called()


@pytest.mark.asyncio
async def test_handle_email_dispatches_command(adapter):
    adapter._allow_all = True
    adapter.agent.should_process_message.return_value = True
    adapter.dispatch_command = AsyncMock(return_value="Command output")
    adapter._send_email = AsyncMock()

    mock_msg = _make_imap_msg(text="!status")

    await adapter._handle_email(mock_msg)

    adapter.dispatch_command.assert_awaited_once_with("!status", "email:subj:Hello")
    adapter._send_email.assert_awaited_once_with(
        "user@example.com",
        "Re: Hello",
        "Command output",
        in_reply_to="<abc@example.com>",
    )
    assert "subj:Hello" in adapter._thread_contexts


@pytest.mark.asyncio
async def test_handle_email_generates_reply(adapter):
    adapter._allow_all = True
    adapter.agent.should_process_message.return_value = True
    adapter.agent.handle_message = AsyncMock(return_value="AI reply")
    adapter._send_email = AsyncMock()

    mock_msg = _make_imap_msg(text="How are you?")

    await adapter._handle_email(mock_msg)

    adapter.agent.handle_message.assert_awaited_once()
    args, _ = adapter.agent.handle_message.call_args
    unified = args[0]
    assert unified.channel.value == "email"
    assert unified.content == "How are you?"
    adapter._send_email.assert_awaited_once_with(
        "user@example.com",
        "Re: Hello",
        "AI reply",
        in_reply_to="<abc@example.com>",
    )


@pytest.mark.asyncio
async def test_handle_email_generates_reply_with_prior_context(adapter):
    adapter._allow_all = True
    adapter.agent.should_process_message.return_value = True
    adapter.agent.handle_message = AsyncMock(return_value="AI reply")
    adapter._send_email = AsyncMock()
    adapter._thread_contexts["email:subj:Hello"] = [
        {"sender": "a@example.com", "content": "Prior msg", "timestamp": "2024-01-01T00:00:00+00:00"}
    ]

    mock_msg = _make_imap_msg(text="Follow up")

    await adapter._handle_email(mock_msg)

    adapter.agent.handle_message.assert_awaited_once()
    adapter._send_email.assert_awaited_once_with(
        "user@example.com",
        "Re: Hello",
        "AI reply",
        in_reply_to="<abc@example.com>",
    )


@pytest.mark.asyncio
async def test_handle_email_agent_error_sends_failure_reply(adapter):
    adapter._allow_all = True
    adapter.agent.should_process_message.return_value = True
    adapter.agent.handle_message = AsyncMock(side_effect=Exception("boom"))
    adapter._send_email = AsyncMock()

    mock_msg = _make_imap_msg(text="Crash me")

    await adapter._handle_email(mock_msg)

    adapter.agent.handle_message.assert_awaited_once()
    adapter._send_email.assert_awaited_once_with(
        "user@example.com",
        "Re: Hello",
        "Sorry, something went wrong processing your email.",
    )


@pytest.mark.asyncio
async def test_send_email_success(adapter):
    mock_client = AsyncMock()
    aiosmtplib_mod = sys.modules["aiosmtplib"]
    aiosmtplib_mod.SMTP.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    aiosmtplib_mod.SMTP.return_value.__aexit__ = AsyncMock(return_value=False)

    await adapter._send_email(
        "user@example.com",
        "Re: Hello",
        "Reply body",
        in_reply_to="<abc@example.com>",
    )

    mock_client.starttls.assert_awaited_once()
    mock_client.login.assert_awaited_once_with("bot@example.com", "secret")
    mock_client.send_message.assert_awaited_once()
    sent_msg = mock_client.send_message.call_args[0][0]
    assert sent_msg["To"] == "user@example.com"
    assert sent_msg["Subject"] == "Re: Hello"
    assert sent_msg["In-Reply-To"] == "<abc@example.com>"
    assert sent_msg["References"] == "<abc@example.com>"
    assert "Reply body" in sent_msg.get_content()


@pytest.mark.asyncio
async def test_send_email_failure_logs(adapter, caplog):
    mock_client = AsyncMock()
    mock_client.send_message.side_effect = Exception("SMTP exploded")
    aiosmtplib_mod = sys.modules["aiosmtplib"]
    aiosmtplib_mod.SMTP.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    aiosmtplib_mod.SMTP.return_value.__aexit__ = AsyncMock(return_value=False)

    with caplog.at_level("ERROR", logger="pillywiggins.adapters.email_adapter"):
        await adapter._send_email("user@example.com", "Subject", "Body")

    assert "Failed to send email" in caplog.text


# ---------------------------------------------------------------------------
# Regression tests: string user ID auth + CRLF header injection
# ---------------------------------------------------------------------------


def test_sanitize_header_replaces_crlf():
    """_sanitize_header() should replace \\r and \\n with spaces."""
    assert _sanitize_header("hello\r\nworld") == "hello  world"
    assert _sanitize_header("\r\ninjected\r\n") == "  injected  "
    assert _sanitize_header("clean") == "clean"
    assert _sanitize_header(42) == "42"  # Non-string handled gracefully


@pytest.mark.parametrize("uid", [
    "bob@example.com",
    "alice@mail.org",
    "user+tag@domain.co.uk",
    "@user:matrix.org",
    "@bob:example.com",
])
def test_is_authorized_accepts_string_user_ids(adapter, uid):
    """_is_authorized() must accept string user IDs like email addresses."""
    adapter._allow_all = False
    adapter._allowed_user_ids = {"bob@example.com", "@user:matrix.org"}
    expected = uid in adapter._allowed_user_ids
    assert adapter._is_authorized(uid) is expected


@pytest.mark.asyncio
async def test_send_email_blocks_crlf_injection_in_subject(adapter):
    """CRLF in subject should be sanitized before hitting SMTP."""
    mock_client = AsyncMock()
    aiosmtplib_mod = sys.modules["aiosmtplib"]
    aiosmtplib_mod.SMTP.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    aiosmtplib_mod.SMTP.return_value.__aexit__ = AsyncMock(return_value=False)

    await adapter._send_email(
        "user@example.com",
        "Hello\r\nBcc: attacker@evil.com\r\nX-Injected: true",
        "Body content",
    )

    sent_msg = mock_client.send_message.call_args[0][0]
    # CRLF should be replaced with spaces; header injection blocked
    assert "\r" not in sent_msg["Subject"]
    assert "\n" not in sent_msg["Subject"]
    assert "Bcc:" in sent_msg["Subject"]  # becomes part of subject, not a header


@pytest.mark.asyncio
async def test_send_email_blocks_crlf_injection_in_to(adapter):
    """CRLF in To address should be sanitized."""
    mock_client = AsyncMock()
    aiosmtplib_mod = sys.modules["aiosmtplib"]
    aiosmtplib_mod.SMTP.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    aiosmtplib_mod.SMTP.return_value.__aexit__ = AsyncMock(return_value=False)

    await adapter._send_email(
        "user@example.com\r\nBcc: attacker@evil.com",
        "Hello",
        "Body",
    )

    sent_msg = mock_client.send_message.call_args[0][0]
    assert "\r" not in sent_msg["To"]
    assert "\n" not in sent_msg["To"]


@pytest.mark.asyncio
async def test_send_email_preserves_body_newlines(adapter):
    """Body newlines should NOT be sanitized — only headers."""
    mock_client = AsyncMock()
    aiosmtplib_mod = sys.modules["aiosmtplib"]
    aiosmtplib_mod.SMTP.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    aiosmtplib_mod.SMTP.return_value.__aexit__ = AsyncMock(return_value=False)

    body = "Line 1\nLine 2\nLine 3"
    await adapter._send_email("user@example.com", "Hello", body)

    sent_msg = mock_client.send_message.call_args[0][0]
    assert "Line 1\nLine 2\nLine 3" in sent_msg.get_content()
