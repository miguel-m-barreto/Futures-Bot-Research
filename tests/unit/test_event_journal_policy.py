from __future__ import annotations

from datetime import UTC, datetime, timedelta

from futures_bot.domain.event_journal import (
    EventJournalCheckpoint,
    EventJournalContinuityStatus,
    EventJournalReadinessPolicy,
    EventJournalReadinessReason,
    EventJournalRecord,
    EventJournalRecordKind,
    EventJournalSourceHealth,
    EventJournalSourceKind,
    EventJournalSourceTrust,
    EventJournalStreamId,
)
from futures_bot.event_journal.policies import evaluate_event_journal_readiness

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
STREAM_ID = EventJournalStreamId("event-journal-stream:" + "a" * 64)
OTHER_STREAM_ID = EventJournalStreamId("event-journal-stream:" + "b" * 64)


def _record(**overrides: object) -> EventJournalRecord:
    values = {
        "stream_id": STREAM_ID,
        "record_kind": EventJournalRecordKind.MARKET_DATA_OBSERVATION,
        "sequence_number": 101,
        "previous_sequence_number": 100,
        "payload_type": "MarketDataObservationSnapshot",
        "payload_hash": "sha256:" + "b" * 64,
        "occurred_at": NOW - timedelta(seconds=1),
        "recorded_at": NOW - timedelta(seconds=1),
        "source_kind": EventJournalSourceKind.SYSTEM_GENERATED_RECORD,
        "source_trust": EventJournalSourceTrust.SYSTEM_GENERATED,
        "source_health": EventJournalSourceHealth.HEALTHY,
        "continuity_status": EventJournalContinuityStatus.CONTINUOUS,
        "source_record_id": "source-record-1",
        "idempotency_key": "idem-1",
        "metadata": {},
    }
    values.update(overrides)
    return EventJournalRecord(**values)


def _checkpoint(**overrides: object) -> EventJournalCheckpoint:
    values = {
        "stream_id": STREAM_ID,
        "last_sequence_number": 100,
        "checkpointed_at": NOW - timedelta(seconds=1),
        "source_kind": EventJournalSourceKind.SYSTEM_GENERATED_RECORD,
        "source_trust": EventJournalSourceTrust.SYSTEM_GENERATED,
        "source_health": EventJournalSourceHealth.HEALTHY,
        "source_record_id": "checkpoint-source-1",
        "metadata": {},
    }
    values.update(overrides)
    return EventJournalCheckpoint(**values)


def _policy(**overrides: object) -> EventJournalReadinessPolicy:
    values = {
        "max_record_age": 5_000,
        "require_source_record": True,
        "allowed_source_kinds": (
            EventJournalSourceKind.SYSTEM_GENERATED_RECORD,
            EventJournalSourceKind.LOCAL_IN_MEMORY_JOURNAL,
        ),
        "allowed_source_trust": (EventJournalSourceTrust.SYSTEM_GENERATED,),
        "allowed_source_health": (EventJournalSourceHealth.HEALTHY,),
        "allowed_record_kinds": (EventJournalRecordKind.MARKET_DATA_OBSERVATION,),
        "allowed_continuity_statuses": (EventJournalContinuityStatus.CONTINUOUS,),
        "require_sequence": True,
        "require_previous_sequence": True,
        "require_contiguous_sequence": True,
        "require_checkpoint": True,
        "require_payload_hash": True,
        "require_idempotency_key": True,
        "metadata": {},
    }
    values.update(overrides)
    return EventJournalReadinessPolicy(**values)


def _evaluate(  # noqa: PLR0913
    *,
    record: EventJournalRecord | None = None,
    checkpoint: EventJournalCheckpoint | None = None,
    policy: EventJournalReadinessPolicy | None = None,
    stream_id: EventJournalStreamId = STREAM_ID,
    record_kind: EventJournalRecordKind = EventJournalRecordKind.MARKET_DATA_OBSERVATION,
    expected_payload_hash: str | None = None,
):
    resolved_record = _record() if record is None else record
    return evaluate_event_journal_readiness(
        policy=_policy() if policy is None else policy,
        checked_at=NOW,
        record=resolved_record,
        checkpoint=_checkpoint() if checkpoint is None else checkpoint,
        stream_id=stream_id,
        record_kind=record_kind,
        expected_payload_hash=(
            resolved_record.payload_hash
            if expected_payload_hash is None
            else expected_payload_hash
        ),
    )


def test_strict_contiguous_market_data_journal_record_ready() -> None:
    decision = _evaluate(policy=EventJournalReadinessPolicy.strict_contiguous(metadata={}))

    assert decision.ready
    assert decision.reason is EventJournalReadinessReason.READY


def test_missing_future_and_stale_record_reject() -> None:
    missing = evaluate_event_journal_readiness(
        policy=_policy(),
        checked_at=NOW,
        record=None,
    )
    future_occurred = _evaluate(
        record=_record(
            occurred_at=NOW + timedelta(milliseconds=1),
            recorded_at=NOW + timedelta(milliseconds=1),
        ),
    )
    future_recorded = _evaluate(
        record=_record(recorded_at=NOW + timedelta(milliseconds=1)),
    )
    stale = _evaluate(
        policy=_policy(max_record_age=500),
        record=_record(recorded_at=NOW - timedelta(seconds=2)),
    )

    assert missing.reason is EventJournalReadinessReason.RECORD_MISSING
    assert future_occurred.reason is EventJournalReadinessReason.RECORD_FUTURE_DATED
    assert future_recorded.reason is EventJournalReadinessReason.RECORD_FUTURE_DATED
    assert stale.reason is EventJournalReadinessReason.RECORD_STALE


