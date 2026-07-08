from __future__ import annotations

from datetime import datetime

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
)
from futures_bot.domain.ids import EventJournalStreamId
from futures_bot.domain.time import ensure_aware_utc


def evaluate_event_journal_readiness(  # noqa: PLR0911, PLR0913
    *,
    policy: EventJournalReadinessPolicy,
    checked_at: datetime,
    record: EventJournalRecord | None = None,
    checkpoint: EventJournalCheckpoint | None = None,
    stream_id: EventJournalStreamId | str | None = None,
    record_kind: EventJournalRecordKind | str | None = None,
    expected_payload_hash: str | None = None,
) -> EventJournalReadinessDecision:
    checked_at = ensure_aware_utc(checked_at)
    requested_stream_id = _stream_id_or_none(stream_id)
    requested_record_kind = _record_kind_or_none(record_kind)

    if _policy_disabled(policy):
        return _decision(
            policy=policy,
            checked_at=checked_at,
            reason=EventJournalReadinessReason.POLICY_DISABLED,
            compatibility=EventJournalReadinessCompatibility.UNKNOWN,
            details={"policy_disabled": True},
        )
    if not isinstance(record, EventJournalRecord):
        return _decision(
            policy=policy,
            checked_at=checked_at,
            reason=EventJournalReadinessReason.RECORD_MISSING,
            compatibility=EventJournalReadinessCompatibility.UNKNOWN,
            details={"record_type": None if record is None else type(record).__name__},
        )

    common = _common_decision_fields(record)
    if record.occurred_at > checked_at or record.recorded_at > checked_at:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            record=record,
            reason=EventJournalReadinessReason.RECORD_FUTURE_DATED,
            details=common,
        )
    age_ms = int((checked_at - record.recorded_at).total_seconds() * 1000)
    if age_ms > policy.max_record_age:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            record=record,
            reason=EventJournalReadinessReason.RECORD_STALE,
            details=common | {"age_ms": age_ms},
        )

    source_reason = _source_reason(policy, record)
    if source_reason is not None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            record=record,
            reason=source_reason,
            compatibility=(
                EventJournalReadinessCompatibility.SOURCE_UNSUPPORTED
                if source_reason
                in {
                    EventJournalReadinessReason.SOURCE_KIND_UNKNOWN,
                    EventJournalReadinessReason.SOURCE_KIND_UNSUPPORTED,
                }
                else EventJournalReadinessCompatibility.NOT_COMPATIBLE
            ),
            details=common,
        )

    kind_reason = _kind_reason(policy, record, requested_record_kind)
    if kind_reason is not None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            record=record,
            reason=kind_reason,
            compatibility=EventJournalReadinessCompatibility.KIND_UNSUPPORTED,
            details=common,
        )

    if requested_stream_id is not None and record.stream_id != requested_stream_id:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            record=record,
            reason=EventJournalReadinessReason.STREAM_ID_MISMATCH,
            compatibility=EventJournalReadinessCompatibility.STREAM_MISMATCH,
            details=common | {"required_stream_id": str(requested_stream_id)},
        )

    continuity_reason = _continuity_reason(policy, record)
    if continuity_reason is not None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            record=record,
            reason=continuity_reason,
            compatibility=EventJournalReadinessCompatibility.CONTINUITY_UNSUPPORTED,
            details=common,
        )

    checkpoint_reason = _checkpoint_reason(policy, record, checkpoint)
    if checkpoint_reason is not None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            record=record,
            checkpoint=checkpoint,
            reason=checkpoint_reason,
            compatibility=EventJournalReadinessCompatibility.STREAM_MISMATCH
            if checkpoint_reason is EventJournalReadinessReason.CHECKPOINT_STREAM_MISMATCH
            else EventJournalReadinessCompatibility.NOT_COMPATIBLE,
            details=common,
        )

    payload_reason = _payload_reason(policy, record, expected_payload_hash)
    if payload_reason is not None:
        return _not_ready(
            policy=policy,
            checked_at=checked_at,
            record=record,
            checkpoint=checkpoint,
            reason=payload_reason,
            details=common,
        )

    return _decision(
        policy=policy,
        checked_at=checked_at,
        record=record,
        checkpoint=checkpoint,
        ready=True,
        reason=EventJournalReadinessReason.READY,
        compatibility=EventJournalReadinessCompatibility.DIRECT_STREAM_MATCH,
        details=common,
    )


