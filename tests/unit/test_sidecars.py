from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from futures_bot.domain.broker import KafkaPartitionOffset
from futures_bot.domain.ids import (
    BatchId,
    BrokerTopicId,
    ConsumerId,
    EventId,
    RunId,
    SidecarId,
    WalSegmentId,
)
from futures_bot.domain.journal import WalOffset, WalOffsetRange
from futures_bot.domain.sidecars import (
    DbWriterCheckpoint,
    RequiredConsumerCheckpointSet,
    RuntimeBackpressureDecision,
    RuntimeBackpressureState,
    SidecarCheckpoint,
    SidecarKind,
    WalGcAction,
    WalGcDecision,
    WalRelayCheckpoint,
    decide_wal_gc,
)
from futures_bot.domain.wal import WalSegmentMetadata, WalSegmentStatus


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _topic() -> BrokerTopicId:
    return BrokerTopicId("events.topic")


def _kafka_offset(offset: int = 42) -> KafkaPartitionOffset:
    return KafkaPartitionOffset(topic=_topic(), partition=0, offset=offset)


def _checkpoint(
    sidecar_id: str = "sidecar-1",
    run_id: str = "run-1",
    offset: int = 0,
    required: bool = False,
    kind: SidecarKind = SidecarKind.DB_WRITER,
) -> SidecarCheckpoint:
    return SidecarCheckpoint(
        sidecar_id=SidecarId(sidecar_id),
        sidecar_kind=kind,
        run_id=RunId(run_id),
        last_committed_wal_offset=WalOffset(value=offset),
        updated_at=_utc(),
        is_required_for_wal_gc=required,
    )


def _sealed_segment(first: int = 0, last: int = 4) -> WalSegmentMetadata:
    event_count = last - first + 1
    return WalSegmentMetadata(
        segment_id=WalSegmentId("seg-1"),
        run_id=RunId("run-1"),
        status=WalSegmentStatus.SEALED,
        offset_range=WalOffsetRange(
            first=WalOffset(value=first), last=WalOffset(value=last)
        ),
        created_at=_utc(0),
        sealed_at=_utc(1),
        event_count=event_count,
    )


def _open_segment() -> WalSegmentMetadata:
    return WalSegmentMetadata(
        segment_id=WalSegmentId("seg-open"),
        run_id=RunId("run-1"),
        status=WalSegmentStatus.OPEN,
        created_at=_utc(),
    )


def _deleted_segment() -> WalSegmentMetadata:
    return WalSegmentMetadata(
        segment_id=WalSegmentId("seg-deleted"),
        run_id=RunId("run-1"),
        status=WalSegmentStatus.DELETED,
        offset_range=WalOffsetRange(
            first=WalOffset(value=0), last=WalOffset(value=4)
        ),
        created_at=_utc(0),
        sealed_at=_utc(1),
        event_count=5,
    )


# ── SidecarCheckpoint ──────────────────────────────────────────────────────────

def test_sidecar_checkpoint_accepts_valid_input() -> None:
    cp = _checkpoint(offset=10, required=True)
    assert cp.last_committed_wal_offset.value == 10
    assert cp.is_required_for_wal_gc is True


def test_sidecar_checkpoint_normalizes_updated_at_to_utc() -> None:
    tz_plus3 = timezone(timedelta(hours=3))
    cp = SidecarCheckpoint(
        sidecar_id=SidecarId("s-1"),
        sidecar_kind=SidecarKind.DB_WRITER,
        run_id=RunId("run-1"),
        last_committed_wal_offset=WalOffset(value=0),
        updated_at=datetime(2026, 1, 1, 12, 0, tzinfo=tz_plus3),
    )
    assert cp.updated_at.tzinfo is UTC
    assert cp.updated_at.hour == 9


def test_sidecar_checkpoint_rejects_naive_updated_at() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        SidecarCheckpoint(
            sidecar_id=SidecarId("s-1"),
            sidecar_kind=SidecarKind.DB_WRITER,
            run_id=RunId("run-1"),
            last_committed_wal_offset=WalOffset(value=0),
            updated_at=datetime(2026, 1, 1),
        )


def test_can_advance_to_accepts_same_and_forward_offset() -> None:
    cp = _checkpoint(offset=10)
    assert cp.can_advance_to(WalOffset(value=10))
    assert cp.can_advance_to(WalOffset(value=11))


