from datetime import datetime, timezone

from pillywiggins.messaging.unified import ChannelType, UnifiedMessage


def test_channel_type_enum_values():
    assert ChannelType.TELEGRAM.value == "telegram"
    assert ChannelType.DISCORD.value == "discord"
    assert ChannelType.SLACK.value == "slack"
    assert ChannelType.MATRIX.value == "matrix"
    assert ChannelType.EMAIL.value == "email"


def test_channel_type_is_str_enum():
    assert isinstance(ChannelType.TELEGRAM, str)
    assert ChannelType.TELEGRAM == "telegram"


def test_unified_message_creation():
    msg = UnifiedMessage(
        channel=ChannelType.TELEGRAM,
        channel_user_id="12345",
        content="Hello, world!",
        conversation_key="tele_12345",
    )
    assert msg.channel == ChannelType.TELEGRAM
    assert msg.channel_user_id == "12345"
    assert msg.content == "Hello, world!"
    assert msg.conversation_key == "tele_12345"


def test_unified_message_default_timestamp():
    before = datetime.now(timezone.utc)
    msg = UnifiedMessage(
        channel=ChannelType.DISCORD,
        channel_user_id="user1",
        content="Hi",
        conversation_key="disc_user1",
    )
    after = datetime.now(timezone.utc)
    assert before <= msg.timestamp <= after
    assert msg.timestamp.tzinfo == timezone.utc


def test_unified_message_default_metadata():
    msg = UnifiedMessage(
        channel=ChannelType.SLACK,
        channel_user_id="u42",
        content="Test",
        conversation_key="slack_u42",
    )
    assert msg.metadata == {}


def test_unified_message_with_metadata():
    msg = UnifiedMessage(
        channel=ChannelType.EMAIL,
        channel_user_id="alice@example.com",
        content="Check this out",
        conversation_key="email_alice",
        metadata={"subject": "Hello", "priority": "high"},
    )
    assert msg.metadata["subject"] == "Hello"
    assert msg.metadata["priority"] == "high"


def test_unified_message_explicit_timestamp():
    ts = datetime(2025, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
    msg = UnifiedMessage(
        channel=ChannelType.MATRIX,
        channel_user_id="@bob:matrix.org",
        content="Hey",
        conversation_key="matrix_bob",
        timestamp=ts,
    )
    assert msg.timestamp == ts


def test_channel_type_from_string():
    assert ChannelType("telegram") == ChannelType.TELEGRAM
    assert ChannelType("discord") == ChannelType.DISCORD


def test_channel_type_invalid_value():
    import pytest

    with pytest.raises(ValueError):
        ChannelType("irc")


def test_unified_message_metadata_mutation_isolation():
    msg1 = UnifiedMessage(
        channel=ChannelType.TELEGRAM,
        channel_user_id="u1",
        content="Hi",
        conversation_key="k1",
    )
    msg1.metadata["key"] = "value"
    msg2 = UnifiedMessage(
        channel=ChannelType.TELEGRAM,
        channel_user_id="u2",
        content="Hi2",
        conversation_key="k2",
    )
    assert msg2.metadata == {}


def test_unified_message_all_channel_types():
    for ct in ChannelType:
        msg = UnifiedMessage(
            channel=ct,
            channel_user_id="u1",
            content="test",
            conversation_key="k1",
        )
        assert msg.channel == ct


def test_unified_message_content_can_be_empty():
    msg = UnifiedMessage(
        channel=ChannelType.EMAIL,
        channel_user_id="a@b.com",
        content="",
        conversation_key="email_a",
    )
    assert msg.content == ""


# --- Tests for messaging/__init__.py exports ---


def test_messaging_package_exports_unified_message():
    from pillywiggins.messaging import UnifiedMessage as ExportedUnifiedMessage

    assert ExportedUnifiedMessage is UnifiedMessage


def test_messaging_package_exports_channel_type():
    from pillywiggins.messaging import ChannelType as ExportedChannelType

    assert ExportedChannelType is ChannelType


def test_messaging_package_exports_nats_bus():
    from pillywiggins.messaging import NatsBus

    assert NatsBus is not None


def test_messaging_package_exports_constants():
    from pillywiggins.messaging import COUNCIL_STREAM, BROADCAST_SUBJECT, DIRECT_SUBJECT_PREFIX

    assert isinstance(COUNCIL_STREAM, str)
    assert isinstance(BROADCAST_SUBJECT, str)
    assert isinstance(DIRECT_SUBJECT_PREFIX, str)

    from pillywiggins.messaging.nats_bus import COUNCIL_STREAM as ORIG_COUNCIL_STREAM
    from pillywiggins.messaging.nats_bus import BROADCAST_SUBJECT as ORIG_BROADCAST_SUBJECT
    from pillywiggins.messaging.nats_bus import DIRECT_SUBJECT_PREFIX as ORIG_DIRECT_SUBJECT_PREFIX

    assert COUNCIL_STREAM is ORIG_COUNCIL_STREAM
    assert BROADCAST_SUBJECT is ORIG_BROADCAST_SUBJECT
    assert DIRECT_SUBJECT_PREFIX is ORIG_DIRECT_SUBJECT_PREFIX