def _source_reason(
    policy: EventJournalReadinessPolicy,
    record: EventJournalRecord,
) -> EventJournalReadinessReason | None:
    if policy.require_source_record and record.source_record_id is None:
        return EventJournalReadinessReason.SOURCE_RECORD_REQUIRED
    if record.source_kind is EventJournalSourceKind.UNKNOWN:
        return EventJournalReadinessReason.SOURCE_KIND_UNKNOWN
    if record.source_kind not in policy.allowed_source_kinds:
        return EventJournalReadinessReason.SOURCE_KIND_UNSUPPORTED
    if record.source_trust not in policy.allowed_source_trust:
        return EventJournalReadinessReason.SOURCE_UNTRUSTED
    if record.source_health not in policy.allowed_source_health:
        return EventJournalReadinessReason.SOURCE_UNHEALTHY
    return None


def _kind_reason(
    policy: EventJournalReadinessPolicy,
    record: EventJournalRecord,
    requested_record_kind: EventJournalRecordKind | None,
) -> EventJournalReadinessReason | None:
    if record.record_kind is EventJournalRecordKind.UNKNOWN:
        return EventJournalReadinessReason.RECORD_KIND_UNKNOWN
    if record.record_kind not in policy.allowed_record_kinds:
        return EventJournalReadinessReason.RECORD_KIND_UNSUPPORTED
    if requested_record_kind is not None and record.record_kind is not requested_record_kind:
        return EventJournalReadinessReason.RECORD_KIND_UNSUPPORTED
    return None


def _continuity_reason(  # noqa: PLR0911
    policy: EventJournalReadinessPolicy,
    record: EventJournalRecord,
) -> EventJournalReadinessReason | None:
    if record.continuity_status is EventJournalContinuityStatus.UNKNOWN:
        return EventJournalReadinessReason.CONTINUITY_UNKNOWN
    if record.continuity_status not in policy.allowed_continuity_statuses:
        return EventJournalReadinessReason.CONTINUITY_GAPPED
    if policy.require_sequence and record.sequence_number is None:
        return EventJournalReadinessReason.SEQUENCE_MISSING
    if policy.require_previous_sequence and record.previous_sequence_number is None:
        return EventJournalReadinessReason.PREVIOUS_SEQUENCE_MISSING
    if (
        record.previous_sequence_number is not None
        and record.sequence_number < record.previous_sequence_number
    ):
        return EventJournalReadinessReason.SEQUENCE_REGRESSION
    if policy.require_contiguous_sequence:
        if record.previous_sequence_number is None:
            return EventJournalReadinessReason.PREVIOUS_SEQUENCE_MISSING
        if record.sequence_number != record.previous_sequence_number + 1:
            return EventJournalReadinessReason.SEQUENCE_GAP_DECLARED
    return None


def _checkpoint_reason(  # noqa: PLR0911
    policy: EventJournalReadinessPolicy,
    record: EventJournalRecord,
    checkpoint: EventJournalCheckpoint | None,
) -> EventJournalReadinessReason | None:
    if not policy.require_checkpoint and checkpoint is None:
        return None
    if checkpoint is None:
        return EventJournalReadinessReason.CHECKPOINT_MISSING
    if checkpoint.stream_id != record.stream_id:
        return EventJournalReadinessReason.CHECKPOINT_STREAM_MISMATCH
    if checkpoint.last_sequence_number > record.sequence_number:
        return EventJournalReadinessReason.CHECKPOINT_AHEAD_OF_RECORD
    if checkpoint.source_kind is EventJournalSourceKind.UNKNOWN:
        return EventJournalReadinessReason.SOURCE_KIND_UNKNOWN
    if checkpoint.source_kind not in policy.allowed_source_kinds:
        return EventJournalReadinessReason.SOURCE_KIND_UNSUPPORTED
    if checkpoint.source_trust not in policy.allowed_source_trust:
        return EventJournalReadinessReason.SOURCE_UNTRUSTED
    if checkpoint.source_health is not EventJournalSourceHealth.HEALTHY:
        return EventJournalReadinessReason.SOURCE_UNHEALTHY
    if checkpoint.source_health not in policy.allowed_source_health:
        return EventJournalReadinessReason.SOURCE_UNHEALTHY
    if policy.require_source_record and checkpoint.source_record_id is None:
        return EventJournalReadinessReason.SOURCE_RECORD_REQUIRED
    return None


