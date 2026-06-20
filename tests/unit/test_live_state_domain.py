from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import (
    DbWriterCheckpointId,
    HistoricalStateSliceId,
    LiveStateSnapshotId,
    LiveTailSliceId,
    StreamId,
    StreamPartitionId,
)
from futures_bot.domain.live_state import (
    DbWriterBatchPolicy,
    DbWriterCheckpoint,
    DurabilityStatus,
    HistoricalStateSlice,
    LiveStateFreshness,
    LiveStateSnapshot,
    LiveTailSlice,
    StreamEventEnvelope,
    StreamPosition,
    canonical_payload_hash,
    canonical_payload_size_bytes,
    deterministic_stream_event_id,
)

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
STREAM = StreamId("market-events")
PARTITION = StreamPartitionId("0")


def _position(offset: int, *, partition: StreamPartitionId = PARTITION) -> StreamPosition:
    return StreamPosition(
        stream_id=STREAM,
        partition_id=partition,
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


def _freshness(
    offset: int,
    *,
    staleness_ms: int = 10,
    is_speculative: bool = False,
    durability_status: DurabilityStatus = DurabilityStatus.DURABLE_COMMITTED,
) -> LiveStateFreshness:
    return LiveStateFreshness(
        latest_position=_position(offset),
        projected_at=BASE_TIME,
        staleness_ms=staleness_ms,
        gap_free=True,
        is_complete=True,
        is_speculative=is_speculative,
        durability_status=durability_status,
    )


def _checkpoint(offset: int) -> DbWriterCheckpoint:
    return DbWriterCheckpoint(
        checkpoint_id=DbWriterCheckpointId(f"checkpoint-{offset}"),
        stream_id=STREAM,
        partition_id=PARTITION,
        persisted_until_offset=offset,
        persisted_until_event_sequence=offset,
        persisted_until_event_time=BASE_TIME + timedelta(milliseconds=offset),
        last_batch_event_count=1,
        last_batch_size_bytes=100,
        last_commit_started_at=BASE_TIME,
        last_commit_finished_at=BASE_TIME + timedelta(milliseconds=1),
        lag_records=0,
        lag_ms=0,
    )


def _snapshot(offset: int, payload: object | None = None) -> LiveStateSnapshot:
    payload = {"offset": offset} if payload is None else payload
    return LiveStateSnapshot(
        snapshot_id=LiveStateSnapshotId("snapshot-1"),
        snapshot_kind="ORDER_BOOK",
        latest_position=_position(offset),
        payload=payload,
        payload_canonical_hash=canonical_payload_hash(payload),
        freshness=_freshness(offset),
        updated_at=BASE_TIME + timedelta(milliseconds=offset),
    )


def test_stream_position_same_stream_partition_comparison() -> None:
    assert _position(1).is_before(_position(2))
    assert _position(2).is_after(_position(1))
    with pytest.raises(ValueError, match="stream_id and partition_id"):
        _position(1).is_before(_position(2, partition=StreamPartitionId("1")))


def test_stream_position_contiguous_offset() -> None:
    assert _position(2).is_contiguous_after(_position(1))
    assert not _position(3).is_contiguous_after(_position(1))


def test_stream_event_envelope_deterministic_event_id() -> None:
    event = _event(1)
    same = _event(1)
    assert event.event_id == same.event_id
    with pytest.raises(ValidationError, match="event_id"):
        StreamEventEnvelope(
            **{**event.model_dump(), "event_id": "stream-event:not-the-id"}
        )


def test_stream_event_envelope_payload_hash_validation() -> None:
    event = _event(1)
    with pytest.raises(ValidationError, match="payload_canonical_hash"):
        StreamEventEnvelope(
            **{**event.model_dump(), "payload_canonical_hash": "0" * 64}
        )


def test_db_writer_batch_policy_flushes_by_bytes() -> None:
    policy = DbWriterBatchPolicy(max_size_bytes=100, max_count=10, max_wait_ms=500)
    assert policy.should_flush(100, 1, 1)


def test_db_writer_batch_policy_flushes_by_count() -> None:
    policy = DbWriterBatchPolicy(max_size_bytes=100, max_count=10, max_wait_ms=500)
    assert policy.should_flush(1, 10, 1)


def test_db_writer_batch_policy_flushes_by_time() -> None:
    policy = DbWriterBatchPolicy(max_size_bytes=100, max_count=10, max_wait_ms=500)
    assert policy.should_flush(1, 1, 500)


def test_db_writer_batch_policy_critical_max_wait() -> None:
    policy = DbWriterBatchPolicy(
        max_size_bytes=100,
        max_count=10,
        max_wait_ms=500,
        critical_max_wait_ms=50,
    )
    assert policy.should_flush(1, 1, 50, is_critical=True)
    assert not policy.should_flush(1, 1, 50)


def test_db_writer_checkpoint_advances_forward() -> None:
    _checkpoint(2).validate_advances_from(_checkpoint(1))


def test_db_writer_checkpoint_rejects_backwards_movement() -> None:
    with pytest.raises(ValueError, match="backwards"):
        _checkpoint(1).validate_advances_from(_checkpoint(2))


def test_live_state_freshness_tradable_if_fresh_complete_gap_free_committed() -> None:
    freshness = _freshness(1)
    assert freshness.is_tradable_for_policy(
        max_staleness_ms=100,
        allow_speculative=False,
        require_gap_free=True,
        require_complete=True,
        minimum_durability_status=DurabilityStatus.DURABLE_COMMITTED,
    )


def test_live_state_freshness_rejects_stale_state() -> None:
    freshness = _freshness(1, staleness_ms=101)
    assert not freshness.is_tradable_for_policy(
        max_staleness_ms=100,
        allow_speculative=False,
        require_gap_free=True,
        require_complete=True,
        minimum_durability_status=DurabilityStatus.DURABLE_COMMITTED,
    )


def test_live_state_freshness_rejects_speculative_when_policy_forbids_it() -> None:
    freshness = _freshness(
        1,
        is_speculative=True,
        durability_status=DurabilityStatus.LIVE_ACCEPTED,
    )
    assert not freshness.is_tradable_for_policy(
        max_staleness_ms=100,
        allow_speculative=False,
        require_gap_free=True,
        require_complete=True,
        minimum_durability_status=DurabilityStatus.LIVE_ACCEPTED,
    )


def test_live_state_snapshot_rejects_older_offset_overwrite() -> None:
    with pytest.raises(ValueError, match="older offset"):
        _snapshot(1).validate_can_replace(_snapshot(2))


def test_live_state_snapshot_idempotent_same_offset_hash() -> None:
    _snapshot(1).validate_can_replace(_snapshot(1))


def test_live_state_snapshot_rejects_same_offset_different_hash() -> None:
    with pytest.raises(ValueError, match="different payload hash"):
        _snapshot(1, {"offset": 1, "version": 2}).validate_can_replace(_snapshot(1))


def test_historical_state_slice_validates_ordered_contiguous_events() -> None:
    events = (_event(1), _event(2), _event(3))
    historical = HistoricalStateSlice(
        slice_id=HistoricalStateSliceId("history-1"),
        stream_id=STREAM,
        partition_id=PARTITION,
        from_offset=1,
        to_offset=3,
        events=events,
        persisted_until_position=_position(3),
        is_gap_free=True,
    )
    assert historical.events == events

    with pytest.raises(ValidationError, match="contiguous"):
        HistoricalStateSlice(
            slice_id=HistoricalStateSliceId("history-gap"),
            stream_id=STREAM,
            partition_id=PARTITION,
            from_offset=1,
            to_offset=3,
            events=(_event(1), _event(3)),
            persisted_until_position=_position(3),
            is_gap_free=True,
        )


def test_empty_historical_state_slice_keeps_explicit_persisted_boundary() -> None:
    historical = HistoricalStateSlice(
        slice_id=HistoricalStateSliceId("history-empty"),
        stream_id=STREAM,
        partition_id=PARTITION,
        from_offset=101,
        to_offset=100,
        events=(),
        persisted_until_position=_position(100),
        is_gap_free=True,
    )
    assert historical.events == ()
    assert historical.persisted_until_position.offset == 100
    assert historical.from_offset == 101
    assert historical.to_offset == 100


def test_live_tail_slice_validates_ordered_contiguous_events() -> None:
    events = (_event(4), _event(5))
    live_tail = LiveTailSlice(
        slice_id=LiveTailSliceId("tail-1"),
        stream_id=STREAM,
        partition_id=PARTITION,
        from_offset=4,
        to_offset=5,
        events=events,
        latest_position=_position(5),
        freshness=_freshness(5),
    )
    assert live_tail.events == events

    with pytest.raises(ValidationError, match="contiguous"):
        LiveTailSlice(
            slice_id=LiveTailSliceId("tail-gap"),
            stream_id=STREAM,
            partition_id=PARTITION,
            from_offset=4,
            to_offset=6,
            events=(_event(4), _event(6)),
            latest_position=_position(6),
            freshness=_freshness(6),
        )