def test_can_advance_to_rejects_backwards_movement() -> None:
    cp = _checkpoint(offset=10)
    assert not cp.can_advance_to(WalOffset(value=9))
    assert not cp.can_advance_to(WalOffset(value=0))


# ── WalRelayCheckpoint ─────────────────────────────────────────────────────────

def test_wal_relay_checkpoint_validates_updated_at() -> None:
    wrc = WalRelayCheckpoint(
        relay_id=SidecarId("relay-1"),
        run_id=RunId("run-1"),
        last_published_wal_offset=WalOffset(value=50),
        last_published_event_id=EventId("evt-50"),
        kafka_offset=_kafka_offset(50),
        updated_at=_utc(),
    )
    assert wrc.last_published_wal_offset.value == 50


def test_wal_relay_checkpoint_rejects_naive_updated_at() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        WalRelayCheckpoint(
            relay_id=SidecarId("relay-1"),
            run_id=RunId("run-1"),
            last_published_wal_offset=WalOffset(value=50),
            last_published_event_id=EventId("evt-50"),
            kafka_offset=_kafka_offset(50),
            updated_at=datetime(2026, 1, 1),
        )


# ── DbWriterCheckpoint ─────────────────────────────────────────────────────────

def test_db_writer_checkpoint_accepts_valid_input() -> None:
    dbc = DbWriterCheckpoint(
        consumer_id=ConsumerId("consumer-1"),
        run_id=RunId("run-1"),
        last_committed_wal_offset=WalOffset(value=100),
        last_committed_event_id=EventId("evt-100"),
        kafka_offset=_kafka_offset(100),
        db_transaction_id="txn-abc123",
        batch_id=BatchId("batch-1"),
        updated_at=_utc(),
    )
    assert dbc.db_transaction_id == "txn-abc123"


def test_db_writer_checkpoint_rejects_empty_db_transaction_id() -> None:
    with pytest.raises(ValidationError, match="db_transaction_id"):
        DbWriterCheckpoint(
            consumer_id=ConsumerId("consumer-1"),
            run_id=RunId("run-1"),
            last_committed_wal_offset=WalOffset(value=0),
            last_committed_event_id=EventId("evt-1"),
            kafka_offset=_kafka_offset(),
            db_transaction_id="",
            batch_id=BatchId("batch-1"),
            updated_at=_utc(),
        )


def test_db_writer_checkpoint_rejects_whitespace_db_transaction_id() -> None:
    with pytest.raises(ValidationError, match="db_transaction_id"):
        DbWriterCheckpoint(
            consumer_id=ConsumerId("consumer-1"),
            run_id=RunId("run-1"),
            last_committed_wal_offset=WalOffset(value=0),
            last_committed_event_id=EventId("evt-1"),
            kafka_offset=_kafka_offset(),
            db_transaction_id=" txn ",
            batch_id=BatchId("batch-1"),
            updated_at=_utc(),
        )


# ── RequiredConsumerCheckpointSet ──────────────────────────────────────────────

def test_checkpoint_set_accepts_valid_checkpoints() -> None:
    cs = RequiredConsumerCheckpointSet(
        run_id=RunId("run-1"),
        checkpoints=(
            _checkpoint("s-1", "run-1", 10, required=True),
            _checkpoint("s-2", "run-1", 20, required=True),
        ),
    )
    assert len(cs.required_checkpoints()) == 2


def test_checkpoint_set_rejects_duplicate_sidecar_id() -> None:
    with pytest.raises(ValidationError, match="duplicate sidecar_id"):
        RequiredConsumerCheckpointSet(
            run_id=RunId("run-1"),
            checkpoints=(
                _checkpoint("same-id", "run-1"),
                _checkpoint("same-id", "run-1"),
            ),
        )


def test_checkpoint_set_rejects_mismatched_run_id() -> None:
    with pytest.raises(ValidationError, match="run_id must match"):
        RequiredConsumerCheckpointSet(
            run_id=RunId("run-1"),
            checkpoints=(_checkpoint("s-1", "run-OTHER"),),
        )


