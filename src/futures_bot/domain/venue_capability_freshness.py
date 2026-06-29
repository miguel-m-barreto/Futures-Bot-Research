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
    VenueCapabilityFreshnessCheckId,
    VenueCapabilityFreshnessDecisionId,
    VenueCapabilityFreshnessPolicyId,
)
from futures_bot.domain.time import ensure_aware_utc
from futures_bot.domain.venue_capabilities import (
    VenueCapabilitySnapshot,
    VenueInstrumentRuleSnapshot,
)


class CapabilitySourceHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class CapabilityFreshnessDecisionReason(StrEnum):
    FRESH = "FRESH"
    VENUE_SNAPSHOT_MISSING = "VENUE_SNAPSHOT_MISSING"
    INSTRUMENT_RULES_MISSING = "INSTRUMENT_RULES_MISSING"
    VENUE_SNAPSHOT_STALE = "VENUE_SNAPSHOT_STALE"
    INSTRUMENT_RULES_STALE = "INSTRUMENT_RULES_STALE"
    VENUE_SNAPSHOT_FROM_FUTURE = "VENUE_SNAPSHOT_FROM_FUTURE"
    INSTRUMENT_RULES_FROM_FUTURE = "INSTRUMENT_RULES_FROM_FUTURE"
    SOURCE_HEALTH_DEGRADED = "SOURCE_HEALTH_DEGRADED"
    SOURCE_HEALTH_UNAVAILABLE = "SOURCE_HEALTH_UNAVAILABLE"
    SOURCE_HEALTH_UNKNOWN = "SOURCE_HEALTH_UNKNOWN"
    VENUE_ID_MISMATCH = "VENUE_ID_MISMATCH"
    INSTRUMENT_ID_MISMATCH = "INSTRUMENT_ID_MISMATCH"
    SNAPSHOT_CAPTURE_ORDER_INVALID = "SNAPSHOT_CAPTURE_ORDER_INVALID"
    POLICY_DISABLED = "POLICY_DISABLED"


class CapabilityFreshnessMode(StrEnum):
    STRICT = "STRICT"
    ALLOW_DEGRADED_READ_ONLY = "ALLOW_DEGRADED_READ_ONLY"
    DISABLED = "DISABLED"


class VenueCapabilityFreshnessPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: VenueCapabilityFreshnessPolicyId
    mode: CapabilityFreshnessMode = CapabilityFreshnessMode.STRICT
    max_venue_snapshot_age_ms: int
    max_instrument_rules_age_ms: int
    max_clock_skew_ms: int = 0
    reject_future_snapshots: bool = True
    reject_degraded_source: bool = True
    reject_unknown_source: bool = True
    require_venue_snapshot: bool = True
    require_instrument_rules: bool = True

    @classmethod
    def strict(
        cls,
        *,
        policy_id: VenueCapabilityFreshnessPolicyId | None = None,
        max_venue_snapshot_age_ms: int,
        max_instrument_rules_age_ms: int,
        max_clock_skew_ms: int = 0,
    ) -> Self:
        return cls(
            policy_id=policy_id
            or VenueCapabilityFreshnessPolicyId(value="venue-cap-freshness:strict"),
            mode=CapabilityFreshnessMode.STRICT,
            max_venue_snapshot_age_ms=max_venue_snapshot_age_ms,
            max_instrument_rules_age_ms=max_instrument_rules_age_ms,
            max_clock_skew_ms=max_clock_skew_ms,
            reject_future_snapshots=True,
            reject_degraded_source=True,
            reject_unknown_source=True,
            require_venue_snapshot=True,
            require_instrument_rules=True,
        )

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.max_venue_snapshot_age_ms <= 0:
            raise ValueError("max_venue_snapshot_age_ms must be > 0")
        if self.max_instrument_rules_age_ms <= 0:
            raise ValueError("max_instrument_rules_age_ms must be > 0")
        if self.max_clock_skew_ms < 0:
            raise ValueError("max_clock_skew_ms must be >= 0")
        if self.mode is CapabilityFreshnessMode.STRICT:
            if not self.reject_future_snapshots:
                raise ValueError("STRICT requires reject_future_snapshots=True")
            if not self.reject_degraded_source:
                raise ValueError("STRICT requires reject_degraded_source=True")
            if not self.reject_unknown_source:
                raise ValueError("STRICT requires reject_unknown_source=True")
            if not self.require_venue_snapshot:
                raise ValueError("STRICT requires require_venue_snapshot=True")
            if not self.require_instrument_rules:
                raise ValueError("STRICT requires require_instrument_rules=True")
        return self


class VenueCapabilityFreshnessCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: VenueCapabilityFreshnessCheckId | None = None
    venue_id: str
    instrument_id: str
    venue_snapshot: VenueCapabilitySnapshot | None = None
    instrument_rules: VenueInstrumentRuleSnapshot | None = None
    policy: VenueCapabilityFreshnessPolicy
    source_health: CapabilitySourceHealth
    checked_at: datetime
    correlation_id: str | None = None

    @field_validator("venue_id", "instrument_id", "correlation_id")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "freshness check text")

    @field_validator("checked_at")
    @classmethod
    def _validate_checked_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.venue_snapshot is not None and self.venue_snapshot.venue_id != self.venue_id:
            raise ValueError("venue_snapshot.venue_id must match venue_id")
        if self.instrument_rules is not None:
            if self.instrument_rules.venue_id != self.venue_id:
                raise ValueError("instrument_rules.venue_id must match venue_id")
            if self.instrument_rules.instrument_id != self.instrument_id:
                raise ValueError("instrument_rules.instrument_id must match instrument_id")
        expected = deterministic_venue_capability_freshness_check_id(self)
        if self.check_id is not None and self.check_id != expected:
            raise ValueError("check_id is not deterministic")
        object.__setattr__(self, "check_id", expected)
        return self


class VenueCapabilityFreshnessDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: VenueCapabilityFreshnessDecisionId | None = None
    check_id: VenueCapabilityFreshnessCheckId
    fresh: bool
    reason: CapabilityFreshnessDecisionReason
    venue_snapshot_age_ms: int | None = None
    instrument_rules_age_ms: int | None = None
    source_health: CapabilitySourceHealth
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
        success_reasons = {
            CapabilityFreshnessDecisionReason.FRESH,
            CapabilityFreshnessDecisionReason.POLICY_DISABLED,
        }
        if self.fresh and self.reason not in success_reasons:
            raise ValueError("fresh=True requires reason FRESH or POLICY_DISABLED")
        if not self.fresh and self.reason in success_reasons:
            raise ValueError("fresh=False requires a rejection reason")
        if self.venue_snapshot_age_ms is not None and self.venue_snapshot_age_ms < 0:
            raise ValueError("venue_snapshot_age_ms must be >= 0")
        if self.instrument_rules_age_ms is not None and self.instrument_rules_age_ms < 0:
            raise ValueError("instrument_rules_age_ms must be >= 0")
        expected = deterministic_venue_capability_freshness_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


def deterministic_venue_capability_freshness_check_id(
    check: VenueCapabilityFreshnessCheck,
) -> VenueCapabilityFreshnessCheckId:
    digest = _digest(_model_identity(check, exclude={"check_id"}))
    return VenueCapabilityFreshnessCheckId(value=f"venue-cap-freshness-check:{digest}")


def deterministic_venue_capability_freshness_decision_id(
    decision: VenueCapabilityFreshnessDecision,
) -> VenueCapabilityFreshnessDecisionId:
    digest = _digest(_model_identity(decision, exclude={"decision_id"}))
    return VenueCapabilityFreshnessDecisionId(value=f"venue-cap-freshness-decision:{digest}")


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
