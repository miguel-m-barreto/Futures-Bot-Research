from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from futures_bot.domain.event_journal import (
    EventJournalCheckpoint,
    EventJournalContinuityStatus,
    EventJournalReadinessPolicy,
    EventJournalRecord,
    EventJournalRecordKind,
    EventJournalSourceHealth,
    EventJournalSourceKind,
    EventJournalSourceTrust,
    EventJournalStreamId,
)
from futures_bot.event_journal.in_memory import (
    InMemoryEventJournalCheckpointStore,
    InMemoryEventJournalReadinessPolicyStore,
    InMemoryEventJournalRecordStore,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
STREAM_ID = EventJournalStreamId("event-journal-stream:" + "a" * 64)


def _record(**overrides: object) -> EventJournalRecord:
    values = {
        "stream_id": STREAM_ID,
        "record_kind": EventJournalRecordKind.MARKET_DATA_OBSERVATION,
        "sequence_number": 101,
        "previous_sequence_number": 100,
        "payload_type": "MarketDataObservationSnapshot",
        "payload_hash": "sha256:" + "b" * 64,
        "occurred_at": NOW,
        "recorded_at": NOW,
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
        "checkpointed_at": NOW,
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
        "allowed_source_kinds": (EventJournalSourceKind.SYSTEM_GENERATED_RECORD,),
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


def test_record_store_put_get_idempotent_and_conflict() -> None:
    store = InMemoryEventJournalRecordStore()
    record = _record()
    if record.record_id is None:
        raise AssertionError("record_id was not assigned")

    store.put(record)
    store.put(record)

    assert store.get(record.record_id) == record

    conflict = record.model_copy(update={"payload_hash": "sha256:" + "c" * 64})
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)


def test_record_store_rejects_same_stream_sequence_different_record() -> None:
    store = InMemoryEventJournalRecordStore()
    first = _record()
    second = _record(payload_hash="sha256:" + "c" * 64, idempotency_key="idem-2")

    store.put(first)

    with pytest.raises(ValueError, match="sequence collision"):
        store.put(second)


def test_record_store_lists_by_id_stream_order_and_latest() -> None:
    store = InMemoryEventJournalRecordStore()
    older = _record(sequence_number=100, previous_sequence_number=99, idempotency_key="a")
    newer = _record(
        sequence_number=101,
        previous_sequence_number=100,
        idempotency_key="b",
        recorded_at=NOW + timedelta(seconds=1),
    )

    store.put(newer)
    store.put(older)

    assert store.list_records() == tuple(
        sorted((older, newer), key=lambda item: str(item.record_id))
    )
    assert store.list_by_stream(STREAM_ID) == (older, newer)
    assert store.latest_for_stream(STREAM_ID) == newer


def test_checkpoint_store_put_get_and_lists_by_id() -> None:
    store = InMemoryEventJournalCheckpointStore()
    first = _checkpoint()
    second = _checkpoint(last_sequence_number=101, source_record_id="checkpoint-source-2")
    if first.checkpoint_id is None:
        raise AssertionError("checkpoint_id was not assigned")

    store.put(second)
    store.put(first)
    store.put(first)

    assert store.get(first.checkpoint_id) == first
    assert store.list_checkpoints() == tuple(
        sorted((first, second), key=lambda item: str(item.checkpoint_id))
    )

    conflict = first.model_copy(update={"last_sequence_number": 1})
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)


def test_policy_store_put_get_and_lists_by_id() -> None:
    store = InMemoryEventJournalReadinessPolicyStore()
    first = _policy()
    second = _policy(require_checkpoint=False)
    if first.policy_id is None:
        raise AssertionError("policy_id was not assigned")

    store.put(second)
    store.put(first)
    store.put(first)

    assert store.get(first.policy_id) == first
    assert store.list_policies() == tuple(
        sorted((first, second), key=lambda item: str(item.policy_id))
    )

    conflict = first.model_copy(update={"max_record_age": 1})
    with pytest.raises(ValueError, match="collision"):
        store.put(conflict)