def test_required_min_offset_returns_minimum_of_required_checkpoints() -> None:
    cs = RequiredConsumerCheckpointSet(
        run_id=RunId("run-1"),
        checkpoints=(
            _checkpoint("s-1", "run-1", 50, required=True),
            _checkpoint("s-2", "run-1", 30, required=True),
            _checkpoint("s-3", "run-1", 200, required=False),  # not required
        ),
    )
    min_offset = cs.required_min_offset()
    assert min_offset is not None
    assert min_offset.value == 30


def test_required_min_offset_returns_none_when_no_required_checkpoints() -> None:
    cs = RequiredConsumerCheckpointSet(
        run_id=RunId("run-1"),
        checkpoints=(_checkpoint("s-1", "run-1", 100, required=False),),
    )
    assert cs.required_min_offset() is None


def test_all_required_consumers_reached_returns_false_with_no_required() -> None:
    cs = RequiredConsumerCheckpointSet(run_id=RunId("run-1"))
    assert cs.all_required_consumers_reached(WalOffset(value=0)) is False


def test_all_required_consumers_reached_true_when_all_past_offset() -> None:
    cs = RequiredConsumerCheckpointSet(
        run_id=RunId("run-1"),
        checkpoints=(
            _checkpoint("s-1", "run-1", 10, required=True),
            _checkpoint("s-2", "run-1", 15, required=True),
        ),
    )
    # Both s-1 (10) and s-2 (15) are >= 10 → True
    assert cs.all_required_consumers_reached(WalOffset(value=10)) is True
    # s-1 is at 10, which is < 11 → False (not all have reached 11)
    assert cs.all_required_consumers_reached(WalOffset(value=11)) is False
    # s-1 is at 10 < 15 → False
    assert cs.all_required_consumers_reached(WalOffset(value=15)) is False


# ── decide_wal_gc ──────────────────────────────────────────────────────────────

def _empty_checkpoints(run_id: str = "run-1") -> RequiredConsumerCheckpointSet:
    return RequiredConsumerCheckpointSet(run_id=RunId(run_id))


def _required_checkpoints(
    offsets: list[int], run_id: str = "run-1"
) -> RequiredConsumerCheckpointSet:
    return RequiredConsumerCheckpointSet(
        run_id=RunId(run_id),
        checkpoints=tuple(
            _checkpoint(f"s-{i}", run_id, off, required=True)
            for i, off in enumerate(offsets, 1)
        ),
    )


def test_gc_open_segment_is_kept() -> None:
    decision = decide_wal_gc(_open_segment(), _empty_checkpoints(), _utc())
    assert decision.action is WalGcAction.KEEP
    assert decision.eligible is False


def test_gc_segment_without_offset_range_is_kept() -> None:
    seg = WalSegmentMetadata(
        segment_id=WalSegmentId("seg-1"),
        run_id=RunId("run-1"),
        status=WalSegmentStatus.SEALED,
        created_at=_utc(0),
        sealed_at=_utc(1),
        event_count=0,
    )
    decision = decide_wal_gc(seg, _empty_checkpoints(), _utc())
    assert decision.action is WalGcAction.KEEP


def test_gc_no_required_checkpoints_means_keep() -> None:
    decision = decide_wal_gc(_sealed_segment(0, 4), _empty_checkpoints(), _utc())
    assert decision.action is WalGcAction.KEEP
    assert "no required consumer checkpoints" in decision.reason


def test_gc_kafka_relay_progress_alone_does_not_authorize_delete() -> None:
    # A WAL_RELAY checkpoint with is_required_for_wal_gc=False must not trigger GC.
    relay_cp = SidecarCheckpoint(
        sidecar_id=SidecarId("relay-1"),
        sidecar_kind=SidecarKind.WAL_RELAY,
        run_id=RunId("run-1"),
        last_committed_wal_offset=WalOffset(value=9999),
        updated_at=_utc(),
        is_required_for_wal_gc=False,
    )
    checkpoints = RequiredConsumerCheckpointSet(
        run_id=RunId("run-1"),
        checkpoints=(relay_cp,),
    )
    decision = decide_wal_gc(_sealed_segment(0, 4), checkpoints, _utc())
    assert decision.action is WalGcAction.KEEP
    assert decision.eligible is False


