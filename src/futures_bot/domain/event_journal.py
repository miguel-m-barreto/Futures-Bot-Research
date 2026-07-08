from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from futures_bot.domain.ids import (
    DomainId,
    EventJournalCheckpointId,
    EventJournalReadinessDecisionId,
    EventJournalReadinessPolicyId,
    EventJournalRecordId,
    EventJournalStreamId,
)
from futures_bot.domain.time import ensure_aware_utc


class EventJournalRecordKind(StrEnum):
    MARKET_DATA_OBSERVATION = "MARKET_DATA_OBSERVATION"
    COLLATERAL_VALUATION_SNAPSHOT = "COLLATERAL_VALUATION_SNAPSHOT"
    ASSET_CONVERSION_RATE_SNAPSHOT = "ASSET_CONVERSION_RATE_SNAPSHOT"
    OBJECTIVE_ASSET_POLICY_SNAPSHOT = "OBJECTIVE_ASSET_POLICY_SNAPSHOT"
    MARGIN_LIQUIDATION_RULE_SNAPSHOT = "MARGIN_LIQUIDATION_RULE_SNAPSHOT"
    EXECUTION_COST_RULE_SNAPSHOT = "EXECUTION_COST_RULE_SNAPSHOT"
    VENUE_CAPABILITY_SNAPSHOT = "VENUE_CAPABILITY_SNAPSHOT"
    INSTRUMENT_RULE_SNAPSHOT = "INSTRUMENT_RULE_SNAPSHOT"
    RUNTIME_CONTROL_EVENT = "RUNTIME_CONTROL_EVENT"
    RECONCILIATION_EVENT = "RECONCILIATION_EVENT"
    TEST_FIXTURE = "TEST_FIXTURE"
    UNKNOWN = "UNKNOWN"


class EventJournalSourceKind(StrEnum):
    LOCAL_IN_MEMORY_JOURNAL = "LOCAL_IN_MEMORY_JOURNAL"
    LOCAL_WAL_CONTRACT = "LOCAL_WAL_CONTRACT"
    IMPORTED_REVIEW_BUNDLE = "IMPORTED_REVIEW_BUNDLE"
    MANUAL_REVIEWED_IMPORT = "MANUAL_REVIEWED_IMPORT"
    SYSTEM_GENERATED_RECORD = "SYSTEM_GENERATED_RECORD"
    TEST_FIXTURE = "TEST_FIXTURE"
    UNKNOWN = "UNKNOWN"


class EventJournalSourceTrust(StrEnum):
    OFFICIAL = "OFFICIAL"
    MANUAL_REVIEWED_OFFICIAL = "MANUAL_REVIEWED_OFFICIAL"
    SYSTEM_GENERATED = "SYSTEM_GENERATED"
    TEST_ONLY = "TEST_ONLY"
    UNTRUSTED = "UNTRUSTED"
    UNKNOWN = "UNKNOWN"


class EventJournalSourceHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    GAPPED = "GAPPED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class EventJournalContinuityStatus(StrEnum):
    CONTINUOUS = "CONTINUOUS"
    GAP_DECLARED = "GAP_DECLARED"
    GAP_SUSPECTED = "GAP_SUSPECTED"
    SNAPSHOT_ONLY = "SNAPSHOT_ONLY"
    UNKNOWN = "UNKNOWN"


class EventJournalReadinessCompatibility(StrEnum):
    DIRECT_STREAM_MATCH = "DIRECT_STREAM_MATCH"
    STREAM_MISMATCH = "STREAM_MISMATCH"
    KIND_UNSUPPORTED = "KIND_UNSUPPORTED"
    SOURCE_UNSUPPORTED = "SOURCE_UNSUPPORTED"
    CONTINUITY_UNSUPPORTED = "CONTINUITY_UNSUPPORTED"
    NOT_COMPATIBLE = "NOT_COMPATIBLE"
    UNKNOWN = "UNKNOWN"