def test_source_gates_reject() -> None:
    unknown_kind = _evaluate(record=_record(source_kind=EventJournalSourceKind.UNKNOWN))
    test_fixture_kind = _evaluate(
        policy=EventJournalReadinessPolicy.strict_contiguous(metadata={}),
        record=_record(source_kind=EventJournalSourceKind.TEST_FIXTURE),
    )
    untrusted = _evaluate(record=_record(source_trust=EventJournalSourceTrust.UNTRUSTED))
    unhealthy = _evaluate(record=_record(source_health=EventJournalSourceHealth.UNHEALTHY))
    gapped = _evaluate(record=_record(source_health=EventJournalSourceHealth.GAPPED))
    missing_record = _evaluate(record=_record(source_record_id=None))

    assert unknown_kind.reason is EventJournalReadinessReason.SOURCE_KIND_UNKNOWN
    assert test_fixture_kind.reason is EventJournalReadinessReason.SOURCE_KIND_UNSUPPORTED
    assert untrusted.reason is EventJournalReadinessReason.SOURCE_UNTRUSTED
    assert unhealthy.reason is EventJournalReadinessReason.SOURCE_UNHEALTHY
    assert gapped.reason is EventJournalReadinessReason.SOURCE_UNHEALTHY
    assert missing_record.reason is EventJournalReadinessReason.SOURCE_RECORD_REQUIRED


def test_kind_and_stream_gates_reject() -> None:
    unknown_kind = _evaluate(record=_record(record_kind=EventJournalRecordKind.UNKNOWN))
    unsupported_kind = _evaluate(
        policy=_policy(allowed_record_kinds=(EventJournalRecordKind.RUNTIME_CONTROL_EVENT,)),
    )
    requested_mismatch = _evaluate(record_kind=EventJournalRecordKind.RUNTIME_CONTROL_EVENT)
    stream_mismatch = _evaluate(stream_id=OTHER_STREAM_ID)

    assert unknown_kind.reason is EventJournalReadinessReason.RECORD_KIND_UNKNOWN
    assert unsupported_kind.reason is EventJournalReadinessReason.RECORD_KIND_UNSUPPORTED
    assert requested_mismatch.reason is EventJournalReadinessReason.RECORD_KIND_UNSUPPORTED
    assert stream_mismatch.reason is EventJournalReadinessReason.STREAM_ID_MISMATCH


def test_continuity_and_sequence_gates_reject() -> None:
    unknown = _evaluate(record=_record(continuity_status=EventJournalContinuityStatus.UNKNOWN))
    declared_gap = _evaluate(
        record=_record(continuity_status=EventJournalContinuityStatus.GAP_DECLARED),
    )
    suspected_gap = _evaluate(
        record=_record(continuity_status=EventJournalContinuityStatus.GAP_SUSPECTED),
    )
    missing_previous = _evaluate(record=_record(previous_sequence_number=None))
    non_contiguous = _evaluate(record=_record(sequence_number=103))

    assert unknown.reason is EventJournalReadinessReason.CONTINUITY_UNKNOWN
    assert declared_gap.reason is EventJournalReadinessReason.CONTINUITY_GAPPED
    assert suspected_gap.reason is EventJournalReadinessReason.CONTINUITY_GAPPED
    assert missing_previous.reason is EventJournalReadinessReason.PREVIOUS_SEQUENCE_MISSING
    assert non_contiguous.reason is EventJournalReadinessReason.SEQUENCE_GAP_DECLARED


def test_checkpoint_gates_reject() -> None:
    missing = evaluate_event_journal_readiness(
        policy=_policy(require_checkpoint=True),
        checked_at=NOW,
        record=_record(),
        checkpoint=None,
        stream_id=STREAM_ID,
        record_kind=EventJournalRecordKind.MARKET_DATA_OBSERVATION,
    )
    stream_mismatch = _evaluate(checkpoint=_checkpoint(stream_id=OTHER_STREAM_ID))
    ahead = _evaluate(checkpoint=_checkpoint(last_sequence_number=102))
    untrusted = _evaluate(
        checkpoint=_checkpoint(source_trust=EventJournalSourceTrust.UNTRUSTED),
    )

    assert missing.reason is EventJournalReadinessReason.CHECKPOINT_MISSING
    assert stream_mismatch.reason is (
        EventJournalReadinessReason.CHECKPOINT_STREAM_MISMATCH
    )
    assert ahead.reason is EventJournalReadinessReason.CHECKPOINT_AHEAD_OF_RECORD
    assert untrusted.reason is EventJournalReadinessReason.SOURCE_UNTRUSTED


def test_payload_and_idempotency_gates_reject() -> None:
    payload_hash_missing = _evaluate(
        record=_record().model_copy(update={"payload_hash": ""}),
    )
    payload_hash_mismatch = _evaluate(expected_payload_hash="sha256:" + "c" * 64)
    idempotency_missing = _evaluate(record=_record(idempotency_key=None))

    assert payload_hash_missing.reason is EventJournalReadinessReason.PAYLOAD_HASH_MISSING
    assert payload_hash_mismatch.reason is EventJournalReadinessReason.PAYLOAD_HASH_MISMATCH
    assert idempotency_missing.reason is EventJournalReadinessReason.IDEMPOTENCY_KEY_MISSING
