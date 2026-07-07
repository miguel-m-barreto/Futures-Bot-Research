from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
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

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.ids import (
    AssetConversionPolicyId,
    AssetConversionRateSnapshotId,
    AssetConversionReadinessDecisionId,
)
from futures_bot.domain.time import ensure_aware_utc


class AssetConversionEvidenceKind(StrEnum):
    DIRECT_PAIR_RATE = "DIRECT_PAIR_RATE"
    INVERSE_PAIR_RATE = "INVERSE_PAIR_RATE"
    TRIANGULATED_RATE = "TRIANGULATED_RATE"
    REFERENCE_INDEX_VALUE = "REFERENCE_INDEX_VALUE"
    MANUAL_OFFICIAL_RATE = "MANUAL_OFFICIAL_RATE"
    UNKNOWN = "UNKNOWN"


class AssetConversionDirection(StrEnum):
    FROM_TO = "FROM_TO"
    TO_FROM_INVERTED = "TO_FROM_INVERTED"
    TRIANGULATED = "TRIANGULATED"
    UNKNOWN = "UNKNOWN"


class AssetConversionDecisionReason(StrEnum):
    READY = "READY"
    POLICY_DISABLED = "POLICY_DISABLED"
    FROM_ASSET_MISSING = "FROM_ASSET_MISSING"
    TO_ASSET_MISSING = "TO_ASSET_MISSING"
    SAME_ASSET_DIRECT_MATCH = "SAME_ASSET_DIRECT_MATCH"
    CONVERSION_RATE_MISSING = "CONVERSION_RATE_MISSING"
    CONVERSION_RATE_STALE = "CONVERSION_RATE_STALE"
    CONVERSION_RATE_FUTURE_DATED = "CONVERSION_RATE_FUTURE_DATED"
    CONVERSION_SOURCE_UNTRUSTED = "CONVERSION_SOURCE_UNTRUSTED"
    CONVERSION_SOURCE_UNHEALTHY = "CONVERSION_SOURCE_UNHEALTHY"
    CONVERSION_PAIR_MISMATCH = "CONVERSION_PAIR_MISMATCH"
    CONVERSION_DIRECTION_NOT_ALLOWED = "CONVERSION_DIRECTION_NOT_ALLOWED"
    CONVERSION_SPREAD_TOO_WIDE = "CONVERSION_SPREAD_TOO_WIDE"
    TRIANGULATION_NOT_ALLOWED = "TRIANGULATION_NOT_ALLOWED"
    TRIANGULATION_LEG_MISSING = "TRIANGULATION_LEG_MISSING"
    TRIANGULATION_LEG_NOT_READY = "TRIANGULATION_LEG_NOT_READY"
    NOT_READY = "NOT_READY"
    UNKNOWN = "UNKNOWN"


class AssetConversionCompatibility(StrEnum):
    DIRECT_SAME_ASSET = "DIRECT_SAME_ASSET"
    DIRECT_RATE = "DIRECT_RATE"
    INVERSE_RATE = "INVERSE_RATE"
    TRIANGULATED_RATE = "TRIANGULATED_RATE"
    NOT_COMPATIBLE = "NOT_COMPATIBLE"
    UNKNOWN = "UNKNOWN"


class AssetConversionSourceKind(StrEnum):
    MARK_PRICE = "MARK_PRICE"
    INDEX_PRICE = "INDEX_PRICE"
    ORACLE_PRICE = "ORACLE_PRICE"
    VENUE_ACCOUNT_PRICE = "VENUE_ACCOUNT_PRICE"
    MANUAL_REVIEWED_RATE = "MANUAL_REVIEWED_RATE"
    TEST_FIXTURE = "TEST_FIXTURE"
    UNKNOWN = "UNKNOWN"


class AssetConversionSourceTrust(StrEnum):
    OFFICIAL = "OFFICIAL"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    TEST_ONLY = "TEST_ONLY"
    UNTRUSTED = "UNTRUSTED"
    UNKNOWN = "UNKNOWN"


class AssetConversionSourceHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class AssetConversionRateSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: AssetConversionRateSnapshotId | None = None
    from_asset: AssetSymbol
    to_asset: AssetSymbol
    rate: Decimal
    observed_at: datetime
    captured_at: datetime
    source_kind: AssetConversionSourceKind
    source_trust: AssetConversionSourceTrust
    source_health: AssetConversionSourceHealth
    evidence_kind: AssetConversionEvidenceKind
    bid: Decimal | None = None
    ask: Decimal | None = None
    mid: Decimal | None = None
    spread_bps: Decimal | None = None
    source_record_id: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("from_asset", "to_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol:
        return _asset_symbol(value)

    @field_validator("rate", "bid", "ask", "mid", "spread_bps", mode="before")
    @classmethod
    def _coerce_decimal_field(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("rate", "bid", "ask", "mid")
    @classmethod
    def _validate_positive_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value <= 0):
            raise ValueError("conversion rate values must be positive")
        return value

    @field_validator("spread_bps")
    @classmethod
    def _validate_spread_bps(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("spread_bps must be finite and >= 0")
        return value

    @field_validator("observed_at", "captured_at")
    @classmethod
    def _validate_timestamp(cls, value: datetime) -> datetime:
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
        if self.from_asset == self.to_asset:
            raise ValueError("conversion rate snapshots require different assets")
        if self.captured_at < self.observed_at:
            raise ValueError("captured_at must be >= observed_at")
        expected = deterministic_asset_conversion_rate_snapshot_id(self)
        if self.snapshot_id is not None and self.snapshot_id != expected:
            raise ValueError("snapshot_id is not deterministic")
        object.__setattr__(self, "snapshot_id", expected)
        return self


class AssetConversionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: AssetConversionPolicyId | None = None
    from_asset: AssetSymbol | None = None
    to_asset: AssetSymbol | None = None
    max_rate_age: int
    require_source_record: bool
    allowed_source_trust: tuple[AssetConversionSourceTrust, ...]
    allowed_source_health: tuple[AssetConversionSourceHealth, ...]
    allow_same_asset_direct_match: bool
    allow_inverse_rate: bool
    allow_triangulation: bool
    require_bid_ask: bool
    max_spread_bps: Decimal | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @classmethod
    def strict(
        cls,
        *,
        from_asset: AssetSymbol | str | None = None,
        to_asset: AssetSymbol | str | None = None,
        max_rate_age: int = 60_000,
        metadata: Mapping[str, Any] | None = None,
    ) -> Self:
        return cls(
            from_asset=None if from_asset is None else _asset_symbol(from_asset),
            to_asset=None if to_asset is None else _asset_symbol(to_asset),
            max_rate_age=max_rate_age,
            require_source_record=True,
            allowed_source_trust=(AssetConversionSourceTrust.OFFICIAL,),
            allowed_source_health=(AssetConversionSourceHealth.HEALTHY,),
            allow_same_asset_direct_match=False,
            allow_inverse_rate=False,
            allow_triangulation=False,
            require_bid_ask=False,
            max_spread_bps=None,
            metadata={"factory": "strict"} if metadata is None else metadata,
        )

    @field_validator("from_asset", "to_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol | None:
        return None if value is None else _asset_symbol(value)

    @field_validator("max_rate_age")
    @classmethod
    def _validate_max_rate_age(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_rate_age must be positive")
        return value

    @field_validator("max_spread_bps", mode="before")
    @classmethod
    def _coerce_spread(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("max_spread_bps")
    @classmethod
    def _validate_max_spread(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("max_spread_bps must be finite and >= 0")
        return value

    @field_validator("allowed_source_trust")
    @classmethod
    def _validate_allowed_trust(
        cls,
        value: tuple[AssetConversionSourceTrust, ...],
    ) -> tuple[AssetConversionSourceTrust, ...]:
        if not value:
            raise ValueError("allowed_source_trust must be non-empty")
        return tuple(sorted(set(value), key=lambda item: item.value))

    @field_validator("allowed_source_health")
    @classmethod
    def _validate_allowed_health(
        cls,
        value: tuple[AssetConversionSourceHealth, ...],
    ) -> tuple[AssetConversionSourceHealth, ...]:
        if not value:
            raise ValueError("allowed_source_health must be non-empty")
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
        expected = deterministic_asset_conversion_policy_id(self)
        if self.policy_id is not None and self.policy_id != expected:
            raise ValueError("policy_id is not deterministic")
        object.__setattr__(self, "policy_id", expected)
        return self


class AssetConversionReadinessDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: AssetConversionReadinessDecisionId | None = None
    policy_id: AssetConversionPolicyId
    from_asset: AssetSymbol | None = None
    to_asset: AssetSymbol | None = None
    ready: bool
    reason: AssetConversionDecisionReason
    compatibility: AssetConversionCompatibility
    snapshot_id: AssetConversionRateSnapshotId | None = None
    inverse_snapshot_id: AssetConversionRateSnapshotId | None = None
    leg_decision_ids: tuple[AssetConversionReadinessDecisionId, ...] = ()
    checked_at: datetime
    effective_rate: Decimal | None = None
    details: Any = Field(default_factory=dict)

    @field_validator("from_asset", "to_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol | None:
        return None if value is None else _asset_symbol(value)

    @field_validator("checked_at")
    @classmethod
    def _validate_checked_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("effective_rate", mode="before")
    @classmethod
    def _coerce_effective_rate(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("effective_rate")
    @classmethod
    def _validate_effective_rate(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value <= 0):
            raise ValueError("effective_rate must be positive")
        return value

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        return _freeze_json_value(value, path="details")

    @field_serializer("details")
    def _serialize_details(self, value: Any) -> Any:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.ready and self.reason is not AssetConversionDecisionReason.READY:
            raise ValueError("ready conversion decision requires READY reason")
        if not self.ready and self.reason is AssetConversionDecisionReason.READY:
            raise ValueError("not-ready conversion decision requires non-READY reason")
        if self.ready and self.compatibility in {
            AssetConversionCompatibility.UNKNOWN,
            AssetConversionCompatibility.NOT_COMPATIBLE,
        }:
            raise ValueError("ready conversion decision requires compatible assets")
        expected = deterministic_asset_conversion_readiness_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


def deterministic_asset_conversion_rate_snapshot_id(
    snapshot: AssetConversionRateSnapshot,
) -> AssetConversionRateSnapshotId:
    digest = _digest(_model_identity(snapshot, exclude={"snapshot_id"}))
    return AssetConversionRateSnapshotId(value=f"asset-conversion-rate:{digest}")


def deterministic_asset_conversion_policy_id(
    policy: AssetConversionPolicy,
) -> AssetConversionPolicyId:
    digest = _digest(_model_identity(policy, exclude={"policy_id"}))
    return AssetConversionPolicyId(value=f"asset-conversion-policy:{digest}")


def deterministic_asset_conversion_readiness_decision_id(
    decision: AssetConversionReadinessDecision,
) -> AssetConversionReadinessDecisionId:
    digest = _digest(_model_identity(decision, exclude={"decision_id"}))
    return AssetConversionReadinessDecisionId(value=f"asset-conversion-readiness:{digest}")


def _asset_symbol(value: object) -> AssetSymbol:
    if isinstance(value, AssetSymbol):
        return AssetSymbol.model_validate(value.model_dump())
    if isinstance(value, str):
        return AssetSymbol(value)
    if isinstance(value, Mapping):
        if set(value) != {"value"}:
            raise ValueError("serialized asset symbol must contain only value")
        return AssetSymbol.model_validate(dict(value))
    raise ValueError("asset symbol input must be an AssetSymbol, string, or mapping")


def _coerce_decimal(value: object) -> Decimal:
    if isinstance(value, bool | float):
        raise ValueError("decimal value must be Decimal, int, or string")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int | str):
        try:
            result = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("decimal value is invalid") from exc
    else:
        raise ValueError("decimal value must be Decimal, int, or string")
    if not result.is_finite():
        raise ValueError("decimal value must be finite")
    return result


def _trimmed(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must be non-empty")
    return stripped


def _model_identity(model: BaseModel, *, exclude: set[str]) -> dict[str, Any]:
    dumped = model.model_dump()
    for key in exclude:
        dumped.pop(key, None)
    return _canonical_value(dumped)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_value(value: Any) -> Any:
    result: Any
    if isinstance(value, Decimal):
        result = format(value, "f")
    elif isinstance(value, datetime):
        result = ensure_aware_utc(value).isoformat()
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


def _freeze_json_mapping(value: Mapping[str, Any], *, path: str) -> Mapping[str, Any]:
    frozen = _freeze_json_value(value, path=path)
    if not isinstance(frozen, Mapping):
        raise ValueError(f"{path} must be a JSON-compatible object")
    return frozen


def _freeze_json_value(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} float must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            frozen[key] = _freeze_json_value(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return tuple(
            _freeze_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    raise ValueError(f"{path} must be JSON-compatible")


def _thaw_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_thaw_json_value(item) for item in value]
    return value
