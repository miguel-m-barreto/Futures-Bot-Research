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
    MarginLiquidationPolicyId,
    MarginLiquidationReadinessDecisionId,
    MarginLiquidationRuleSnapshotId,
)
from futures_bot.domain.time import ensure_aware_utc


class MarginMode(StrEnum):
    ISOLATED = "ISOLATED"
    CROSS = "CROSS"
    PORTFOLIO = "PORTFOLIO"
    MULTI_ASSET = "MULTI_ASSET"
    UNKNOWN = "UNKNOWN"


class MarginLiquidationSourceKind(StrEnum):
    VENUE_RULES = "VENUE_RULES"
    VENUE_RISK_BRACKET = "VENUE_RISK_BRACKET"
    VENUE_ACCOUNT_CONFIG = "VENUE_ACCOUNT_CONFIG"
    MANUAL_REVIEWED_RULE = "MANUAL_REVIEWED_RULE"
    TEST_FIXTURE = "TEST_FIXTURE"
    UNKNOWN = "UNKNOWN"


class MarginLiquidationSourceTrust(StrEnum):
    OFFICIAL = "OFFICIAL"
    MANUAL_REVIEWED_OFFICIAL = "MANUAL_REVIEWED_OFFICIAL"
    TEST_ONLY = "TEST_ONLY"
    UNTRUSTED = "UNTRUSTED"
    UNKNOWN = "UNKNOWN"


class MarginLiquidationSourceHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class LiquidationModelKind(StrEnum):
    VENUE_FORMULA = "VENUE_FORMULA"
    MAINTENANCE_MARGIN_MODEL = "MAINTENANCE_MARGIN_MODEL"
    RISK_BRACKET_MODEL = "RISK_BRACKET_MODEL"
    ACCOUNT_MODE_MODEL = "ACCOUNT_MODE_MODEL"
    NOT_PROVIDED = "NOT_PROVIDED"
    UNKNOWN = "UNKNOWN"


class MarginLiquidationCompatibility(StrEnum):
    DIRECT_MATCH = "DIRECT_MATCH"
    ASSET_MISMATCH = "ASSET_MISMATCH"
    MODE_UNSUPPORTED = "MODE_UNSUPPORTED"
    NOT_COMPATIBLE = "NOT_COMPATIBLE"
    UNKNOWN = "UNKNOWN"


class MarginLiquidationDecisionReason(StrEnum):
    READY = "READY"
    POLICY_DISABLED = "POLICY_DISABLED"
    SNAPSHOT_MISSING = "SNAPSHOT_MISSING"
    SNAPSHOT_STALE = "SNAPSHOT_STALE"
    SNAPSHOT_FUTURE_DATED = "SNAPSHOT_FUTURE_DATED"
    SOURCE_RECORD_REQUIRED = "SOURCE_RECORD_REQUIRED"
    SOURCE_KIND_UNKNOWN = "SOURCE_KIND_UNKNOWN"
    SOURCE_KIND_UNSUPPORTED = "SOURCE_KIND_UNSUPPORTED"
    SOURCE_UNTRUSTED = "SOURCE_UNTRUSTED"
    SOURCE_UNHEALTHY = "SOURCE_UNHEALTHY"
    VENUE_MISMATCH = "VENUE_MISMATCH"
    INSTRUMENT_MISMATCH = "INSTRUMENT_MISMATCH"
    MARGIN_MODE_UNKNOWN = "MARGIN_MODE_UNKNOWN"
    MARGIN_MODE_UNSUPPORTED = "MARGIN_MODE_UNSUPPORTED"
    INITIAL_MARGIN_MISSING = "INITIAL_MARGIN_MISSING"
    MAINTENANCE_MARGIN_MISSING = "MAINTENANCE_MARGIN_MISSING"
    LIQUIDATION_FEE_MISSING = "LIQUIDATION_FEE_MISSING"
    MAX_LEVERAGE_MISSING = "MAX_LEVERAGE_MISSING"
    LIQUIDATION_MODEL_MISSING = "LIQUIDATION_MODEL_MISSING"
    RISK_TIER_MISSING = "RISK_TIER_MISSING"
    COLLATERAL_ASSET_MISSING = "COLLATERAL_ASSET_MISSING"
    MARGIN_ASSET_MISSING = "MARGIN_ASSET_MISSING"
    SETTLEMENT_ASSET_MISSING = "SETTLEMENT_ASSET_MISSING"
    COLLATERAL_ASSET_MISMATCH = "COLLATERAL_ASSET_MISMATCH"
    MARGIN_ASSET_MISMATCH = "MARGIN_ASSET_MISMATCH"
    SETTLEMENT_ASSET_MISMATCH = "SETTLEMENT_ASSET_MISMATCH"
    NOT_READY = "NOT_READY"
    UNKNOWN = "UNKNOWN"


class MarginLiquidationRuleSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: MarginLiquidationRuleSnapshotId | None = None
    venue_id: str
    instrument_id: str | None = None
    margin_mode: MarginMode
    collateral_asset: AssetSymbol | None = None
    margin_asset: AssetSymbol | None = None
    settlement_asset: AssetSymbol | None = None
    initial_margin_rate: Decimal | None = None
    maintenance_margin_rate: Decimal | None = None
    liquidation_fee_rate: Decimal | None = None
    max_leverage: Decimal | None = None
    liquidation_model_kind: LiquidationModelKind
    risk_tier_id: str | None = None
    notional_floor: Decimal | None = None
    notional_ceiling: Decimal | None = None
    observed_at: datetime
    captured_at: datetime
    source_kind: MarginLiquidationSourceKind
    source_trust: MarginLiquidationSourceTrust
    source_health: MarginLiquidationSourceHealth
    source_record_id: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("venue_id", "instrument_id", "risk_tier_id", "source_record_id")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "margin liquidation text")

    @field_validator("collateral_asset", "margin_asset", "settlement_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol | None:
        return None if value is None else _asset_symbol(value)

    @field_validator(
        "initial_margin_rate",
        "maintenance_margin_rate",
        "liquidation_fee_rate",
        "max_leverage",
        "notional_floor",
        "notional_ceiling",
        mode="before",
    )
    @classmethod
    def _coerce_decimal_field(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("initial_margin_rate", "maintenance_margin_rate", "max_leverage")
    @classmethod
    def _validate_positive_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value <= 0):
            raise ValueError("margin rates and max_leverage must be positive")
        return value

    @field_validator("liquidation_fee_rate", "notional_floor", "notional_ceiling")
    @classmethod
    def _validate_non_negative_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("margin/liquidation decimal values must be >= 0")
        return value

    @field_validator("observed_at", "captured_at")
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
        if self.captured_at < self.observed_at:
            raise ValueError("captured_at must be >= observed_at")
        if (
            self.notional_floor is not None
            and self.notional_ceiling is not None
            and self.notional_floor > self.notional_ceiling
        ):
            raise ValueError("notional_floor must be <= notional_ceiling")
        expected = deterministic_margin_liquidation_rule_snapshot_id(self)
        if self.snapshot_id is not None and self.snapshot_id != expected:
            raise ValueError("snapshot_id is not deterministic")
        object.__setattr__(self, "snapshot_id", expected)
        return self


class MarginLiquidationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: MarginLiquidationPolicyId | None = None
    max_snapshot_age: int
    require_source_record: bool
    allowed_source_kinds: tuple[MarginLiquidationSourceKind, ...]
    allowed_source_trust: tuple[MarginLiquidationSourceTrust, ...]
    allowed_source_health: tuple[MarginLiquidationSourceHealth, ...]
    allowed_margin_modes: tuple[MarginMode, ...]
    require_initial_margin: bool
    require_maintenance_margin: bool
    require_liquidation_fee: bool
    require_max_leverage: bool
    require_liquidation_model: bool
    require_risk_tier: bool
    require_collateral_asset_match: bool
    require_margin_asset_match: bool
    require_settlement_asset_match: bool
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @classmethod
    def strict_official(cls, *, metadata: Mapping[str, Any] | None = None) -> Self:
        return cls(
            max_snapshot_age=300_000,
            require_source_record=True,
            allowed_source_kinds=(
                MarginLiquidationSourceKind.VENUE_RULES,
                MarginLiquidationSourceKind.VENUE_RISK_BRACKET,
                MarginLiquidationSourceKind.VENUE_ACCOUNT_CONFIG,
                MarginLiquidationSourceKind.MANUAL_REVIEWED_RULE,
            ),
            allowed_source_trust=(MarginLiquidationSourceTrust.OFFICIAL,),
            allowed_source_health=(MarginLiquidationSourceHealth.HEALTHY,),
            allowed_margin_modes=(MarginMode.ISOLATED, MarginMode.CROSS),
            require_initial_margin=True,
            require_maintenance_margin=True,
            require_liquidation_fee=True,
            require_max_leverage=True,
            require_liquidation_model=True,
            require_risk_tier=True,
            require_collateral_asset_match=True,
            require_margin_asset_match=True,
            require_settlement_asset_match=True,
            metadata={"factory": "strict_official"} if metadata is None else metadata,
        )

    @field_validator("max_snapshot_age")
    @classmethod
    def _validate_max_snapshot_age(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_snapshot_age must be positive")
        return value

    @field_validator("allowed_source_kinds")
    @classmethod
    def _validate_allowed_source_kinds(
        cls,
        value: tuple[MarginLiquidationSourceKind, ...],
    ) -> tuple[MarginLiquidationSourceKind, ...]:
        if not value:
            raise ValueError("allowed_source_kinds must be non-empty")
        kinds = tuple(sorted(set(value), key=lambda item: item.value))
        if MarginLiquidationSourceKind.UNKNOWN in kinds:
            raise ValueError("UNKNOWN source kind is not allowed")
        return kinds

    @field_validator("allowed_source_trust")
    @classmethod
    def _validate_allowed_trust(
        cls,
        value: tuple[MarginLiquidationSourceTrust, ...],
    ) -> tuple[MarginLiquidationSourceTrust, ...]:
        if not value:
            raise ValueError("allowed_source_trust must be non-empty")
        return tuple(sorted(set(value), key=lambda item: item.value))

    @field_validator("allowed_source_health")
    @classmethod
    def _validate_allowed_health(
        cls,
        value: tuple[MarginLiquidationSourceHealth, ...],
    ) -> tuple[MarginLiquidationSourceHealth, ...]:
        if not value:
            raise ValueError("allowed_source_health must be non-empty")
        return tuple(sorted(set(value), key=lambda item: item.value))

    @field_validator("allowed_margin_modes")
    @classmethod
    def _validate_allowed_modes(cls, value: tuple[MarginMode, ...]) -> tuple[MarginMode, ...]:
        if not value:
            raise ValueError("allowed_margin_modes must be non-empty")
        modes = tuple(sorted(set(value), key=lambda item: item.value))
        if MarginMode.UNKNOWN in modes:
            raise ValueError("UNKNOWN margin mode is not allowed")
        return modes

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_json_mapping(value, path="metadata")

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> Any:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        expected = deterministic_margin_liquidation_policy_id(self)
        if self.policy_id is not None and self.policy_id != expected:
            raise ValueError("policy_id is not deterministic")
        object.__setattr__(self, "policy_id", expected)
        return self


class MarginLiquidationReadinessDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: MarginLiquidationReadinessDecisionId | None = None
    policy_id: MarginLiquidationPolicyId
    venue_id: str | None = None
    instrument_id: str | None = None
    margin_mode: MarginMode | None = None
    collateral_asset: AssetSymbol | None = None
    margin_asset: AssetSymbol | None = None
    settlement_asset: AssetSymbol | None = None
    ready: bool
    reason: MarginLiquidationDecisionReason
    compatibility: MarginLiquidationCompatibility
    snapshot_id: MarginLiquidationRuleSnapshotId | None = None
    checked_at: datetime
    details: Any = Field(default_factory=dict)

    @field_validator("venue_id", "instrument_id")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "margin liquidation text")

    @field_validator("collateral_asset", "margin_asset", "settlement_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol | None:
        return None if value is None else _asset_symbol(value)

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
        if self.ready and self.reason is not MarginLiquidationDecisionReason.READY:
            raise ValueError("ready margin/liquidation decision requires READY reason")
        if not self.ready and self.reason is MarginLiquidationDecisionReason.READY:
            raise ValueError("not-ready margin/liquidation decision requires non-READY reason")
        if self.ready and self.compatibility in {
            MarginLiquidationCompatibility.UNKNOWN,
            MarginLiquidationCompatibility.NOT_COMPATIBLE,
        }:
            raise ValueError("ready margin/liquidation decision requires compatibility")
        expected = deterministic_margin_liquidation_readiness_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


def deterministic_margin_liquidation_rule_snapshot_id(
    snapshot: MarginLiquidationRuleSnapshot,
) -> MarginLiquidationRuleSnapshotId:
    digest = _digest(_model_identity(snapshot, exclude={"snapshot_id"}))
    return MarginLiquidationRuleSnapshotId(value=f"margin-liquidation-rule:{digest}")


def deterministic_margin_liquidation_policy_id(
    policy: MarginLiquidationPolicy,
) -> MarginLiquidationPolicyId:
    digest = _digest(_model_identity(policy, exclude={"policy_id"}))
    return MarginLiquidationPolicyId(value=f"margin-liquidation-policy:{digest}")


def deterministic_margin_liquidation_readiness_decision_id(
    decision: MarginLiquidationReadinessDecision,
) -> MarginLiquidationReadinessDecisionId:
    digest = _digest(_model_identity(decision, exclude={"decision_id"}))
    return MarginLiquidationReadinessDecisionId(
        value=f"margin-liquidation-readiness:{digest}",
    )


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
