from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.events import EventEnvelope, EventType
from futures_bot.domain.ids import BotId, EventId


def test_valid_event_creation_and_payload_default() -> None:
    event = EventEnvelope(
        event_id=EventId("event-1"),
        event_type=EventType.BOT_CREATED,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        bot_id=BotId("bot-1"),
        schema_version="v1",
    )

    assert event.payload == {}
    assert event.local_sequence is None


def test_empty_schema_version_rejected() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        EventEnvelope(
            event_id=EventId("event-1"),
            event_type=EventType.BOT_CREATED,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            schema_version="",
        )


def test_negative_local_sequence_rejected() -> None:
    with pytest.raises(ValidationError, match="local_sequence"):
        EventEnvelope(
            event_id=EventId("event-1"),
            event_type=EventType.BOT_CREATED,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            schema_version="v1",
            local_sequence=-1,
        )


def test_naive_occurred_at_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        EventEnvelope(
            event_id=EventId("event-1"),
            event_type=EventType.BOT_CREATED,
            occurred_at=datetime(2026, 1, 1),
            schema_version="v1",
        )


def test_payload_accepts_dict_safely() -> None:
    payload = {"note": "created"}
    event = EventEnvelope(
        event_id=EventId("event-1"),
        event_type=EventType.BOT_CREATED,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        schema_version="v1",
        payload=payload,
    )

    payload["note"] = "mutated outside"
    assert event.payload == {"note": "created"}
