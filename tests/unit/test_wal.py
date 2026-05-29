from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.events import EventEnvelope, EventType
from futures_bot.domain.ids import BotId, EventId, ProducerId, RunId, WalSegmentId
from futures_bot.domain.journal import JournalRecord, WalOffset, WalOffsetRange
from futures_bot.domain.wal import (
    WalAppendResult,
    WalAppendStatus,
    WalSegmentMetadata,
    WalSegmentStatus,
)


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


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


def _open_segment() -> WalSegmentMetadata:
    return WalSegmentMetadata(
        segment_id=WalSegmentId("seg-1"),
        run_id=RunId("run-1"),
        status=WalSegmentStatus.OPEN,
        created_at=_utc(),
    )


def _sealed_segment(
    first: int = 0,
    last: int = 4,
    status: WalSegmentStatus = WalSegmentStatus.SEALED,
) -> WalSegmentMetadata:
    event_count = last - first + 1
    return WalSegmentMetadata(
        segment_id=WalSegmentId("seg-1"),
        run_id=RunId("run-1"),
        status=status,
        offset_range=WalOffsetRange(
            first=WalOffset(value=first), last=WalOffset(value=last)
        ),
        created_at=_utc(0),
        sealed_at=_utc(1),
        event_count=event_count,
    )


# ── WalSegmentMetadata ─────────────────────────────────────────────────────────

def test_open_segment_is_valid() -> None:
    seg = _open_segment()
    assert seg.status is WalSegmentStatus.OPEN
    assert seg.sealed_at is None


def test_open_segment_rejects_sealed_at() -> None:
    with pytest.raises(ValidationError, match="OPEN segment must not have sealed_at"):
        WalSegmentMetadata(
            segment_id=WalSegmentId("seg-1"),
            run_id=RunId("run-1"),
            status=WalSegmentStatus.OPEN,
            created_at=_utc(),
            sealed_at=_utc(1),
        )


def test_non_open_segment_requires_sealed_at() -> None:
    with pytest.raises(ValidationError, match="non-OPEN segment requires sealed_at"):
        WalSegmentMetadata(
            segment_id=WalSegmentId("seg-1"),
            run_id=RunId("run-1"),
            status=WalSegmentStatus.SEALED,
            created_at=_utc(),
        )


def test_segment_event_count_must_match_offset_range() -> None:
    with pytest.raises(ValidationError, match="event_count must match"):
        WalSegmentMetadata(
            segment_id=WalSegmentId("seg-1"),
            run_id=RunId("run-1"),
            status=WalSegmentStatus.SEALED,
            offset_range=WalOffsetRange(
                first=WalOffset(value=0), last=WalOffset(value=4)
            ),
            created_at=_utc(0),
            sealed_at=_utc(1),
            event_count=3,  # range count is 5
        )


def test_sealed_at_before_created_at_rejected() -> None:
    with pytest.raises(ValidationError, match="sealed_at must be >= created_at"):
        WalSegmentMetadata(
            segment_id=WalSegmentId("seg-1"),
            run_id=RunId("run-1"),
            status=WalSegmentStatus.SEALED,
            created_at=_utc(5),
            sealed_at=_utc(3),
            event_count=0,
        )


def test_deleted_segment_requires_offset_range_and_sealed_at() -> None:
    with pytest.raises(ValidationError, match="DELETED segment requires"):
        WalSegmentMetadata(
            segment_id=WalSegmentId("seg-1"),
            run_id=RunId("run-1"),
            status=WalSegmentStatus.DELETED,
            created_at=_utc(0),
            sealed_at=_utc(1),
            event_count=0,
            # missing offset_range
        )


def test_sealed_segment_with_correct_event_count_is_valid() -> None:
    seg = _sealed_segment(first=0, last=4)
    assert seg.event_count == 5
    assert seg.status is WalSegmentStatus.SEALED


# ── WalAppendResult ────────────────────────────────────────────────────────────

def test_wal_append_result_appended_requires_record() -> None:
    rec = _record()
    result = WalAppendResult.ok(rec)
    assert result.appended is True
    assert result.record == rec
    assert result.reason is None


def test_wal_append_result_appended_without_record_rejected() -> None:
    with pytest.raises(ValidationError, match="APPENDED status requires record"):
        WalAppendResult(
            status=WalAppendStatus.APPENDED,
            appended=True,
        )


def test_wal_append_result_rejected_requires_reason() -> None:
    result = WalAppendResult.rejected(WalAppendStatus.REJECTED_WAL_FULL, "WAL is full")
    assert result.appended is False
    assert result.record is None
    assert result.reason == "WAL is full"


def test_wal_append_result_rejected_without_reason_raises() -> None:
    with pytest.raises(ValidationError, match="non-empty trimmed reason"):
        WalAppendResult(
            status=WalAppendStatus.REJECTED_WAL_FULL,
            appended=False,
        )


def test_wal_append_result_rejected_cannot_carry_record() -> None:
    rec = _record()
    with pytest.raises(ValidationError, match="rejected status must not carry record"):
        WalAppendResult(
            status=WalAppendStatus.REJECTED_WAL_FULL,
            appended=False,
            record=rec,
            reason="WAL is full",
        )


def test_wal_append_result_appended_must_have_appended_true() -> None:
    rec = _record()
    with pytest.raises(ValidationError, match="APPENDED status requires appended=True"):
        WalAppendResult(
            status=WalAppendStatus.APPENDED,
            appended=False,
            record=rec,
        )