def _payload_reason(
    policy: EventJournalReadinessPolicy,
    record: EventJournalRecord,
    expected_payload_hash: str | None,
) -> EventJournalReadinessReason | None:
    if not record.payload_type:
        return EventJournalReadinessReason.PAYLOAD_TYPE_MISSING
    if policy.require_payload_hash and not record.payload_hash:
        return EventJournalReadinessReason.PAYLOAD_HASH_MISSING
    if expected_payload_hash is not None and record.payload_hash != expected_payload_hash:
        return EventJournalReadinessReason.PAYLOAD_HASH_MISMATCH
    if policy.require_idempotency_key and record.idempotency_key is None:
        return EventJournalReadinessReason.IDEMPOTENCY_KEY_MISSING
    return None


def _not_ready(  # noqa: PLR0913
    *,
    policy: EventJournalReadinessPolicy,
    checked_at: datetime,
    record: EventJournalRecord,
    reason: EventJournalReadinessReason,
    details: object,
    checkpoint: EventJournalCheckpoint | None = None,
    compatibility: EventJournalReadinessCompatibility = (
        EventJournalReadinessCompatibility.NOT_COMPATIBLE
    ),
) -> EventJournalReadinessDecision:
    return _decision(
        policy=policy,
        checked_at=checked_at,
        record=record,
        checkpoint=checkpoint,
        reason=reason,
        compatibility=compatibility,
        details=details,
    )


def _decision(  # noqa: PLR0913
    *,
    policy: EventJournalReadinessPolicy,
    checked_at: datetime,
    reason: EventJournalReadinessReason,
    compatibility: EventJournalReadinessCompatibility,
    details: object,
    record: EventJournalRecord | None = None,
    checkpoint: EventJournalCheckpoint | None = None,
    ready: bool = False,
) -> EventJournalReadinessDecision:
    if policy.policy_id is None:
        raise ValueError("event journal policy must have policy_id")
    return EventJournalReadinessDecision(
        policy_id=policy.policy_id,
        stream_id=None if record is None else record.stream_id,
        record_kind=None if record is None else record.record_kind,
        sequence_number=None if record is None else record.sequence_number,
        checkpoint_id=None if checkpoint is None else checkpoint.checkpoint_id,
        ready=ready,
        reason=reason,
        compatibility=compatibility,
        record_id=None if record is None else record.record_id,
        checked_at=checked_at,
        details=details,
    )


def _common_decision_fields(record: EventJournalRecord) -> dict[str, object]:
    return {
        "stream_id": str(record.stream_id),
        "record_kind": record.record_kind.value,
        "sequence_number": record.sequence_number,
        "source_kind": record.source_kind.value,
        "continuity_status": record.continuity_status.value,
    }


def _policy_disabled(policy: EventJournalReadinessPolicy) -> bool:
    return policy.metadata.get("policy_disabled") is True


def _stream_id_or_none(
    value: EventJournalStreamId | str | None,
) -> EventJournalStreamId | None:
    if value is None:
        return None
    return (
        value
        if isinstance(value, EventJournalStreamId)
        else EventJournalStreamId(value=value)
    )


def _record_kind_or_none(
    value: EventJournalRecordKind | str | None,
) -> EventJournalRecordKind | None:
    if value is None:
        return None
    return value if isinstance(value, EventJournalRecordKind) else EventJournalRecordKind(value)