def test_gc_segment_eligible_only_when_all_required_consumers_reached() -> None:
    segment = _sealed_segment(first=0, last=4)  # last offset = 4
    # One consumer at offset 3 (below segment last=4) → KEEP
    decision = decide_wal_gc(segment, _required_checkpoints([10, 3]), _utc())
    assert decision.action is WalGcAction.KEEP

    # Both consumers at offset >= 4 → eligible
    decision = decide_wal_gc(segment, _required_checkpoints([4, 5]), _utc())
    assert decision.action is WalGcAction.ARCHIVE
    assert decision.eligible is True


def test_gc_archive_instead_of_delete_true_returns_archive() -> None:
    segment = _sealed_segment(first=0, last=4)
    decision = decide_wal_gc(
        segment, _required_checkpoints([10, 10]), _utc(), archive_instead_of_delete=True
    )
    assert decision.action is WalGcAction.ARCHIVE


def test_gc_archive_instead_of_delete_false_returns_delete() -> None:
    segment = _sealed_segment(first=0, last=4)
    decision = decide_wal_gc(
        segment, _required_checkpoints([10, 10]), _utc(), archive_instead_of_delete=False
    )
    assert decision.action is WalGcAction.DELETE


def test_gc_deleted_segment_is_kept() -> None:
    decision = decide_wal_gc(_deleted_segment(), _required_checkpoints([9999]), _utc())
    assert decision.action is WalGcAction.KEEP
    assert "already DELETED" in decision.reason


def test_gc_mismatched_run_id_keeps_segment_even_with_sufficient_offsets() -> None:
    segment = _sealed_segment(first=0, last=4)  # run_id="run-1"
    wrong_checkpoints = _required_checkpoints([9999], run_id="run-OTHER")
    decision = decide_wal_gc(segment, wrong_checkpoints, _utc())
    assert decision.action is WalGcAction.KEEP
    assert decision.eligible is False
    assert "run_id" in decision.reason


def test_gc_mismatched_run_id_reason_names_both_run_ids() -> None:
    segment = _sealed_segment(first=0, last=4)
    wrong_checkpoints = _required_checkpoints([9999], run_id="run-OTHER")
    decision = decide_wal_gc(segment, wrong_checkpoints, _utc())
    assert "run-1" in decision.reason
    assert "run-OTHER" in decision.reason


def test_gc_mismatched_run_id_does_not_delete_regardless_of_flag() -> None:
    segment = _sealed_segment(first=0, last=4)
    wrong_checkpoints = _required_checkpoints([9999], run_id="run-OTHER")
    for flag in (True, False):
        decision = decide_wal_gc(
            segment, wrong_checkpoints, _utc(), archive_instead_of_delete=flag
        )
        assert decision.action is WalGcAction.KEEP


def test_gc_eligible_decision_carries_required_checkpoint_min_offset() -> None:
    segment = _sealed_segment(first=0, last=4)
    checkpoints = _required_checkpoints([8, 12])
    decision = decide_wal_gc(segment, checkpoints, _utc())
    assert decision.required_checkpoint_min_offset is not None
    assert decision.required_checkpoint_min_offset.value == 8


# ── WalGcDecision model invariants ─────────────────────────────────────────────

def test_wal_gc_decision_keep_requires_eligible_false() -> None:
    with pytest.raises(ValidationError, match="KEEP action requires eligible=False"):
        WalGcDecision(
            segment_id=WalSegmentId("seg-1"),
            action=WalGcAction.KEEP,
            eligible=True,
            reason="some reason",
            decided_at=_utc(),
        )


def test_wal_gc_decision_archive_requires_eligible_true_and_min_offset() -> None:
    with pytest.raises(ValidationError, match="requires required_checkpoint_min_offset"):
        WalGcDecision(
            segment_id=WalSegmentId("seg-1"),
            action=WalGcAction.ARCHIVE,
            eligible=True,
            reason="eligible",
            decided_at=_utc(),
        )


# ── RuntimeBackpressureDecision ────────────────────────────────────────────────

def test_backpressure_normal_allows_all() -> None:
    d = RuntimeBackpressureDecision(
        state=RuntimeBackpressureState.NORMAL,
        allow_new_entries=True,
        allow_exits=True,
        allow_protective_actions=True,
        reason="healthy",
    )
    assert d.allow_new_entries is True