class EventJournalReadinessReason(StrEnum):
    READY = "READY"
    POLICY_DISABLED = "POLICY_DISABLED"
    RECORD_MISSING = "RECORD_MISSING"
    RECORD_STALE = "RECORD_STALE"
    RECORD_FUTURE_DATED = "RECORD_FUTURE_DATED"
    SOURCE_RECORD_REQUIRED = "SOURCE_RECORD_REQUIRED"
    SOURCE_KIND_UNKNOWN = "SOURCE_KIND_UNKNOWN"
    SOURCE_KIND_UNSUPPORTED = "SOURCE_KIND_UNSUPPORTED"
    SOURCE_UNTRUSTED = "SOURCE_UNTRUSTED"
    SOURCE_UNHEALTHY = "SOURCE_UNHEALTHY"
    RECORD_KIND_UNKNOWN = "RECORD_KIND_UNKNOWN"
    RECORD_KIND_UNSUPPORTED = "RECORD_KIND_UNSUPPORTED"
    CONTINUITY_UNKNOWN = "CONTINUITY_UNKNOWN"
    CONTINUITY_GAPPED = "CONTINUITY_GAPPED"
    STREAM_ID_MISSING = "STREAM_ID_MISSING"
    STREAM_ID_MISMATCH = "STREAM_ID_MISMATCH"
    SEQUENCE_REQUIRED = "SEQUENCE_REQUIRED"
    SEQUENCE_MISSING = "SEQUENCE_MISSING"
    PREVIOUS_SEQUENCE_MISSING = "PREVIOUS_SEQUENCE_MISSING"
    SEQUENCE_REGRESSION = "SEQUENCE_REGRESSION"
    SEQUENCE_GAP_DECLARED = "SEQUENCE_GAP_DECLARED"
    CHECKPOINT_MISSING = "CHECKPOINT_MISSING"
    CHECKPOINT_STREAM_MISMATCH = "CHECKPOINT_STREAM_MISMATCH"
    CHECKPOINT_AHEAD_OF_RECORD = "CHECKPOINT_AHEAD_OF_RECORD"
    PAYLOAD_TYPE_MISSING = "PAYLOAD_TYPE_MISSING"
    PAYLOAD_HASH_MISSING = "PAYLOAD_HASH_MISSING"
    PAYLOAD_HASH_MISMATCH = "PAYLOAD_HASH_MISMATCH"
    IDEMPOTENCY_KEY_MISSING = "IDEMPOTENCY_KEY_MISSING"
    NOT_READY = "NOT_READY"
    UNKNOWN = "UNKNOWN"


class EventJournalRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: EventJournalRecordId | None = None
    stream_id: EventJournalStreamId
    record_kind: EventJournalRecordKind
    sequence_number: int
    previous_sequence_number: int | None = None
    payload_type: str
    payload_hash: str
    occurred_at: datetime
    recorded_at: datetime
    source_kind: EventJournalSourceKind
    source_trust: EventJournalSourceTrust
    source_health: EventJournalSourceHealth
    continuity_status: EventJournalContinuityStatus
    source_record_id: str | None = None
    idempotency_key: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("stream_id", mode="before")
    @classmethod
    def _coerce_stream_id(cls, value: object) -> EventJournalStreamId:
        return _revalidate_domain_id(EventJournalStreamId, value)

    @field_validator("sequence_number", "previous_sequence_number", mode="before")
    @classmethod
    def _validate_sequence(cls, value: object) -> int | None:
        if value is None:
            return None
        return _non_negative_int(value, "sequence")

    @field_validator("payload_type", "payload_hash")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _trimmed(value, "event journal payload text")

    @field_validator("source_record_id", "idempotency_key", "correlation_id", "causation_id")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "event journal text")

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def _validate_timestamp(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_json_mapping(value, path="metadata")

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> Any:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if (
            self.previous_sequence_number is not None
            and self.sequence_number < self.previous_sequence_number
        ):
            raise ValueError("sequence_number must be >= previous_sequence_number")
        expected = deterministic_event_journal_record_id(self)
        if self.record_id is not None and self.record_id != expected:
            raise ValueError("record_id is not deterministic")
        object.__setattr__(self, "record_id", expected)
        return self


class EventJournalCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint_id: EventJournalCheckpointId | None = None
    stream_id: EventJournalStreamId
    last_sequence_number: int
    checkpointed_at: datetime
    source_kind: EventJournalSourceKind
    source_trust: EventJournalSourceTrust
    source_health: EventJournalSourceHealth
    source_record_id: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("stream_id", mode="before")
    @classmethod
    def _coerce_stream_id(cls, value: object) -> EventJournalStreamId:
        return _revalidate_domain_id(EventJournalStreamId, value)

    @field_validator("last_sequence_number", mode="before")
    @classmethod
    def _validate_last_sequence(cls, value: object) -> int:
        return _non_negative_int(value, "last_sequence_number")

    @field_validator("checkpointed_at")
    @classmethod
    def _validate_checkpointed_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("source_record_id")
    @classmethod
    def _validate_source_record_id(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "source_record_id")

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_json_mapping(value, path="metadata")

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> Any:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        expected = deterministic_event_journal_checkpoint_id(self)
        if self.checkpoint_id is not None and self.checkpoint_id != expected:
            raise ValueError("checkpoint_id is not deterministic")
        object.__setattr__(self, "checkpoint_id", expected)
        return self


class EventJournalReadinessPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: EventJournalReadinessPolicyId | None = None
    max_record_age: int
    require_source_record: bool
    allowed_source_kinds: tuple[EventJournalSourceKind, ...]
    allowed_source_trust: tuple[EventJournalSourceTrust, ...]
    allowed_source_health: tuple[EventJournalSourceHealth, ...]
    allowed_record_kinds: tuple[EventJournalRecordKind, ...]
    allowed_continuity_statuses: tuple[EventJournalContinuityStatus, ...]
    require_sequence: bool
    require_previous_sequence: bool
    require_contiguous_sequence: bool
    require_checkpoint: bool
    require_payload_hash: bool
    require_idempotency_key: bool
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @classmethod
    def strict_contiguous(cls, *, metadata: Mapping[str, Any] | None = None) -> Self:
        return cls(
            max_record_age=5_000,
            require_source_record=True,
            allowed_source_kinds=(
                EventJournalSourceKind.LOCAL_IN_MEMORY_JOURNAL,
                EventJournalSourceKind.LOCAL_WAL_CONTRACT,
                EventJournalSourceKind.IMPORTED_REVIEW_BUNDLE,
                EventJournalSourceKind.MANUAL_REVIEWED_IMPORT,
                EventJournalSourceKind.SYSTEM_GENERATED_RECORD,
            ),
            allowed_source_trust=(
                EventJournalSourceTrust.OFFICIAL,
                EventJournalSourceTrust.MANUAL_REVIEWED_OFFICIAL,
                EventJournalSourceTrust.SYSTEM_GENERATED,
            ),
            allowed_source_health=(EventJournalSourceHealth.HEALTHY,),
            allowed_record_kinds=(EventJournalRecordKind.MARKET_DATA_OBSERVATION,),
            allowed_continuity_statuses=(EventJournalContinuityStatus.CONTINUOUS,),
            require_sequence=True,
            require_previous_sequence=True,
            require_contiguous_sequence=True,
            require_checkpoint=True,
            require_payload_hash=True,
            require_idempotency_key=True,
            metadata={"factory": "strict_contiguous"} if metadata is None else metadata,
        )

    @classmethod
    def research_fixture(cls, *, metadata: Mapping[str, Any] | None = None) -> Self:
        return cls(
            max_record_age=60_000,
            require_source_record=True,
            allowed_source_kinds=(EventJournalSourceKind.TEST_FIXTURE,),
            allowed_source_trust=(EventJournalSourceTrust.TEST_ONLY,),
            allowed_source_health=(EventJournalSourceHealth.HEALTHY,),
            allowed_record_kinds=(EventJournalRecordKind.TEST_FIXTURE,),
            allowed_continuity_statuses=(EventJournalContinuityStatus.SNAPSHOT_ONLY,),
            require_sequence=True,
            require_previous_sequence=False,
            require_contiguous_sequence=False,
            require_checkpoint=False,
            require_payload_hash=True,
            require_idempotency_key=False,
            metadata={"factory": "research_fixture"} if metadata is None else metadata,
        )

    @field_validator("max_record_age")
    @classmethod
    def _validate_max_record_age(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_record_age must be positive")
        return value

    @field_validator("allowed_source_kinds")
    @classmethod
    def _validate_allowed_source_kinds(
        cls,
        value: tuple[EventJournalSourceKind, ...],
    ) -> tuple[EventJournalSourceKind, ...]:
        if not value:
            raise ValueError("allowed_source_kinds must be non-empty")
        kinds = tuple(sorted(set(value), key=lambda item: item.value))
        if EventJournalSourceKind.UNKNOWN in kinds:
            raise ValueError("UNKNOWN source kind is not allowed")
        return kinds

    @field_validator("allowed_source_trust")
    @classmethod
    def _validate_allowed_source_trust(
        cls,
        value: tuple[EventJournalSourceTrust, ...],
    ) -> tuple[EventJournalSourceTrust, ...]:
        if not value:
            raise ValueError("allowed_source_trust must be non-empty")
        return tuple(sorted(set(value), key=lambda item: item.value))

    @field_validator("allowed_source_health")
    @classmethod
    def _validate_allowed_source_health(
        cls,
        value: tuple[EventJournalSourceHealth, ...],
    ) -> tuple[EventJournalSourceHealth, ...]:
        if not value:
            raise ValueError("allowed_source_health must be non-empty")
        return tuple(sorted(set(value), key=lambda item: item.value))

    @field_validator("allowed_record_kinds")
    @classmethod
    def _validate_allowed_record_kinds(
        cls,
        value: tuple[EventJournalRecordKind, ...],
    ) -> tuple[EventJournalRecordKind, ...]:
        if not value:
            raise ValueError("allowed_record_kinds must be non-empty")
        kinds = tuple(sorted(set(value), key=lambda item: item.value))
        if EventJournalRecordKind.UNKNOWN in kinds:
            raise ValueError("UNKNOWN record kind is not allowed")
        return kinds

    @field_validator("allowed_continuity_statuses")
    @classmethod
    def _validate_allowed_continuity_statuses(
        cls,
        value: tuple[EventJournalContinuityStatus, ...],
    ) -> tuple[EventJournalContinuityStatus, ...]:
        if not value:
            raise ValueError("allowed_continuity_statuses must be non-empty")
        return tuple(sorted(set(value), key=lambda item: item.value))

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_json_mapping(value, path="metadata")

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> Any:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        expected = deterministic_event_journal_readiness_policy_id(self)
        if self.policy_id is not None and self.policy_id != expected:
            raise ValueError("policy_id is not deterministic")
        object.__setattr__(self, "policy_id", expected)
        return self


class EventJournalReadinessDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: EventJournalReadinessDecisionId | None = None
    policy_id: EventJournalReadinessPolicyId
    stream_id: EventJournalStreamId | None = None
    record_kind: EventJournalRecordKind | None = None
    sequence_number: int | None = None
    checkpoint_id: EventJournalCheckpointId | None = None
    ready: bool
    reason: EventJournalReadinessReason
    compatibility: EventJournalReadinessCompatibility
    record_id: EventJournalRecordId | None = None
    checked_at: datetime
    details: Any = Field(default_factory=dict)

    @field_validator("stream_id", mode="before")
    @classmethod
    def _coerce_stream_id(cls, value: object) -> EventJournalStreamId | None:
        return None if value is None else _revalidate_domain_id(EventJournalStreamId, value)

    @field_validator("sequence_number", mode="before")
    @classmethod
    def _validate_sequence_number(cls, value: object) -> int | None:
        if value is None:
            return None
        return _non_negative_int(value, "sequence_number")

    @field_validator("checked_at")
    @classmethod
    def _validate_checked_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        return _freeze_json_value(value, path="details")

    @field_serializer("details")
    def _serialize_details(self, value: Any) -> Any:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.ready and self.reason is not EventJournalReadinessReason.READY:
            raise ValueError("ready event journal decision requires READY reason")
        if not self.ready and self.reason is EventJournalReadinessReason.READY:
            raise ValueError("not-ready event journal decision requires non-READY reason")
        if self.ready and self.compatibility in {
            EventJournalReadinessCompatibility.UNKNOWN,
            EventJournalReadinessCompatibility.NOT_COMPATIBLE,
        }:
            raise ValueError("ready event journal decision requires compatibility")
        expected = deterministic_event_journal_readiness_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


def deterministic_event_journal_record_id(record: EventJournalRecord) -> EventJournalRecordId:
    digest = _digest(_model_identity(record, exclude={"record_id"}))
    return EventJournalRecordId(value=f"event-journal-record:{digest}")


def deterministic_event_journal_checkpoint_id(
    checkpoint: EventJournalCheckpoint,
) -> EventJournalCheckpointId:
    digest = _digest(_model_identity(checkpoint, exclude={"checkpoint_id"}))
    return EventJournalCheckpointId(value=f"event-journal-checkpoint:{digest}")


def deterministic_event_journal_readiness_policy_id(
    policy: EventJournalReadinessPolicy,
) -> EventJournalReadinessPolicyId:
    digest = _digest(_model_identity(policy, exclude={"policy_id"}))
    return EventJournalReadinessPolicyId(value=f"event-journal-policy:{digest}")


def deterministic_event_journal_readiness_decision_id(
    decision: EventJournalReadinessDecision,
) -> EventJournalReadinessDecisionId:
    digest = _digest(_model_identity(decision, exclude={"decision_id"}))
    return EventJournalReadinessDecisionId(value=f"event-journal-readiness:{digest}")


def deterministic_event_journal_stream_id(
    *,
    stream_scope: Mapping[str, Any],
) -> EventJournalStreamId:
    digest = _digest(_canonical_value(stream_scope))
    return EventJournalStreamId(value=f"event-journal-stream:{digest}")


def _revalidate_domain_id[T: DomainId](id_type: type[T], value: object) -> T:
    if isinstance(value, id_type):
        return id_type.model_validate(value.model_dump())
    if isinstance(value, str):
        return id_type(value)
    return id_type.model_validate(value)


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return value


def _trimmed(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value


def _model_identity(model: BaseModel, *, exclude: set[str]) -> dict[str, Any]:
    dumped = model.model_dump()
    for key in exclude:
        dumped.pop(key, None)
    return _canonical_value(dumped)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return ensure_aware_utc(value).isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump())
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_canonical_value(item) for item in value]
    return value


def _canonical_json_bytes(payload: Any) -> bytes:
    payload = _canonical_value(payload)
    _validate_json_compatible(payload, path="payload")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _validate_json_compatible(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} must be JSON-compatible")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _validate_json_compatible(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            _validate_json_compatible(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} must be JSON-compatible")


def _freeze_json_mapping(value: Mapping[str, Any], *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a mapping")
    frozen = {
        str(key): _freeze_json_value(item, path=f"{path}.{key}")
        for key, item in value.items()
    }
    _validate_json_compatible(frozen, path=path)
    return MappingProxyType(frozen)


def _freeze_json_value(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, str | bool | int | float):
        _validate_json_compatible(value, path=path)
        return value
    if isinstance(value, Mapping):
        return _freeze_json_mapping(value, path=path)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        frozen = tuple(_freeze_json_value(item, path=f"{path}[]") for item in value)
        _validate_json_compatible(frozen, path=path)
        return frozen
    raise ValueError(f"{path} must be JSON-compatible")


def _thaw_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    return value
