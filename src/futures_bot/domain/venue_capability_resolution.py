from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from math import isfinite
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.ids import (
    VenueCapabilityResolutionDecisionId,
    VenueCapabilityResolutionRequestId,
    VenueCapabilitySourceRecordId,
)
from futures_bot.domain.order_lifecycle import OrderIntent
from futures_bot.domain.time import ensure_aware_utc
from futures_bot.domain.venue_capabilities import (
    VenueCapabilitySnapshot,
    VenueInstrumentRuleSnapshot,
    VenueOrderValidationContext,
)
from futures_bot.domain.venue_capability_freshness import (
    CapabilitySourceHealth,
    VenueCapabilityFreshnessCheck,
    VenueCapabilityFreshnessDecision,
    VenueCapabilityFreshnessPolicy,
)


class VenueCapabilityResolutionReason(StrEnum):
    READY = "READY"
    VENUE_SNAPSHOT_MISSING = "VENUE_SNAPSHOT_MISSING"
    INSTRUMENT_RULES_MISSING = "INSTRUMENT_RULES_MISSING"
    FRESHNESS_REJECTED = "FRESHNESS_REJECTED"
    VENUE_VALIDATION_CONTEXT_INVALID = "VENUE_VALIDATION_CONTEXT_INVALID"
    STORE_CONFLICT = "STORE_CONFLICT"
    REQUEST_VENUE_INSTRUMENT_MISMATCH = "REQUEST_VENUE_INSTRUMENT_MISMATCH"


class VenueCapabilityResolutionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: VenueCapabilityResolutionRequestId | None = None
    order_intent: OrderIntent
    checked_at: datetime
    freshness_policy: VenueCapabilityFreshnessPolicy
    source_health: CapabilitySourceHealth
    correlation_id: str | None = None

    @field_validator("checked_at")
    @classmethod
    def _validate_checked_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("correlation_id")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "resolution request text")

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        expected = deterministic_venue_capability_resolution_request_id(self)
        if self.request_id is not None and self.request_id != expected:
            raise ValueError("request_id is not deterministic")
        object.__setattr__(self, "request_id", expected)
        return self


class VenueCapabilityResolutionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: VenueCapabilityResolutionDecisionId | None = None
    request_id: VenueCapabilityResolutionRequestId
    ready: bool
    reason: VenueCapabilityResolutionReason
    venue_snapshot: VenueCapabilitySnapshot | None = None
    instrument_rules: VenueInstrumentRuleSnapshot | None = None
    freshness_check: VenueCapabilityFreshnessCheck | None = None
    freshness_decision: VenueCapabilityFreshnessDecision | None = None
    venue_validation_context: VenueOrderValidationContext | None = None
    venue_source_record_id: VenueCapabilitySourceRecordId | None = None
    instrument_source_record_ids: tuple[VenueCapabilitySourceRecordId, ...] = ()
    checked_at: datetime
    details: Any

    @field_validator("checked_at")
    @classmethod
    def _validate_checked_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.ready:
            if self.reason is not VenueCapabilityResolutionReason.READY:
                raise ValueError("ready=True requires reason READY")
            if self.venue_snapshot is None:
                raise ValueError("ready=True requires venue_snapshot")
            if self.instrument_rules is None:
                raise ValueError("ready=True requires instrument_rules")
            if self.freshness_check is None:
                raise ValueError("ready=True requires freshness_check")
            if self.freshness_decision is None:
                raise ValueError("ready=True requires freshness_decision")
            if self.venue_validation_context is None:
                raise ValueError("ready=True requires venue_validation_context")
        elif self.reason is VenueCapabilityResolutionReason.READY:
            raise ValueError("ready=False requires reason != READY")
        expected = deterministic_venue_capability_resolution_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


def deterministic_venue_capability_resolution_request_id(
    request: VenueCapabilityResolutionRequest,
) -> VenueCapabilityResolutionRequestId:
    digest = _digest(_model_identity(request, exclude={"request_id"}))
    return VenueCapabilityResolutionRequestId(value=f"venue-cap-resolution-request:{digest}")


def deterministic_venue_capability_resolution_decision_id(
    decision: VenueCapabilityResolutionDecision,
) -> VenueCapabilityResolutionDecisionId:
    digest = _digest(_model_identity(decision, exclude={"decision_id"}))
    return VenueCapabilityResolutionDecisionId(value=f"venue-cap-resolution-decision:{digest}")


def _model_identity(model: BaseModel, *, exclude: set[str]) -> dict[str, Any]:
    dumped = model.model_dump()
    for key in exclude:
        dumped.pop(key, None)
    return _canonical_value(dumped)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_value(value: Any) -> Any:
    result: Any
    if isinstance(value, datetime):
        result = ensure_aware_utc(value).isoformat()
    elif isinstance(value, Decimal):
        result = format(value, "f")
    elif isinstance(value, StrEnum):
        result = value.value
    elif isinstance(value, BaseModel):
        result = _canonical_value(value.model_dump())
    elif isinstance(value, Mapping):
        result = {str(key): _canonical_value(item) for key, item in value.items()}
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