def test_backpressure_wal_full_rejects_allow_new_entries() -> None:
    with pytest.raises(ValidationError, match="WAL_FULL requires allow_new_entries=False"):
        RuntimeBackpressureDecision(
            state=RuntimeBackpressureState.WAL_FULL,
            allow_new_entries=True,
            allow_exits=True,
            allow_protective_actions=True,
            reason="WAL is full",
        )


def test_backpressure_wal_unavailable_rejects_allow_new_entries() -> None:
    with pytest.raises(ValidationError, match="allow_new_entries=False"):
        RuntimeBackpressureDecision(
            state=RuntimeBackpressureState.WAL_UNAVAILABLE,
            allow_new_entries=True,
            allow_exits=True,
            allow_protective_actions=True,
            reason="WAL unavailable",
        )


def test_backpressure_wal_backlog_critical_rejects_allow_new_entries() -> None:
    with pytest.raises(ValidationError, match="allow_new_entries=False"):
        RuntimeBackpressureDecision(
            state=RuntimeBackpressureState.WAL_BACKLOG_CRITICAL,
            allow_new_entries=True,
            allow_exits=False,
            allow_protective_actions=True,
            reason="critical backlog",
        )


def test_backpressure_critical_states_may_still_allow_exits_and_protective() -> None:
    for state in (
        RuntimeBackpressureState.WAL_FULL,
        RuntimeBackpressureState.WAL_UNAVAILABLE,
        RuntimeBackpressureState.WAL_BACKLOG_CRITICAL,
    ):
        d = RuntimeBackpressureDecision(
            state=state,
            allow_new_entries=False,
            allow_exits=True,
            allow_protective_actions=True,
            reason="blocked",
        )
        assert d.allow_exits is True
        assert d.allow_protective_actions is True


# ── GC authority guard ─────────────────────────────────────────────────────────


def test_wal_relay_checkpoint_with_gc_required_raises() -> None:
    with pytest.raises(ValidationError, match="WAL_RELAY"):
        SidecarCheckpoint(
            sidecar_id=SidecarId("relay-1"),
            sidecar_kind=SidecarKind.WAL_RELAY,
            run_id=RunId("run-1"),
            last_committed_wal_offset=WalOffset(value=0),
            updated_at=_utc(),
            is_required_for_wal_gc=True,
        )


def test_wal_relay_checkpoint_without_gc_required_is_valid() -> None:
    cp = SidecarCheckpoint(
        sidecar_id=SidecarId("relay-1"),
        sidecar_kind=SidecarKind.WAL_RELAY,
        run_id=RunId("run-1"),
        last_committed_wal_offset=WalOffset(value=0),
        updated_at=_utc(),
        is_required_for_wal_gc=False,
    )
    assert cp.is_required_for_wal_gc is False


def test_db_writer_checkpoint_with_gc_required_is_valid() -> None:
    cp = SidecarCheckpoint(
        sidecar_id=SidecarId("db-1"),
        sidecar_kind=SidecarKind.DB_WRITER,
        run_id=RunId("run-1"),
        last_committed_wal_offset=WalOffset(value=0),
        updated_at=_utc(),
        is_required_for_wal_gc=True,
    )
    assert cp.is_required_for_wal_gc is True


# ── ARCHIVED guard in decide_wal_gc ───────────────────────────────────────────


def _archived_segment() -> WalSegmentMetadata:
    return WalSegmentMetadata(
        segment_id=WalSegmentId("seg-archived"),
        run_id=RunId("run-1"),
        status=WalSegmentStatus.ARCHIVED,
        offset_range=WalOffsetRange(
            first=WalOffset(value=0), last=WalOffset(value=4)
        ),
        created_at=_utc(0),
        sealed_at=_utc(1),
        event_count=5,
    )


def test_gc_archived_segment_is_kept() -> None:
    decision = decide_wal_gc(_archived_segment(), _required_checkpoints([9999]), _utc())
    assert decision.action is WalGcAction.KEEP
    assert decision.eligible is False
    assert "ARCHIVED" in decision.reason


def test_gc_archived_segment_kept_regardless_of_delete_flag() -> None:
    for flag in (True, False):
        decision = decide_wal_gc(
            _archived_segment(),
            _required_checkpoints([9999]),
            _utc(),
            archive_instead_of_delete=flag,
        )
        assert decision.action is WalGcAction.KEEP
