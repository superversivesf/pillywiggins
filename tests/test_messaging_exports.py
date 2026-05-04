"""Verify that src/pillywiggins/messaging/__init__.py exports the expected symbols."""
from pillywiggins.messaging import (
    BROADCAST_SUBJECT,
    DIRECT_SUBJECT_PREFIX,
    NatsBus,
    UnifiedMessage,
)


def test_unified_message_import():
    assert UnifiedMessage is not None


def test_nats_bus_import():
    assert NatsBus is not None


def test_broadcast_subject_import():
    assert BROADCAST_SUBJECT == "council.broadcast"


def test_direct_subject_prefix_import():
    assert DIRECT_SUBJECT_PREFIX == "council.direct"
