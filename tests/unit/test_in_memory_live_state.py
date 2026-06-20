from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from futures_bot.domain.ids import (
    DbWriterCheckpointId,
    HistoricalStateSliceId,
    LiveStateSnapshotId,
    StreamId,
    StreamPartitionId,
)
from futures_bot.domain.live_state import (
    DbWriterCheckpoint,
    DurabilityStatus,
    LiveStateFreshness,
    LiveStateSnapshot,
    StreamEventEnvelope,
    StreamPosition,
    canonical_payload_hash,
    canonical_payload_size_bytes,
    deterministic_stream_event_id,
)
from futures_bot.live_state.in_memory import (
    InMemoryDbWriterCheckpointStore,
    InMemoryHistoricalStateReader,
    InMemoryLiveStateGateway,
)

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


def _event(offset: int) -> StreamEventEnvelope:
    payload = {"offset": offset}
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


def _freshness(offset: int) -> LiveStateFreshness:
    return LiveStateFreshness(
        latest_position=_position(offset),
        projected_at=BASE_TIME,
        staleness_ms=10,
        gap_free=True,
        is_complete=True,
        is_speculative=False,
        durability_status=DurabilityStatus.DURABLE_COMMITTED,
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


def test_in_memory_live_state_gateway_stores_newest_snapshot() -> None:
    gateway = InMemoryLiveStateGateway()
    gateway.put_snapshot(_snapshot(1))
    gateway.put_snapshot(_snapshot(2))
    loaded = gateway.get_snapshot(LiveStateSnapshotId("snapshot-1"))
    assert loaded is not None
    assert loaded.latest_position.offset == 2


def test_in_memory_live_state_gateway_rejects_older_snapshot() -> None:
    gateway = InMemoryLiveStateGateway()
    gateway.put_snapshot(_snapshot(2))
    with pytest.raises(ValueError, match="older offset"):
        gateway.put_snapshot(_snapshot(1))


def test_in_memory_live_state_gateway_accepts_idempotent_same_snapshot() -> None:
    gateway = InMemoryLiveStateGateway()
    snapshot = _snapshot(2)
    gateway.put_snapshot(snapshot)
    gateway.put_snapshot(snapshot)
    assert gateway.get_snapshot(snapshot.snapshot_id) == snapshot


def test_in_memory_live_state_gateway_rejects_same_offset_different_hash() -> None:
    gateway = InMemoryLiveStateGateway()
    gateway.put_snapshot(_snapshot(2))
    with pytest.raises(ValueError, match="different payload hash"):
        gateway.put_snapshot(_snapshot(2, {"offset": 2, "revision": 2}))


def test_in_memory_checkpoint_store_advances_checkpoint() -> None:
    store = InMemoryDbWriterCheckpointStore()
    store.save_checkpoint(_checkpoint(1))
    store.save_checkpoint(_checkpoint(2))
    loaded = store.get_checkpoint(STREAM, PARTITION)
    assert loaded is not None
    assert loaded.persisted_until_offset == 2


def test_in_memory_checkpoint_store_rejects_backwards_checkpoint() -> None:
    store = InMemoryDbWriterCheckpointStore()
    store.save_checkpoint(_checkpoint(2))
    with pytest.raises(ValueError, match="backwards"):
        store.save_checkpoint(_checkpoint(1))


def test_historical_state_reader_returns_ordered_slice() -> None:
    reader = InMemoryHistoricalStateReader(
        slice_id=HistoricalStateSliceId("history-1"),
        events=(_event(3), _event(1), _event(2)),
    )
    historical = reader.read_slice(STREAM, PARTITION, 1, 3)
    assert [event.stream_position.offset for event in historical.events] == [1, 2, 3]
    assert historical.is_gap_free


def test_historical_state_reader_empty_slice_uses_explicit_boundary_position() -> None:
    reader = InMemoryHistoricalStateReader(
        slice_id=HistoricalStateSliceId("history-empty"),
        events=(),
        empty_slice_position=_position(100),
    )
    historical = reader.read_slice(STREAM, PARTITION, 101, 101)
    assert historical.events == ()
    assert historical.persisted_until_position.offset == 100
    assert historical.from_offset == 101
    assert historical.to_offset == 101
