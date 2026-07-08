from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import ValidationError

from futures_bot.domain.event_journal import (
    EventJournalCheckpoint,
    EventJournalContinuityStatus,
    EventJournalReadinessCompatibility,
    EventJournalReadinessDecision,
    EventJournalReadinessPolicy,
    EventJournalReadinessReason,
    EventJournalRecord,
    EventJournalRecordKind,
    EventJournalSourceHealth,
    EventJournalSourceKind,
    EventJournalSourceTrust,
    EventJournalStreamId,
    deterministic_event_journal_checkpoint_id,
    deterministic_event_journal_readiness_decision_id,
    deterministic_event_journal_readiness_policy_id,
    deterministic_event_journal_record_id,
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


def _decision(**overrides: object) -> EventJournalReadinessDecision:
    policy = _policy()
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    values = {
        "policy_id": policy.policy_id,
        "stream_id": STREAM_ID,
        "record_kind": EventJournalRecordKind.MARKET_DATA_OBSERVATION,
        "sequence_number": 101,
        "checkpoint_id": _checkpoint().checkpoint_id,
        "ready": True,
        "reason": EventJournalReadinessReason.READY,
        "compatibility": EventJournalReadinessCompatibility.DIRECT_STREAM_MATCH,
        "record_id": _record().record_id,
        "checked_at": NOW,
        "details": {},
    }
    values.update(overrides)
    return EventJournalReadinessDecision(**values)


def test_event_journal_ids_are_deterministic() -> None:
    assert _record().record_id == _record().record_id
    assert _checkpoint().checkpoint_id == _checkpoint().checkpoint_id
    assert _policy().policy_id == _policy().policy_id
    assert _decision().decision_id == _decision().decision_id


def test_record_rejects_invalid_sequence_and_payload_identity() -> None:
    with pytest.raises(ValidationError, match="sequence"):
        _record(sequence_number=-1)
    with pytest.raises(ValidationError, match="sequence_number"):
        _record(sequence_number=1, previous_sequence_number=2)
    with pytest.raises(ValidationError, match="payload"):
        _record(payload_type="")
    with pytest.raises(ValidationError, match="payload"):
        _record(payload_hash="")


def test_checkpoint_rejects_invalid_sequence() -> None:
    with pytest.raises(ValidationError, match="last_sequence_number"):
        _checkpoint(last_sequence_number=-1)


def test_policy_rejects_invalid_gate_configuration() -> None:
    with pytest.raises(ValidationError, match="max_record_age"):
        _policy(max_record_age=0)
    with pytest.raises(ValidationError, match="allowed_source_kinds"):
        _policy(allowed_source_kinds=())
    with pytest.raises(ValidationError, match="UNKNOWN source"):
        _policy(allowed_source_kinds=(EventJournalSourceKind.UNKNOWN,))
    with pytest.raises(ValidationError, match="allowed_source_trust"):
        _policy(allowed_source_trust=())
    with pytest.raises(ValidationError, match="allowed_source_health"):
        _policy(allowed_source_health=())
    with pytest.raises(ValidationError, match="allowed_record_kinds"):
        _policy(allowed_record_kinds=())
    with pytest.raises(ValidationError, match="UNKNOWN record"):
        _policy(allowed_record_kinds=(EventJournalRecordKind.UNKNOWN,))
    with pytest.raises(ValidationError, match="allowed_continuity_statuses"):
        _policy(allowed_continuity_statuses=())


def test_strict_contiguous_and_research_fixture_source_contracts() -> None:
    strict = EventJournalReadinessPolicy.strict_contiguous(metadata={})
    fixture = EventJournalReadinessPolicy.research_fixture(metadata={})

    assert EventJournalSourceKind.TEST_FIXTURE not in strict.allowed_source_kinds
    assert EventJournalContinuityStatus.UNKNOWN not in strict.allowed_continuity_statuses
    assert strict.require_contiguous_sequence
    assert fixture.allowed_source_kinds == (EventJournalSourceKind.TEST_FIXTURE,)
    assert fixture.allowed_record_kinds == (EventJournalRecordKind.TEST_FIXTURE,)


def test_metadata_and_details_are_deeply_immutable_and_id_stable() -> None:
    record = _record(metadata={"nested": {"x": [1]}})
    checkpoint = _checkpoint(metadata={"nested": {"x": [1]}})
    policy = _policy(metadata={"nested": {"x": [1]}})
    decision = _decision(details={"nested": {"x": [1]}})

    for value in (record.metadata, checkpoint.metadata, policy.metadata, decision.details):
        with pytest.raises(TypeError):
            cast(Any, value)["nested"]["new"] = True
        with pytest.raises(AttributeError):
            cast(Any, value)["nested"]["x"].append(2)

    assert deterministic_event_journal_record_id(record) == record.record_id
    assert deterministic_event_journal_checkpoint_id(checkpoint) == checkpoint.checkpoint_id
    assert deterministic_event_journal_readiness_policy_id(policy) == policy.policy_id
    assert deterministic_event_journal_readiness_decision_id(decision) == decision.decision_id


def test_model_dump_json_thaws_metadata_and_details() -> None:
    cases = (
        (_record(metadata={"nested": {"x": [1]}}).model_dump(mode="json"), "metadata"),
        (_checkpoint(metadata={"nested": {"x": [1]}}).model_dump(mode="json"), "metadata"),
        (_policy(metadata={"nested": {"x": [1]}}).model_dump(mode="json"), "metadata"),
        (_decision(details={"nested": {"x": [1]}}).model_dump(mode="json"), "details"),
    )

    for dumped, field_name in cases:
        assert dumped[field_name] == {"nested": {"x": [1]}}
        assert isinstance(dumped[field_name]["nested"]["x"], list)


def test_decision_ready_reason_consistency() -> None:
    with pytest.raises(ValidationError, match="READY"):
        _decision(ready=True, reason=EventJournalReadinessReason.NOT_READY)
    with pytest.raises(ValidationError, match="READY"):
        _decision(ready=False, reason=EventJournalReadinessReason.READY)
    with pytest.raises(ValidationError, match="compatibility"):
        _decision(compatibility=EventJournalReadinessCompatibility.NOT_COMPATIBLE)
