from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from futures_bot.domain.events import EventEnvelope, EventType
from futures_bot.domain.ids import BotId, EventId, ProducerId, RunId
from futures_bot.domain.journal import JournalRecord, WalOffset, WalOffsetRange


def _utc(year: int = 2026, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


def _event() -> EventEnvelope:
    return EventEnvelope(
        event_id=EventId("evt-1"),
        event_type=EventType.BOT_CREATED,
        occurred_at=_utc(),
        bot_id=BotId("bot-1"),
        schema_version="1.0",
    )


def _record(offset: int = 0) -> JournalRecord:
    return JournalRecord(
        run_id=RunId("run-1"),
        producer_id=ProducerId("producer-1"),
        wal_offset=WalOffset(value=offset),
        event=_event(),
        recorded_at=_utc(),
        payload_hash="abc123",
        record_size_bytes=64,
    )


# ── WalOffset ─────────────────────────────────────────────────────────────────

def test_wal_offset_accepts_zero_and_positive() -> None:
    assert WalOffset(value=0).value == 0
    assert WalOffset(value=100).value == 100


def test_wal_offset_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        WalOffset(value=-1)


def test_wal_offset_next_increments_by_one() -> None:
    assert WalOffset(value=5).next() == WalOffset(value=6)


def test_wal_offset_is_before_or_equal() -> None:
    a = WalOffset(value=3)
    b = WalOffset(value=5)
    assert a.is_before_or_equal(b)
    assert a.is_before_or_equal(a)
    assert not b.is_before_or_equal(a)


def test_wal_offset_lt_and_le() -> None:
    a = WalOffset(value=1)
    b = WalOffset(value=2)
    assert a < b
    assert a <= b
    assert a <= WalOffset(value=1)  # reflexive via equal value
    assert not b < a
    assert not b <= a


# ── WalOffsetRange ─────────────────────────────────────────────────────────────

def test_wal_offset_range_count_and_contains() -> None:
    r = WalOffsetRange(first=WalOffset(value=3), last=WalOffset(value=7))
    assert r.count == 5
    assert r.contains(WalOffset(value=3))
    assert r.contains(WalOffset(value=5))
    assert r.contains(WalOffset(value=7))
    assert not r.contains(WalOffset(value=2))
    assert not r.contains(WalOffset(value=8))


def test_wal_offset_range_accepts_equal_first_and_last() -> None:
    r = WalOffsetRange(first=WalOffset(value=4), last=WalOffset(value=4))
    assert r.count == 1


def test_wal_offset_range_rejects_first_greater_than_last() -> None:
    with pytest.raises(ValidationError):
        WalOffsetRange(first=WalOffset(value=5), last=WalOffset(value=3))


# ── JournalRecord ──────────────────────────────────────────────────────────────

def test_journal_record_accepts_valid_input() -> None:
    rec = _record(offset=0)
    assert rec.record_size_bytes == 64
    assert rec.payload_hash == "abc123"


def test_journal_record_rejects_naive_recorded_at() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        JournalRecord(
            run_id=RunId("run-1"),
            producer_id=ProducerId("producer-1"),
            wal_offset=WalOffset(value=0),
            event=_event(),
            recorded_at=datetime(2026, 1, 1),
            payload_hash="abc123",
            record_size_bytes=64,
        )


def test_journal_record_rejects_empty_payload_hash() -> None:
    with pytest.raises(ValidationError, match="payload_hash"):
        JournalRecord(
            run_id=RunId("run-1"),
            producer_id=ProducerId("producer-1"),
            wal_offset=WalOffset(value=0),
            event=_event(),
            recorded_at=_utc(),
            payload_hash="",
            record_size_bytes=64,
        )


def test_journal_record_rejects_whitespace_payload_hash() -> None:
    with pytest.raises(ValidationError, match="payload_hash"):
        JournalRecord(
            run_id=RunId("run-1"),
            producer_id=ProducerId("producer-1"),
            wal_offset=WalOffset(value=0),
            event=_event(),
            recorded_at=_utc(),
            payload_hash=" abc ",
            record_size_bytes=64,
        )


def test_journal_record_rejects_zero_record_size_bytes() -> None:
    with pytest.raises(ValidationError, match="record_size_bytes"):
        JournalRecord(
            run_id=RunId("run-1"),
            producer_id=ProducerId("producer-1"),
            wal_offset=WalOffset(value=0),
            event=_event(),
            recorded_at=_utc(),
            payload_hash="abc123",
            record_size_bytes=0,
        )


def test_journal_record_normalizes_recorded_at_to_utc() -> None:
    tz_plus2 = timezone(timedelta(hours=2))
    rec = JournalRecord(
        run_id=RunId("run-1"),
        producer_id=ProducerId("producer-1"),
        wal_offset=WalOffset(value=0),
        event=_event(),
        recorded_at=datetime(2026, 1, 1, 12, 0, tzinfo=tz_plus2),
        payload_hash="abc123",
        record_size_bytes=64,
    )
    assert rec.recorded_at.tzinfo is UTC
    assert rec.recorded_at.hour == 10
