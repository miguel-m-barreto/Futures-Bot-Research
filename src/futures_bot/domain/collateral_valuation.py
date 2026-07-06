from __future__ import annotations

import hashlib
import json
import re
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
    CollateralEligibilityRuleId,
    CollateralHaircutRuleId,
    CollateralValuationDecisionId,
    CollateralValuationPolicyId,
    CollateralValuationSnapshotId,
    CollateralValuationSourceId,
)
from futures_bot.domain.time import ensure_aware_utc

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class CollateralValuationSourceKind(StrEnum):
    MARK_PRICE = "MARK_PRICE"
    INDEX_PRICE = "INDEX_PRICE"
    ORACLE_PRICE = "ORACLE_PRICE"
    VENUE_ACCOUNT_PRICE = "VENUE_ACCOUNT_PRICE"
    MANUAL_REVIEWED_SNAPSHOT = "MANUAL_REVIEWED_SNAPSHOT"
    TEST_FIXTURE = "TEST_FIXTURE"
    UNKNOWN = "UNKNOWN"


class CollateralValuationTrust(StrEnum):
    OFFICIAL = "OFFICIAL"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    TEST_ONLY = "TEST_ONLY"
    UNTRUSTED = "UNTRUSTED"
    UNKNOWN = "UNKNOWN"


class CollateralValuationHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class CollateralEligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    UNKNOWN = "UNKNOWN"


class CollateralHaircutKind(StrEnum):
    NONE = "NONE"
    FIXED_PERCENTAGE = "FIXED_PERCENTAGE"
    VENUE_DEFINED = "VENUE_DEFINED"
    TIERED = "TIERED"
    UNKNOWN = "UNKNOWN"


class CollateralValuationDecisionReason(StrEnum):
    READY = "READY"
    VALUATION_MISSING = "VALUATION_MISSING"
    VALUATION_STALE = "VALUATION_STALE"
    VALUATION_FUTURE_DATED = "VALUATION_FUTURE_DATED"
    VALUATION_SOURCE_UNTRUSTED = "VALUATION_SOURCE_UNTRUSTED"
    VALUATION_SOURCE_UNHEALTHY = "VALUATION_SOURCE_UNHEALTHY"
    HAIRCUT_RULE_MISSING = "HAIRCUT_RULE_MISSING"
    HAIRCUT_RULE_NOT_EFFECTIVE = "HAIRCUT_RULE_NOT_EFFECTIVE"
    HAIRCUT_RULE_UNKNOWN = "HAIRCUT_RULE_UNKNOWN"
    COLLATERAL_NOT_ELIGIBLE = "COLLATERAL_NOT_ELIGIBLE"
    COLLATERAL_ELIGIBILITY_RULE_NOT_EFFECTIVE = (
        "COLLATERAL_ELIGIBILITY_RULE_NOT_EFFECTIVE"
    )
    REFERENCE_ASSET_MISMATCH = "REFERENCE_ASSET_MISMATCH"
    POLICY_DISABLED = "POLICY_DISABLED"
    NOT_READY = "NOT_READY"


class CollateralValuationSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: CollateralValuationSnapshotId | None = None
    collateral_asset: AssetSymbol
    reference_asset: AssetSymbol
    price: Decimal
    source_kind: CollateralValuationSourceKind
    trust: CollateralValuationTrust
    health: CollateralValuationHealth
    observed_at: datetime
    captured_at: datetime
    source_id: CollateralValuationSourceId | None = None
    source_payload_hash: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("collateral_asset", "reference_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol:
        return _asset_symbol(value)

    @field_validator("price", mode="before")
    @classmethod
    def _coerce_price(cls, value: object) -> Decimal:
        return _coerce_decimal(value)

    @field_validator("price")
    @classmethod
    def _validate_price(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0:
            raise ValueError("collateral valuation price must be positive")
        return value

    @field_validator("observed_at", "captured_at")
    @classmethod
    def _validate_timestamp(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("source_payload_hash")
    @classmethod
    def _validate_payload_hash(cls, value: str | None) -> str | None:
        return None if value is None else _sha256_hex(value, "source_payload_hash")

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
        expected = deterministic_collateral_valuation_snapshot_id(self)
        if self.snapshot_id is not None and self.snapshot_id != expected:
            raise ValueError("snapshot_id is not deterministic")
        object.__setattr__(self, "snapshot_id", expected)
        return self


class CollateralHaircutRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: CollateralHaircutRuleId | None = None
    venue_id: str | None = None
    account_mode: str | None = None
    collateral_asset: AssetSymbol
    reference_asset: AssetSymbol
    haircut_kind: CollateralHaircutKind
    haircut_rate: Decimal | None = None
    effective_at: datetime
    expires_at: datetime | None = None
    source_id: CollateralValuationSourceId | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("venue_id", "account_mode")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "haircut rule text")

    @field_validator("collateral_asset", "reference_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol:
        return _asset_symbol(value)

    @field_validator("haircut_rate", mode="before")
    @classmethod
    def _coerce_haircut_rate(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("haircut_rate")
    @classmethod
    def _validate_haircut_rate(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if not value.is_finite() or value < 0 or value > 1:
            raise ValueError("haircut_rate must be between 0 and 1 inclusive")
        return value

    @field_validator("effective_at", "expires_at")
    @classmethod
    def _validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_aware_utc(value)

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
            self.haircut_kind is CollateralHaircutKind.FIXED_PERCENTAGE
            and self.haircut_rate is None
        ):
            raise ValueError("FIXED_PERCENTAGE haircut requires haircut_rate")
        if self.haircut_kind is CollateralHaircutKind.NONE:
            if self.haircut_rate is not None and self.haircut_rate != Decimal("0"):
                raise ValueError("NONE haircut implies zero haircut_rate")
            object.__setattr__(self, "haircut_rate", Decimal("0"))
        if self.expires_at is not None and self.expires_at <= self.effective_at:
            raise ValueError("expires_at must be after effective_at")
        expected = deterministic_collateral_haircut_rule_id(self)
        if self.rule_id is not None and self.rule_id != expected:
            raise ValueError("rule_id is not deterministic")
        object.__setattr__(self, "rule_id", expected)
        return self


class CollateralEligibilityRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    eligibility_rule_id: CollateralEligibilityRuleId | None = None
    venue_id: str | None = None
    account_mode: str | None = None
    collateral_asset: AssetSymbol
    eligibility_status: CollateralEligibilityStatus
    effective_at: datetime
    expires_at: datetime | None = None
    reason: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("venue_id", "account_mode", "reason")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "eligibility rule text")

    @field_validator("collateral_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol:
        return _asset_symbol(value)

    @field_validator("effective_at", "expires_at")
    @classmethod
    def _validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_aware_utc(value)

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_json_mapping(value, path="metadata")

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> Any:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.expires_at is not None and self.expires_at <= self.effective_at:
            raise ValueError("expires_at must be after effective_at")
        expected = deterministic_collateral_eligibility_rule_id(self)
        if self.eligibility_rule_id is not None and self.eligibility_rule_id != expected:
            raise ValueError("eligibility_rule_id is not deterministic")
        object.__setattr__(self, "eligibility_rule_id", expected)
        return self


class CollateralValuationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: CollateralValuationPolicyId | None = None
    valuation_required: bool
    haircut_required: bool
    eligibility_required: bool
    max_valuation_age_ms: int | None = None
    allow_manual_review_sources: bool = False
    allow_test_fixture_sources: bool = False
    allow_untrusted_sources: bool = False
    allow_degraded_sources: bool = False
    required_reference_asset: AssetSymbol | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @classmethod
    def strict(
        cls,
        *,
        reference_asset: AssetSymbol | str,
        max_valuation_age_ms: int = 60_000,
    ) -> Self:
        return cls(
            valuation_required=True,
            haircut_required=True,
            eligibility_required=True,
            max_valuation_age_ms=max_valuation_age_ms,
            required_reference_asset=_asset_symbol(reference_asset),
            metadata={"policy": "strict"},
        )

    @field_validator("required_reference_asset", mode="before")
    @classmethod
    def _coerce_reference_asset(cls, value: object) -> AssetSymbol | None:
        return None if value is None else _asset_symbol(value)

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_json_mapping(value, path="metadata")

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> Any:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.valuation_required and (
            self.max_valuation_age_ms is None or self.max_valuation_age_ms <= 0
        ):
            raise ValueError("max_valuation_age_ms must be > 0 when valuation is required")
        expected = deterministic_collateral_valuation_policy_id(self)
        if self.policy_id is not None and self.policy_id != expected:
            raise ValueError("policy_id is not deterministic")
        object.__setattr__(self, "policy_id", expected)
        return self


class CollateralValuationReadinessDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: CollateralValuationDecisionId | None = None
    collateral_asset: AssetSymbol
    reference_asset: AssetSymbol
    ready: bool
    reason: CollateralValuationDecisionReason
    valuation_snapshot: CollateralValuationSnapshot | None = None
    haircut_rule: CollateralHaircutRule | None = None
    eligibility_rule: CollateralEligibilityRule | None = None
    checked_at: datetime
    effective_value_multiplier: Decimal | None = None
    details: Any = Field(default_factory=dict)

    @field_validator("collateral_asset", "reference_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol:
        return _asset_symbol(value)

    @field_validator("checked_at")
    @classmethod
    def _validate_checked_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("effective_value_multiplier", mode="before")
    @classmethod
    def _coerce_multiplier(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("effective_value_multiplier")
    @classmethod
    def _validate_multiplier(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if not value.is_finite() or value < 0 or value > 1:
            raise ValueError("effective_value_multiplier must be between 0 and 1 inclusive")
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
        if self.ready and self.reason is not CollateralValuationDecisionReason.READY:
            raise ValueError("ready collateral valuation decision requires READY reason")
        if not self.ready and self.reason is CollateralValuationDecisionReason.READY:
            raise ValueError("not-ready collateral valuation decision requires non-READY reason")
        expected = deterministic_collateral_valuation_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


def deterministic_collateral_valuation_snapshot_id(
    snapshot: CollateralValuationSnapshot,
) -> CollateralValuationSnapshotId:
    digest = _digest(_model_identity(snapshot, exclude={"snapshot_id"}))
    return CollateralValuationSnapshotId(value=f"collateral-valuation-snapshot:{digest}")


def deterministic_collateral_haircut_rule_id(
    rule: CollateralHaircutRule,
) -> CollateralHaircutRuleId:
    digest = _digest(_model_identity(rule, exclude={"rule_id"}))
    return CollateralHaircutRuleId(value=f"collateral-haircut-rule:{digest}")


def deterministic_collateral_eligibility_rule_id(
    rule: CollateralEligibilityRule,
) -> CollateralEligibilityRuleId:
    digest = _digest(_model_identity(rule, exclude={"eligibility_rule_id"}))
    return CollateralEligibilityRuleId(value=f"collateral-eligibility-rule:{digest}")


def deterministic_collateral_valuation_policy_id(
    policy: CollateralValuationPolicy,
) -> CollateralValuationPolicyId:
    digest = _digest(_model_identity(policy, exclude={"policy_id"}))
    return CollateralValuationPolicyId(value=f"collateral-valuation-policy:{digest}")


def deterministic_collateral_valuation_decision_id(
    decision: CollateralValuationReadinessDecision,
) -> CollateralValuationDecisionId:
    digest = _digest(_model_identity(decision, exclude={"decision_id"}))
    return CollateralValuationDecisionId(value=f"collateral-valuation-decision:{digest}")


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
    if isinstance(value, Decimal):
        decimal = value
    elif isinstance(value, int | str):
        try:
            decimal = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("decimal value is invalid") from exc
    else:
        raise ValueError("decimal value must be a Decimal, int, or string")
    if not decimal.is_finite():
        raise ValueError("decimal value must be finite")
    return decimal


def _trimmed(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(f"{name} must be non-empty")
    return trimmed


def _sha256_hex(value: str, name: str) -> str:
    if not _SHA256_HEX_RE.fullmatch(value):
        raise ValueError(f"{name} must be lowercase sha256 hex")
    return value


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
