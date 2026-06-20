from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from futures_bot.domain.ids import (
    HistoricalStateSliceId,
    LiveTailSliceId,
    StreamId,
    StreamPartitionId,
)
from futures_bot.domain.live_state import (
    DurabilityStatus,
    HistoricalStateSlice,
    LiveStateFreshness,
    LiveStateFreshnessPolicy,
    LiveTailSlice,
    StitchFailureReason,
    StreamEventEnvelope,
    StreamPosition,
    canonical_payload_hash,
    canonical_payload_size_bytes,
    deterministic_stream_event_id,
)
from futures_bot.live_state.stitcher import DeterministicStateStitcher

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
STREAM = StreamId("market-events")
PARTITION = StreamPartitionId("0")


def _position(offset: int) -> StreamPosition:
    return StreamPosition(
        stream_id=STREAM,
        partition_id=PARTITION,
        offset=offset,
        event_sequence=offset,
        event_time=BASE_TIME + timedelta(milliseconds=offset),
    )


def _event(offset: int, payload: object | None = None) -> StreamEventEnvelope:
    payload = {"offset": offset} if payload is None else payload
    payload_hash = canonical_payload_hash(payload)
    position = _position(offset)
    return StreamEventEnvelope(
        schema_version="1",
        event_id=deterministic_stream_event_id(position, "MARKET_TICK", payload_hash),
        event_kind="MARKET_TICK",
        stream_position=position,
        payload=payload,
        payload_canonical_hash=payload_hash,
        payload_size_bytes=canonical_payload_size_bytes(payload),
        durability_status=DurabilityStatus.DURABLE_COMMITTED,
        producer_id="unit-test",
        created_at=BASE_TIME,
    )


def _freshness(offset: int, *, staleness_ms: int = 10) -> LiveStateFreshness:
    return LiveStateFreshness(
        latest_position=_position(offset),
        projected_at=BASE_TIME,
        staleness_ms=staleness_ms,
        gap_free=True,
        is_complete=True,
        is_speculative=False,
        durability_status=DurabilityStatus.DURABLE_COMMITTED,
    )


def _historical(events: tuple[StreamEventEnvelope, ...]) -> HistoricalStateSlice:
    return HistoricalStateSlice(
        slice_id=HistoricalStateSliceId("history-1"),
        stream_id=STREAM,
        partition_id=PARTITION,
        from_offset=events[0].stream_position.offset,
        to_offset=events[-1].stream_position.offset,
        events=events,
        persisted_until_position=events[-1].stream_position,
        is_gap_free=True,
    )


def _empty_historical(persisted_until_offset: int) -> HistoricalStateSlice:
    return HistoricalStateSlice(
        slice_id=HistoricalStateSliceId("empty-history"),
        stream_id=STREAM,
        partition_id=PARTITION,
        from_offset=persisted_until_offset + 1,
        to_offset=persisted_until_offset,
        events=(),
        persisted_until_position=_position(persisted_until_offset),
        is_gap_free=True,
    )


def _tail(
    events: tuple[StreamEventEnvelope, ...],
    *,
    staleness_ms: int = 10,
) -> LiveTailSlice:
    return LiveTailSlice(
        slice_id=LiveTailSliceId("tail-1"),
        stream_id=STREAM,
        partition_id=PARTITION,
        from_offset=events[0].stream_position.offset,
        to_offset=events[-1].stream_position.offset,
        events=events,
        latest_position=events[-1].stream_position,
        freshness=_freshness(events[-1].stream_position.offset, staleness_ms=staleness_ms),
    )


def _policy() -> LiveStateFreshnessPolicy:
    return LiveStateFreshnessPolicy(max_staleness_ms=100)


def test_stitched_state_slice_accepts_db_plus_live_tail_contiguous() -> None:
    stitched = DeterministicStateStitcher().stitch(
        _historical((_event(1), _event(2))),
        _tail((_event(3), _event(4))),
        _policy(),
    )
    assert [event.stream_position.offset for event in stitched.events] == [1, 2, 3, 4]
    assert stitched.is_complete
    assert stitched.is_gap_free
    assert stitched.tradable
    assert stitched.reason is None


def test_stitched_state_slice_rejects_db_plus_live_tail_gap() -> None:
    stitched = DeterministicStateStitcher().stitch(
        _historical((_event(1), _event(2))),
        _tail((_event(4), _event(5))),
        _policy(),
    )
    assert not stitched.is_complete
    assert not stitched.is_gap_free
    assert not stitched.tradable
    assert stitched.reason is StitchFailureReason.LIVE_HISTORY_GAP


def test_stitched_state_slice_accepts_exact_matching_overlap() -> None:
    event_2 = _event(2)
    stitched = DeterministicStateStitcher().stitch(
        _historical((_event(1), event_2)),
        _tail((event_2, _event(3))),
        _policy(),
    )
    assert [event.stream_position.offset for event in stitched.events] == [1, 2, 3]
    assert stitched.tradable


def test_stitched_state_slice_rejects_conflicting_overlap() -> None:
    with pytest.raises(ValueError, match=StitchFailureReason.INVALID_OVERLAP):
        DeterministicStateStitcher().stitch(
            _historical((_event(1), _event(2))),
            _tail((_event(2, {"offset": 2, "revision": 2}), _event(3))),
            _policy(),
        )


def test_stitched_state_slice_non_tradable_when_stale() -> None:
    stitched = DeterministicStateStitcher().stitch(
        _historical((_event(1), _event(2))),
        _tail((_event(3), _event(4)), staleness_ms=101),
        _policy(),
    )
    assert stitched.is_complete
    assert stitched.is_gap_free
    assert not stitched.tradable
    assert stitched.reason is StitchFailureReason.STALE_LIVE_STATE


def test_empty_history_live_tail_after_persisted_boundary_gap_is_non_tradable() -> None:
    stitched = DeterministicStateStitcher().stitch(
        _empty_historical(100),
        _tail((_event(102),)),
        _policy(),
    )
    assert [event.stream_position.offset for event in stitched.events] == [102]
    assert not stitched.is_complete
    assert not stitched.is_gap_free
    assert not stitched.tradable
    assert stitched.reason is StitchFailureReason.LIVE_HISTORY_GAP


def test_empty_historical_slice_with_live_tail_at_persisted_boundary_overlap_is_rejected() -> None:
    with pytest.raises(ValueError, match=StitchFailureReason.INVALID_OVERLAP):
        DeterministicStateStitcher().stitch(
            _empty_historical(100),
            _tail((_event(100),)),
            _policy(),
        )


def test_empty_history_live_tail_contiguous_after_persisted_boundary_is_tradable() -> None:
    stitched = DeterministicStateStitcher().stitch(
        _empty_historical(100),
        _tail((_event(101), _event(102))),
        _policy(),
    )
    assert [event.stream_position.offset for event in stitched.events] == [101, 102]
    assert stitched.is_complete
    assert stitched.is_gap_free
    assert stitched.tradable
    assert stitched.reason is None


def test_empty_history_without_live_tail_is_explicitly_incomplete() -> None:
    stitched = DeterministicStateStitcher().stitch(
        _empty_historical(100),
        None,
        _policy(),
    )
    assert stitched.events == ()
    assert not stitched.is_complete
    assert stitched.is_gap_free
    assert not stitched.tradable
    assert stitched.reason is StitchFailureReason.INCOMPLETE_HISTORY
