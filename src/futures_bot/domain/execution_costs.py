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
    ExecutionCostPolicyId,
    ExecutionCostReadinessDecisionId,
    ExecutionCostRuleSnapshotId,
)
from futures_bot.domain.time import ensure_aware_utc


class ExecutionCostSourceKind(StrEnum):
    VENUE_FEE_SCHEDULE = "VENUE_FEE_SCHEDULE"
    VENUE_FUNDING_RULES = "VENUE_FUNDING_RULES"
    VENUE_DEPTH_RULES = "VENUE_DEPTH_RULES"
    VENUE_ACCOUNT_CONFIG = "VENUE_ACCOUNT_CONFIG"
    MANUAL_REVIEWED_RULE = "MANUAL_REVIEWED_RULE"
    TEST_FIXTURE = "TEST_FIXTURE"
    UNKNOWN = "UNKNOWN"


class ExecutionCostSourceTrust(StrEnum):
    OFFICIAL = "OFFICIAL"
    MANUAL_REVIEWED_OFFICIAL = "MANUAL_REVIEWED_OFFICIAL"
    TEST_ONLY = "TEST_ONLY"
    UNTRUSTED = "UNTRUSTED"
    UNKNOWN = "UNKNOWN"


class ExecutionCostSourceHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class FeeModelKind(StrEnum):
    MAKER_TAKER_BPS = "MAKER_TAKER_BPS"
    FLAT_BPS = "FLAT_BPS"
    TIERED_BY_VOLUME = "TIERED_BY_VOLUME"
    INSTRUMENT_SPECIFIC = "INSTRUMENT_SPECIFIC"
    NOT_PROVIDED = "NOT_PROVIDED"
    UNKNOWN = "UNKNOWN"


class FundingModelKind(StrEnum):
    PERIODIC_RATE = "PERIODIC_RATE"
    VENUE_FUNDING_SCHEDULE = "VENUE_FUNDING_SCHEDULE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_PROVIDED = "NOT_PROVIDED"
    UNKNOWN = "UNKNOWN"


class DepthModelKind(StrEnum):
    TOP_OF_BOOK_ONLY = "TOP_OF_BOOK_ONLY"
    ORDER_BOOK_DEPTH = "ORDER_BOOK_DEPTH"
    DEPTH_CURVE = "DEPTH_CURVE"
    CONSERVATIVE_PLACEHOLDER = "CONSERVATIVE_PLACEHOLDER"
    NOT_PROVIDED = "NOT_PROVIDED"
    UNKNOWN = "UNKNOWN"


class ExecutionCostCompatibility(StrEnum):
    DIRECT_MATCH = "DIRECT_MATCH"
    ASSET_MISMATCH = "ASSET_MISMATCH"
    MODEL_UNSUPPORTED = "MODEL_UNSUPPORTED"
    NOT_COMPATIBLE = "NOT_COMPATIBLE"
    UNKNOWN = "UNKNOWN"


class ExecutionCostDecisionReason(StrEnum):
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
    FEE_MODEL_UNKNOWN = "FEE_MODEL_UNKNOWN"
    FEE_MODEL_UNSUPPORTED = "FEE_MODEL_UNSUPPORTED"
    FEE_MODEL_MISSING = "FEE_MODEL_MISSING"
    MAKER_FEE_MISSING = "MAKER_FEE_MISSING"
    TAKER_FEE_MISSING = "TAKER_FEE_MISSING"
    FEE_ASSET_MISSING = "FEE_ASSET_MISSING"
    FEE_ASSET_MISMATCH = "FEE_ASSET_MISMATCH"
    FUNDING_MODEL_UNKNOWN = "FUNDING_MODEL_UNKNOWN"
    FUNDING_MODEL_UNSUPPORTED = "FUNDING_MODEL_UNSUPPORTED"
    FUNDING_MODEL_MISSING = "FUNDING_MODEL_MISSING"
    FUNDING_INTERVAL_MISSING = "FUNDING_INTERVAL_MISSING"
    FUNDING_ASSET_MISSING = "FUNDING_ASSET_MISSING"
    FUNDING_ASSET_MISMATCH = "FUNDING_ASSET_MISMATCH"
    DEPTH_MODEL_UNKNOWN = "DEPTH_MODEL_UNKNOWN"
    DEPTH_MODEL_UNSUPPORTED = "DEPTH_MODEL_UNSUPPORTED"
    DEPTH_MODEL_MISSING = "DEPTH_MODEL_MISSING"
    MIN_DEPTH_NOTIONAL_MISSING = "MIN_DEPTH_NOTIONAL_MISSING"
    DEPTH_REFERENCE_ASSET_MISSING = "DEPTH_REFERENCE_ASSET_MISSING"
    DEPTH_REFERENCE_ASSET_MISMATCH = "DEPTH_REFERENCE_ASSET_MISMATCH"
    MAX_SPREAD_MISSING = "MAX_SPREAD_MISSING"
    NOT_READY = "NOT_READY"
    UNKNOWN = "UNKNOWN"


class ExecutionCostRuleSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: ExecutionCostRuleSnapshotId | None = None
    venue_id: str
    instrument_id: str | None = None
    fee_asset: AssetSymbol | None = None
    funding_asset: AssetSymbol | None = None
    depth_reference_asset: AssetSymbol | None = None
    fee_model_kind: FeeModelKind
    maker_fee_rate: Decimal | None = None
    taker_fee_rate: Decimal | None = None
    flat_fee_rate: Decimal | None = None
    fee_tier_id: str | None = None
    funding_model_kind: FundingModelKind
    funding_interval_ms: int | None = None
    funding_rate_cap: Decimal | None = None
    depth_model_kind: DepthModelKind
    min_depth_notional: Decimal | None = None
    max_spread_bps: Decimal | None = None
    observed_at: datetime
    captured_at: datetime
    source_kind: ExecutionCostSourceKind
    source_trust: ExecutionCostSourceTrust
    source_health: ExecutionCostSourceHealth
    source_record_id: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("venue_id", "instrument_id", "fee_tier_id", "source_record_id")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "execution cost text")

    @field_validator("fee_asset", "funding_asset", "depth_reference_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol | None:
        return None if value is None else _asset_symbol(value)

    @field_validator(
        "maker_fee_rate",
        "taker_fee_rate",
        "flat_fee_rate",
        "funding_rate_cap",
        "min_depth_notional",
        "max_spread_bps",
        mode="before",
    )
    @classmethod
    def _coerce_decimal_field(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator(
        "maker_fee_rate",
        "taker_fee_rate",
        "flat_fee_rate",
        "funding_rate_cap",
        "max_spread_bps",
    )
    @classmethod
    def _validate_non_negative_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("execution cost rate values must be >= 0")
        return value

    @field_validator("min_depth_notional")
    @classmethod
    def _validate_positive_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value <= 0):
            raise ValueError("min_depth_notional must be positive")
        return value

    @field_validator("funding_interval_ms")
    @classmethod
    def _validate_funding_interval(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("funding_interval_ms must be positive")
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
        expected = deterministic_execution_cost_rule_snapshot_id(self)
        if self.snapshot_id is not None and self.snapshot_id != expected:
            raise ValueError("snapshot_id is not deterministic")
        object.__setattr__(self, "snapshot_id", expected)
        return self


class ExecutionCostPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: ExecutionCostPolicyId | None = None
    max_snapshot_age: int
    require_source_record: bool
    allowed_source_kinds: tuple[ExecutionCostSourceKind, ...]
    allowed_source_trust: tuple[ExecutionCostSourceTrust, ...]
    allowed_source_health: tuple[ExecutionCostSourceHealth, ...]
    allowed_fee_models: tuple[FeeModelKind, ...]
    allowed_funding_models: tuple[FundingModelKind, ...]
    allowed_depth_models: tuple[DepthModelKind, ...]
    require_fee_model: bool
    require_maker_fee: bool
    require_taker_fee: bool
    require_fee_asset_match: bool
    require_funding_model: bool
    require_funding_interval: bool
    require_funding_asset_match: bool
    require_depth_model: bool
    require_min_depth_notional: bool
    require_depth_reference_asset_match: bool
    require_max_spread_bps: bool
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @classmethod
    def strict_official(cls, *, metadata: Mapping[str, Any] | None = None) -> Self:
        return cls(
            max_snapshot_age=300_000,
            require_source_record=True,
            allowed_source_kinds=(
                ExecutionCostSourceKind.VENUE_FEE_SCHEDULE,
                ExecutionCostSourceKind.VENUE_FUNDING_RULES,
                ExecutionCostSourceKind.VENUE_DEPTH_RULES,
                ExecutionCostSourceKind.VENUE_ACCOUNT_CONFIG,
                ExecutionCostSourceKind.MANUAL_REVIEWED_RULE,
            ),
            allowed_source_trust=(ExecutionCostSourceTrust.OFFICIAL,),
            allowed_source_health=(ExecutionCostSourceHealth.HEALTHY,),
            allowed_fee_models=(
                FeeModelKind.MAKER_TAKER_BPS,
                FeeModelKind.TIERED_BY_VOLUME,
                FeeModelKind.INSTRUMENT_SPECIFIC,
            ),
            allowed_funding_models=(
                FundingModelKind.PERIODIC_RATE,
                FundingModelKind.VENUE_FUNDING_SCHEDULE,
                FundingModelKind.NOT_APPLICABLE,
            ),
            allowed_depth_models=(
                DepthModelKind.TOP_OF_BOOK_ONLY,
                DepthModelKind.ORDER_BOOK_DEPTH,
                DepthModelKind.DEPTH_CURVE,
                DepthModelKind.CONSERVATIVE_PLACEHOLDER,
            ),
            require_fee_model=True,
            require_maker_fee=True,
            require_taker_fee=True,
            require_fee_asset_match=True,
            require_funding_model=True,
            require_funding_interval=True,
            require_funding_asset_match=True,
            require_depth_model=True,
            require_min_depth_notional=True,
            require_depth_reference_asset_match=True,
            require_max_spread_bps=True,
            metadata={"factory": "strict_official"} if metadata is None else metadata,
        )

    @classmethod
    def research_fixture(cls, *, metadata: Mapping[str, Any] | None = None) -> Self:
        return cls(
            max_snapshot_age=300_000,
            require_source_record=True,
            allowed_source_kinds=(ExecutionCostSourceKind.TEST_FIXTURE,),
            allowed_source_trust=(ExecutionCostSourceTrust.TEST_ONLY,),
            allowed_source_health=(ExecutionCostSourceHealth.HEALTHY,),
            allowed_fee_models=(FeeModelKind.MAKER_TAKER_BPS,),
            allowed_funding_models=(FundingModelKind.PERIODIC_RATE,),
            allowed_depth_models=(DepthModelKind.CONSERVATIVE_PLACEHOLDER,),
            require_fee_model=True,
            require_maker_fee=True,
            require_taker_fee=True,
            require_fee_asset_match=True,
            require_funding_model=True,
            require_funding_interval=True,
            require_funding_asset_match=True,
            require_depth_model=True,
            require_min_depth_notional=True,
            require_depth_reference_asset_match=True,
            require_max_spread_bps=True,
            metadata={"factory": "research_fixture"} if metadata is None else metadata,
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
        value: tuple[ExecutionCostSourceKind, ...],
    ) -> tuple[ExecutionCostSourceKind, ...]:
        if not value:
            raise ValueError("allowed_source_kinds must be non-empty")
        kinds = tuple(sorted(set(value), key=lambda item: item.value))
        if ExecutionCostSourceKind.UNKNOWN in kinds:
            raise ValueError("UNKNOWN source kind is not allowed")
        return kinds

    @field_validator("allowed_source_trust")
    @classmethod
    def _validate_allowed_source_trust(
        cls,
        value: tuple[ExecutionCostSourceTrust, ...],
    ) -> tuple[ExecutionCostSourceTrust, ...]:
        if not value:
            raise ValueError("allowed_source_trust must be non-empty")
        return tuple(sorted(set(value), key=lambda item: item.value))

    @field_validator("allowed_source_health")
    @classmethod
    def _validate_allowed_source_health(
        cls,
        value: tuple[ExecutionCostSourceHealth, ...],
    ) -> tuple[ExecutionCostSourceHealth, ...]:
        if not value:
            raise ValueError("allowed_source_health must be non-empty")
        return tuple(sorted(set(value), key=lambda item: item.value))

    @field_validator("allowed_fee_models")
    @classmethod
    def _validate_allowed_fee_models(
        cls,
        value: tuple[FeeModelKind, ...],
    ) -> tuple[FeeModelKind, ...]:
        models = tuple(sorted(set(value), key=lambda item: item.value))
        if FeeModelKind.UNKNOWN in models:
            raise ValueError("UNKNOWN fee model is not allowed")
        return models

    @field_validator("allowed_funding_models")
    @classmethod
    def _validate_allowed_funding_models(
        cls,
        value: tuple[FundingModelKind, ...],
    ) -> tuple[FundingModelKind, ...]:
        models = tuple(sorted(set(value), key=lambda item: item.value))
        if FundingModelKind.UNKNOWN in models:
            raise ValueError("UNKNOWN funding model is not allowed")
        return models

    @field_validator("allowed_depth_models")
    @classmethod
    def _validate_allowed_depth_models(
        cls,
        value: tuple[DepthModelKind, ...],
    ) -> tuple[DepthModelKind, ...]:
        models = tuple(sorted(set(value), key=lambda item: item.value))
        if DepthModelKind.UNKNOWN in models:
            raise ValueError("UNKNOWN depth model is not allowed")
        return models

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_json_mapping(value, path="metadata")

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> Any:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.require_fee_model and not self.allowed_fee_models:
            raise ValueError("allowed_fee_models must be non-empty when fee model is required")
        if self.require_funding_model and not self.allowed_funding_models:
            raise ValueError(
                "allowed_funding_models must be non-empty when funding model is required",
            )
        if self.require_depth_model and not self.allowed_depth_models:
            raise ValueError(
                "allowed_depth_models must be non-empty when depth model is required",
            )
        expected = deterministic_execution_cost_policy_id(self)
        if self.policy_id is not None and self.policy_id != expected:
            raise ValueError("policy_id is not deterministic")
        object.__setattr__(self, "policy_id", expected)
        return self


class ExecutionCostReadinessDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: ExecutionCostReadinessDecisionId | None = None
    policy_id: ExecutionCostPolicyId
    venue_id: str | None = None
    instrument_id: str | None = None
    fee_asset: AssetSymbol | None = None
    funding_asset: AssetSymbol | None = None
    depth_reference_asset: AssetSymbol | None = None
    ready: bool
    reason: ExecutionCostDecisionReason
    compatibility: ExecutionCostCompatibility
    snapshot_id: ExecutionCostRuleSnapshotId | None = None
    checked_at: datetime
    details: Any = Field(default_factory=dict)

    @field_validator("venue_id", "instrument_id")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "execution cost text")

    @field_validator("fee_asset", "funding_asset", "depth_reference_asset", mode="before")
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
        if self.ready and self.reason is not ExecutionCostDecisionReason.READY:
            raise ValueError("ready execution cost decision requires READY reason")
        if not self.ready and self.reason is ExecutionCostDecisionReason.READY:
            raise ValueError("not-ready execution cost decision requires non-READY reason")
        if self.ready and self.compatibility in {
            ExecutionCostCompatibility.UNKNOWN,
            ExecutionCostCompatibility.NOT_COMPATIBLE,
        }:
            raise ValueError("ready execution cost decision requires compatibility")
        expected = deterministic_execution_cost_readiness_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


def deterministic_execution_cost_rule_snapshot_id(
    snapshot: ExecutionCostRuleSnapshot,
) -> ExecutionCostRuleSnapshotId:
    digest = _digest(_model_identity(snapshot, exclude={"snapshot_id"}))
    return ExecutionCostRuleSnapshotId(value=f"execution-cost-rule:{digest}")


def deterministic_execution_cost_policy_id(
    policy: ExecutionCostPolicy,
) -> ExecutionCostPolicyId:
    digest = _digest(_model_identity(policy, exclude={"policy_id"}))
    return ExecutionCostPolicyId(value=f"execution-cost-policy:{digest}")


def deterministic_execution_cost_readiness_decision_id(
    decision: ExecutionCostReadinessDecision,
) -> ExecutionCostReadinessDecisionId:
    digest = _digest(_model_identity(decision, exclude={"decision_id"}))
    return ExecutionCostReadinessDecisionId(value=f"execution-cost-readiness:{digest}")


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
