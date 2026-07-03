from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Any, NamedTuple, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.ids import (
    VenueCapabilityManualImportDecisionId,
    VenueCapabilityManualImportRequestId,
    VenueCapabilitySnapshotId,
    VenueCapabilitySourceHealthRecordId,
    VenueCapabilitySourceId,
    VenueCapabilitySourceImportId,
    VenueCapabilitySourcePayloadHashId,
    VenueCapabilitySourceRecordId,
    VenueInstrumentRuleSnapshotId,
)
from futures_bot.domain.time import ensure_aware_utc
from futures_bot.domain.venue_capabilities import (
    VenueCapabilitySnapshot,
    VenueInstrumentRuleSnapshot,
)


class VenueCapabilitySourceKind(StrEnum):
    OFFICIAL_EXCHANGE_API = "OFFICIAL_EXCHANGE_API"
    OFFICIAL_EXCHANGE_DOCS = "OFFICIAL_EXCHANGE_DOCS"
    OFFICIAL_EXCHANGE_EXPORT = "OFFICIAL_EXCHANGE_EXPORT"
    MANUAL_OFFICIAL_SNAPSHOT = "MANUAL_OFFICIAL_SNAPSHOT"
    INTERNAL_TEST_FIXTURE = "INTERNAL_TEST_FIXTURE"
    UNKNOWN = "UNKNOWN"


class VenueCapabilitySourceTrust(StrEnum):
    OFFICIAL = "OFFICIAL"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    TEST_ONLY = "TEST_ONLY"
    UNTRUSTED = "UNTRUSTED"
    UNKNOWN = "UNKNOWN"


class VenueCapabilitySourceFetchMode(StrEnum):
    MANUAL = "MANUAL"
    API_DEFERRED = "API_DEFERRED"
    STATIC_REFERENCE = "STATIC_REFERENCE"
    TEST_FIXTURE = "TEST_FIXTURE"


class VenueCapabilitySourceHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class VenueCapabilitySourceRecordReason(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED_UNTRUSTED = "REJECTED_UNTRUSTED"
    REJECTED_UNKNOWN_SOURCE = "REJECTED_UNKNOWN_SOURCE"
    REJECTED_PAYLOAD_HASH_MISMATCH = "REJECTED_PAYLOAD_HASH_MISMATCH"
    REJECTED_NON_CANONICAL_PAYLOAD = "REJECTED_NON_CANONICAL_PAYLOAD"
    REJECTED_SOURCE_TIME_INVALID = "REJECTED_SOURCE_TIME_INVALID"


class VenueCapabilityManualImportDecisionReason(StrEnum):
    ACCEPTED = "ACCEPTED"
    SOURCE_RECORD_NOT_ACCEPTED = "SOURCE_RECORD_NOT_ACCEPTED"
    SOURCE_RECORD_NOT_OFFICIAL = "SOURCE_RECORD_NOT_OFFICIAL"
    SOURCE_RECORD_NOT_HEALTHY = "SOURCE_RECORD_NOT_HEALTHY"
    VENUE_SNAPSHOT_PROVENANCE_MISMATCH = "VENUE_SNAPSHOT_PROVENANCE_MISMATCH"
    INSTRUMENT_RULE_PROVENANCE_MISMATCH = "INSTRUMENT_RULE_PROVENANCE_MISMATCH"
    VENUE_ID_MISMATCH = "VENUE_ID_MISMATCH"
    SOURCE_RECORD_STORE_CONFLICT = "SOURCE_RECORD_STORE_CONFLICT"
    VENUE_SNAPSHOT_STORE_CONFLICT = "VENUE_SNAPSHOT_STORE_CONFLICT"
    INSTRUMENT_RULE_STORE_CONFLICT = "INSTRUMENT_RULE_STORE_CONFLICT"
    MANUAL_IMPORT_STORE_CONFLICT = "MANUAL_IMPORT_STORE_CONFLICT"
    NO_SNAPSHOTS_PROVIDED = "NO_SNAPSHOTS_PROVIDED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class VenueCapabilitySourceDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: VenueCapabilitySourceId | None = None
    venue_id: str
    source_kind: VenueCapabilitySourceKind
    trust: VenueCapabilitySourceTrust
    fetch_mode: VenueCapabilitySourceFetchMode
    reference_uri: str | None = None
    reference_name: str
    official_owner: str | None = None
    version: str | None = None
    created_at: datetime
    metadata: Any

    @field_validator(
        "venue_id",
        "reference_uri",
        "reference_name",
        "official_owner",
        "version",
    )
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "source descriptor text")

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Any) -> Any:
        _validate_json_compatible(value, path="metadata")
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if (
            self.source_kind is VenueCapabilitySourceKind.UNKNOWN
            and self.trust is VenueCapabilitySourceTrust.OFFICIAL
        ):
            raise ValueError("UNKNOWN source_kind cannot have OFFICIAL trust")
        if (
            self.source_kind is VenueCapabilitySourceKind.INTERNAL_TEST_FIXTURE
            and self.trust is not VenueCapabilitySourceTrust.TEST_ONLY
        ):
            raise ValueError("INTERNAL_TEST_FIXTURE requires TEST_ONLY trust")
        expected = deterministic_venue_capability_source_id(self)
        if self.source_id is not None and self.source_id != expected:
            raise ValueError("source_id is not deterministic")
        object.__setattr__(self, "source_id", expected)
        return self


class VenueCapabilitySourcePayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    payload_hash_id: VenueCapabilitySourcePayloadHashId | None = None
    canonical_payload: Any
    payload_hash: str | None = None
    content_type: str
    captured_at: datetime
    observed_at: datetime
    allow_observed_before_captured: bool = False

    @field_validator("canonical_payload")
    @classmethod
    def _validate_payload(cls, value: Any) -> Any:
        _validate_json_compatible(value, path="canonical_payload")
        _canonical_json_bytes(value)
        return value

    @field_validator("payload_hash")
    @classmethod
    def _validate_hash(cls, value: str | None) -> str | None:
        return None if value is None else _sha256_hex(value, "payload_hash")

    @field_validator("content_type")
    @classmethod
    def _validate_content_type(cls, value: str) -> str:
        return _trimmed(value, "content_type")

    @field_validator("captured_at", "observed_at")
    @classmethod
    def _validate_timestamp(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        expected_hash = source_payload_hash(self.canonical_payload)
        if self.payload_hash is not None and self.payload_hash != expected_hash:
            raise ValueError("payload_hash does not match canonical_payload")
        object.__setattr__(self, "payload_hash", expected_hash)
        expected_id = deterministic_venue_capability_source_payload_hash_id(expected_hash)
        if self.payload_hash_id is not None and self.payload_hash_id != expected_id:
            raise ValueError("payload_hash_id is not deterministic")
        object.__setattr__(self, "payload_hash_id", expected_id)
        if (
            self.observed_at < self.captured_at
            and not self.allow_observed_before_captured
        ):
            raise ValueError("observed_at must be >= captured_at")
        return self


class VenueCapabilitySourceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: VenueCapabilitySourceRecordId | None = None
    descriptor: VenueCapabilitySourceDescriptor
    payload: VenueCapabilitySourcePayload
    health_status: VenueCapabilitySourceHealthStatus
    reason: VenueCapabilitySourceRecordReason
    accepted_for_execution: bool
    recorded_at: datetime
    details: Any

    @field_validator("recorded_at")
    @classmethod
    def _validate_recorded_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        _validate_json_compatible(value, path="details")
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.accepted_for_execution:
            if self.reason is not VenueCapabilitySourceRecordReason.ACCEPTED:
                raise ValueError("accepted source record requires ACCEPTED reason")
            if self.descriptor.trust is not VenueCapabilitySourceTrust.OFFICIAL:
                raise ValueError("accepted source record requires OFFICIAL trust")
            if self.descriptor.source_kind is VenueCapabilitySourceKind.UNKNOWN:
                raise ValueError("accepted source record cannot use UNKNOWN source_kind")
            if self.health_status is not VenueCapabilitySourceHealthStatus.HEALTHY:
                raise ValueError("accepted source record requires HEALTHY source status")
        elif self.reason is VenueCapabilitySourceRecordReason.ACCEPTED:
            raise ValueError("rejected source record requires reason != ACCEPTED")
        expected = deterministic_venue_capability_source_record_id(self)
        if self.record_id is not None and self.record_id != expected:
            raise ValueError("record_id is not deterministic")
        object.__setattr__(self, "record_id", expected)
        return self


class VenueCapabilitySourceHealthRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    health_record_id: VenueCapabilitySourceHealthRecordId | None = None
    source_id: VenueCapabilitySourceId
    venue_id: str
    health_status: VenueCapabilitySourceHealthStatus
    checked_at: datetime
    recorded_at: datetime
    details: Any

    @field_validator("venue_id")
    @classmethod
    def _validate_venue_id(cls, value: str) -> str:
        return _trimmed(value, "venue_id")

    @field_validator("checked_at", "recorded_at")
    @classmethod
    def _validate_timestamp(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        _validate_json_compatible(value, path="details")
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.recorded_at < self.checked_at:
            raise ValueError("recorded_at must be >= checked_at")
        expected = deterministic_venue_capability_source_health_record_id(self)
        if self.health_record_id is not None and self.health_record_id != expected:
            raise ValueError("health_record_id is not deterministic")
        object.__setattr__(self, "health_record_id", expected)
        return self


class VenueCapabilityManualImport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    import_id: VenueCapabilitySourceImportId | None = None
    source_record: VenueCapabilitySourceRecord
    venue_snapshot: VenueCapabilitySnapshot | None = None
    instrument_rules: tuple[VenueInstrumentRuleSnapshot, ...] = ()
    imported_at: datetime
    imported_by: str
    details: Any

    @field_validator("imported_at")
    @classmethod
    def _validate_imported_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("imported_by")
    @classmethod
    def _validate_imported_by(cls, value: str) -> str:
        return _trimmed(value, "imported_by")

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        _validate_json_compatible(value, path="details")
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if not self.source_record.accepted_for_execution:
            raise ValueError("manual import requires accepted source record")
        venue_id = self.source_record.descriptor.venue_id
        record_id = self.source_record.record_id
        payload_hash = self.source_record.payload.payload_hash
        if record_id is None or payload_hash is None:
            raise ValueError("manual import requires finalized source record")
        if self.venue_snapshot is not None:
            _validate_snapshot_provenance(
                actual=_SnapshotProvenanceRef.from_snapshot(self.venue_snapshot),
                expected=_SnapshotProvenanceRef(
                    venue_id=venue_id,
                    source_record_id=record_id,
                    source_payload_hash=payload_hash,
                ),
                label="venue_snapshot",
            )
        for rule in self.instrument_rules:
            _validate_snapshot_provenance(
                actual=_SnapshotProvenanceRef.from_snapshot(rule),
                expected=_SnapshotProvenanceRef(
                    venue_id=venue_id,
                    source_record_id=record_id,
                    source_payload_hash=payload_hash,
                ),
                label="instrument rule",
            )
        expected = deterministic_venue_capability_source_import_id(self)
        if self.import_id is not None and self.import_id != expected:
            raise ValueError("import_id is not deterministic")
        object.__setattr__(self, "import_id", expected)
        return self


class VenueCapabilityManualImportRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: VenueCapabilityManualImportRequestId | None = None
    source_record: VenueCapabilitySourceRecord
    venue_snapshot: VenueCapabilitySnapshot | None = None
    instrument_rules: tuple[VenueInstrumentRuleSnapshot, ...] = ()
    imported_at: datetime
    imported_by: str
    correlation_id: str | None = None
    details: Any

    @field_validator("imported_at")
    @classmethod
    def _validate_imported_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("imported_by", "correlation_id")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "manual import request text")

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        _validate_json_compatible(value, path="details")
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.venue_snapshot is None and not self.instrument_rules:
            raise ValueError("manual import request requires at least one snapshot")
        expected = deterministic_venue_capability_manual_import_request_id(self)
        if self.request_id is not None and self.request_id != expected:
            raise ValueError("request_id is not deterministic")
        object.__setattr__(self, "request_id", expected)
        return self


class VenueCapabilityManualImportDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: VenueCapabilityManualImportDecisionId | None = None
    request_id: VenueCapabilityManualImportRequestId
    accepted: bool
    reason: VenueCapabilityManualImportDecisionReason
    source_record_id: VenueCapabilitySourceRecordId | None = None
    venue_snapshot_id: VenueCapabilitySnapshotId | None = None
    instrument_rule_snapshot_ids: tuple[VenueInstrumentRuleSnapshotId, ...] = ()
    manual_import_id: VenueCapabilitySourceImportId | None = None
    imported_at: datetime
    details: Any

    @field_validator("imported_at")
    @classmethod
    def _validate_imported_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        _validate_json_compatible(value, path="details")
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.accepted:
            if self.reason is not VenueCapabilityManualImportDecisionReason.ACCEPTED:
                raise ValueError("accepted=True requires reason ACCEPTED")
            if self.manual_import_id is None:
                raise ValueError("accepted=True requires manual_import_id")
        elif self.reason is VenueCapabilityManualImportDecisionReason.ACCEPTED:
            raise ValueError("accepted=False requires reason != ACCEPTED")
        expected = deterministic_venue_capability_manual_import_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


def deterministic_venue_capability_source_id(
    descriptor: VenueCapabilitySourceDescriptor,
) -> VenueCapabilitySourceId:
    digest = _digest(_model_identity(descriptor, exclude={"source_id"}))
    return VenueCapabilitySourceId(value=f"venue-cap-source:{digest}")


def source_payload_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def deterministic_venue_capability_source_payload_hash_id(
    payload_hash: str,
) -> VenueCapabilitySourcePayloadHashId:
    _sha256_hex(payload_hash, "payload_hash")
    return VenueCapabilitySourcePayloadHashId(
        value=f"venue-cap-source-payload-hash:{payload_hash}"
    )


def deterministic_venue_capability_source_record_id(
    record: VenueCapabilitySourceRecord,
) -> VenueCapabilitySourceRecordId:
    digest = _digest(_model_identity(record, exclude={"record_id"}))
    return VenueCapabilitySourceRecordId(value=f"venue-cap-source-record:{digest}")


def deterministic_venue_capability_source_health_record_id(
    health_record: VenueCapabilitySourceHealthRecord,
) -> VenueCapabilitySourceHealthRecordId:
    digest = _digest(_model_identity(health_record, exclude={"health_record_id"}))
    return VenueCapabilitySourceHealthRecordId(
        value=f"venue-cap-source-health:{digest}"
    )


def deterministic_venue_capability_source_import_id(
    manual_import: VenueCapabilityManualImport,
) -> VenueCapabilitySourceImportId:
    digest = _digest(_model_identity(manual_import, exclude={"import_id"}))
    return VenueCapabilitySourceImportId(value=f"venue-cap-source-import:{digest}")


def deterministic_venue_capability_manual_import_request_id(
    request: VenueCapabilityManualImportRequest,
) -> VenueCapabilityManualImportRequestId:
    digest = _digest(_model_identity(request, exclude={"request_id"}))
    return VenueCapabilityManualImportRequestId(value=f"venue-cap-manual-import-req:{digest}")


def deterministic_venue_capability_manual_import_decision_id(
    decision: VenueCapabilityManualImportDecision,
) -> VenueCapabilityManualImportDecisionId:
    digest = _digest(_model_identity(decision, exclude={"decision_id"}))
    return VenueCapabilityManualImportDecisionId(
        value=f"venue-cap-manual-import-decision:{digest}"
    )


class _SnapshotProvenanceRef(NamedTuple):
    venue_id: str
    source_record_id: VenueCapabilitySourceRecordId | None
    source_payload_hash: str | None

    @classmethod
    def from_snapshot(
        cls,
        snapshot: VenueCapabilitySnapshot | VenueInstrumentRuleSnapshot,
    ) -> Self:
        return cls(
            venue_id=snapshot.venue_id,
            source_record_id=snapshot.source_record_id,
            source_payload_hash=snapshot.source_payload_hash,
        )


def _validate_snapshot_provenance(
    *,
    actual: _SnapshotProvenanceRef,
    expected: _SnapshotProvenanceRef,
    label: str,
) -> None:
    if actual.venue_id != expected.venue_id:
        raise ValueError(f"{label} venue_id must match source record venue_id")
    if actual.source_record_id != expected.source_record_id:
        raise ValueError(f"{label} source_record_id must match source record")
    if actual.source_payload_hash != expected.source_payload_hash:
        raise ValueError(f"{label} source_payload_hash must match source payload")


def _model_identity(model: BaseModel, *, exclude: set[str]) -> dict[str, Any]:
    dumped = model.model_dump(mode="json")
    for key in exclude:
        dumped.pop(key, None)
    return _canonical_value(dumped)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_value(value: Any) -> Any:
    result: Any
    if isinstance(value, datetime):
        result = ensure_aware_utc(value).isoformat()
    elif isinstance(value, StrEnum):
        result = value.value
    elif isinstance(value, BaseModel):
        result = _canonical_value(value.model_dump(mode="json"))
    elif isinstance(value, Mapping):
        result = {key: _canonical_value(item) for key, item in value.items()}
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        result = [_canonical_value(item) for item in value]
    else:
        result = value
    return result


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
            raise ValueError(f"{path} float must be finite")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            _validate_json_compatible(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _validate_json_compatible(item, path=f"{path}[{index}]")
        return
    raise ValueError(f"{path} must be JSON-compatible")


def _trimmed(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty and trimmed")
    return value


def _sha256_hex(value: str, name: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase sha256 hex")
    return value
