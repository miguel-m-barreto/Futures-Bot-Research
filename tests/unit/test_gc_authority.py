"""GC authority guardrail tests.

Proves that only RequiredConsumerCheckpointSet with at least one required
DB_WRITER checkpoint that has reached the segment end offset can authorize
WAL GC.  WalRelayCheckpoint, KafkaPublishAck, and WAL_RELAY sidecar
checkpoints cannot authorize GC by themselves.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import RunId, SidecarId, WalSegmentId
from futures_bot.domain.journal import WalOffset, WalOffsetRange
from futures_bot.domain.sidecars import (
    RequiredConsumerCheckpointSet,
    SidecarCheckpoint,
    SidecarKind,
    WalGcAction,
    decide_wal_gc,
)
from futures_bot.domain.wal import WalSegmentMetadata, WalSegmentStatus
from futures_bot.infrastructure.checkpoints.in_memory import (
    InMemoryRequiredConsumerCheckpointStore,
)


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _sealed_segment(first: int = 0, last: int = 4, run_id: str = "run-1") -> WalSegmentMetadata:
    return WalSegmentMetadata(
        segment_id=WalSegmentId("seg-1"),
        run_id=RunId(run_id),
        status=WalSegmentStatus.SEALED,
        offset_range=WalOffsetRange(
            first=WalOffset(value=first), last=WalOffset(value=last)
        ),
        created_at=_utc(),
        sealed_at=_utc(),
        event_count=last - first + 1,
    )


def _db_writer_cp(
    sidecar_id: str,
    run_id: str = "run-1",
    offset: int = 0,
    required: bool = True,
) -> SidecarCheckpoint:
    return SidecarCheckpoint(
        sidecar_id=SidecarId(sidecar_id),
        sidecar_kind=SidecarKind.DB_WRITER,
        run_id=RunId(run_id),
        last_committed_wal_offset=WalOffset(value=offset),
        updated_at=_utc(),
        is_required_for_wal_gc=required,
    )


def _wal_relay_cp(
    sidecar_id: str = "relay-1",
    run_id: str = "run-1",
    offset: int = 9999,
) -> SidecarCheckpoint:
    return SidecarCheckpoint(
        sidecar_id=SidecarId(sidecar_id),
        sidecar_kind=SidecarKind.WAL_RELAY,
        run_id=RunId(run_id),
        last_committed_wal_offset=WalOffset(value=offset),
        updated_at=_utc(),
        is_required_for_wal_gc=False,  # must be False for WAL_RELAY
    )


# ── Test 1: WAL_RELAY cannot be loaded as a required checkpoint ───────────────

def test_wal_relay_sidecar_checkpoint_is_not_required() -> None:
    # A WAL_RELAY SidecarCheckpoint stored at offset 9999 (well past segment end)
    # must not appear in required_checkpoints().
    store = InMemoryRequiredConsumerCheckpointStore(
        checkpoints=(_wal_relay_cp(offset=9999),)
    )
    result = store.load_required_checkpoints(RunId("run-1"))
    assert _wal_relay_cp().sidecar_id not in {
        cp.sidecar_id for cp in result.required_checkpoints()
    }
    assert result.required_checkpoints() == ()


# ── Test 2: WAL_RELAY sidecar alone cannot authorize decide_wal_gc ────────────

def test_wal_relay_sidecar_alone_cannot_authorize_gc() -> None:
    store = InMemoryRequiredConsumerCheckpointStore(
        checkpoints=(_wal_relay_cp(offset=9999),)
    )
    checkpoints = store.load_required_checkpoints(RunId("run-1"))
    decision = decide_wal_gc(_sealed_segment(0, 4), checkpoints, _utc())
    assert decision.action is WalGcAction.KEEP
    assert decision.eligible is False
    assert "no required consumer checkpoints" in decision.reason


# ── Test 3: KafkaPublishAck alone cannot authorize decide_wal_gc ──────────────

def test_kafka_publish_ack_alone_cannot_authorize_gc() -> None:
    # decide_wal_gc takes no KafkaPublishAck argument.
    # Even if the relay has published everything, with no required consumer
    # checkpoint the decision is always KEEP.
    empty_store = InMemoryRequiredConsumerCheckpointStore()
    checkpoints = empty_store.load_required_checkpoints(RunId("run-1"))
    decision = decide_wal_gc(_sealed_segment(0, 4), checkpoints, _utc())
    assert decision.action is WalGcAction.KEEP
    assert decision.eligible is False


# ── Test 4: required DB_WRITER at/beyond segment end authorizes ARCHIVE ───────

def test_required_db_writer_at_segment_end_authorizes_archive() -> None:
    segment = _sealed_segment(first=0, last=4)
    store = InMemoryRequiredConsumerCheckpointStore(
        checkpoints=(_db_writer_cp("db-1", offset=4, required=True),)
    )
    checkpoints = store.load_required_checkpoints(RunId("run-1"))
    decision = decide_wal_gc(segment, checkpoints, _utc())
    assert decision.eligible is True
    assert decision.action is WalGcAction.ARCHIVE


def test_required_db_writer_beyond_segment_end_authorizes_archive() -> None:
    segment = _sealed_segment(first=0, last=4)
    store = InMemoryRequiredConsumerCheckpointStore(
        checkpoints=(_db_writer_cp("db-1", offset=100, required=True),)
    )
    checkpoints = store.load_required_checkpoints(RunId("run-1"))
    decision = decide_wal_gc(segment, checkpoints, _utc())
    assert decision.eligible is True
    assert decision.action is WalGcAction.ARCHIVE


# ── Test 5: required DB_WRITER behind segment end keeps segment ───────────────

def test_required_db_writer_behind_segment_end_keeps_segment() -> None:
    segment = _sealed_segment(first=0, last=4)
    store = InMemoryRequiredConsumerCheckpointStore(
        checkpoints=(_db_writer_cp("db-1", offset=3, required=True),)
    )
    checkpoints = store.load_required_checkpoints(RunId("run-1"))
    decision = decide_wal_gc(segment, checkpoints, _utc())
    assert decision.action is WalGcAction.KEEP
    assert decision.eligible is False


# ── Test 6: only WAL_RELAY checkpoint → no required consumers → KEEP ─────────

def test_only_wal_relay_checkpoint_cannot_authorize_archive() -> None:
    segment = _sealed_segment(first=0, last=4)
    checkpoints = RequiredConsumerCheckpointSet(
        run_id=RunId("run-1"),
        checkpoints=(_wal_relay_cp(offset=9999),),
    )
    decision = decide_wal_gc(segment, checkpoints, _utc())
    assert decision.action is WalGcAction.KEEP
    assert "no required consumer checkpoints" in decision.reason


# ── Test 7: WAL_RELAY with is_required_for_wal_gc=True is rejected ────────────

def test_wal_relay_required_flag_rejected_by_model() -> None:
    with pytest.raises(ValidationError, match="WAL_RELAY"):
        SidecarCheckpoint(
            sidecar_id=SidecarId("relay-1"),
            sidecar_kind=SidecarKind.WAL_RELAY,
            run_id=RunId("run-1"),
            last_committed_wal_offset=WalOffset(value=0),
            updated_at=_utc(),
            is_required_for_wal_gc=True,
        )


# ── Test 8: multiple required consumers ──────────────────────────────────────

def test_multiple_required_all_reached_authorizes_archive() -> None:
    segment = _sealed_segment(first=0, last=4)
    store = InMemoryRequiredConsumerCheckpointStore(
        checkpoints=(
            _db_writer_cp("db-1", offset=5, required=True),
            _db_writer_cp("db-2", offset=4, required=True),
        )
    )
    checkpoints = store.load_required_checkpoints(RunId("run-1"))
    decision = decide_wal_gc(segment, checkpoints, _utc())
    assert decision.eligible is True
    assert decision.action is WalGcAction.ARCHIVE


def test_multiple_required_one_behind_keeps_segment() -> None:
    segment = _sealed_segment(first=0, last=4)
    store = InMemoryRequiredConsumerCheckpointStore(
        checkpoints=(
            _db_writer_cp("db-1", offset=10, required=True),
            _db_writer_cp("db-2", offset=3, required=True),  # behind segment last=4
        )
    )
    checkpoints = store.load_required_checkpoints(RunId("run-1"))
    decision = decide_wal_gc(segment, checkpoints, _utc())
    assert decision.action is WalGcAction.KEEP
    assert decision.eligible is False


# ── Test 9: optional/non-required consumers do not block GC ──────────────────

def test_optional_consumer_does_not_block_gc_when_required_reached() -> None:
    segment = _sealed_segment(first=0, last=4)
    store = InMemoryRequiredConsumerCheckpointStore(
        checkpoints=(
            _db_writer_cp("db-required", offset=5, required=True),
            # optional consumer far behind — must NOT block GC
            _db_writer_cp("db-optional", offset=0, required=False),
        )
    )
    checkpoints = store.load_required_checkpoints(RunId("run-1"))
    # optional consumer at offset 0 must not prevent archive
    decision = decide_wal_gc(segment, checkpoints, _utc())
    assert decision.eligible is True
    assert decision.action is WalGcAction.ARCHIVE


# ── Test 10: empty RequiredConsumerCheckpointSet does not authorize archive ───

def test_empty_checkpoint_set_does_not_authorize_archive() -> None:
    segment = _sealed_segment(first=0, last=4)
    checkpoints = RequiredConsumerCheckpointSet(run_id=RunId("run-1"))
    decision = decide_wal_gc(segment, checkpoints, _utc())
    assert decision.action is WalGcAction.KEEP
    assert decision.eligible is False
    assert "no required consumer checkpoints" in decision.reason


# ── Additional store-integration GC tests ────────────────────────────────────

def test_gc_uses_store_checkpoints_not_relay_checkpoint() -> None:
    # Build a scenario with both a WAL_RELAY (non-required) and a required DB_WRITER.
    # GC eligibility must come from the DB_WRITER only.
    segment = _sealed_segment(first=0, last=4)
    store = InMemoryRequiredConsumerCheckpointStore(
        checkpoints=(
            _wal_relay_cp("relay-1", offset=9999),
            _db_writer_cp("db-1", offset=4, required=True),
        )
    )
    checkpoints = store.load_required_checkpoints(RunId("run-1"))
    decision = decide_wal_gc(segment, checkpoints, _utc())
    # Eligible because DB_WRITER (not relay) reached the end.
    assert decision.eligible is True
    # The required_checkpoint_min_offset reflects the DB_WRITER offset, not 9999.
    assert decision.required_checkpoint_min_offset is not None
    assert decision.required_checkpoint_min_offset.value == 4


def test_gc_min_offset_is_slowest_required_consumer() -> None:
    segment = _sealed_segment(first=0, last=4)
    store = InMemoryRequiredConsumerCheckpointStore(
        checkpoints=(
            _db_writer_cp("db-fast", offset=20, required=True),
            _db_writer_cp("db-slow", offset=5, required=True),
        )
    )
    checkpoints = store.load_required_checkpoints(RunId("run-1"))
    decision = decide_wal_gc(segment, checkpoints, _utc())
    assert decision.eligible is True
    assert decision.required_checkpoint_min_offset is not None
    assert decision.required_checkpoint_min_offset.value == 5
