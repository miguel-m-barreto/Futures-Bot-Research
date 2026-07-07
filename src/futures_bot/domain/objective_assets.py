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

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.ids import (
    CollateralValuationDecisionId,
    ObjectiveAssetMeasurementId,
    ObjectiveAssetPolicyId,
    ObjectiveAssetReadinessDecisionId,
)
from futures_bot.domain.time import ensure_aware_utc


class ObjectivePolicyKind(StrEnum):
    ACCUMULATE_ASSET = "ACCUMULATE_ASSET"
    MAXIMIZE_REFERENCE_VALUE = "MAXIMIZE_REFERENCE_VALUE"
    PRESERVE_COLLATERAL_ASSET = "PRESERVE_COLLATERAL_ASSET"
    MATCH_SETTLEMENT_ASSET = "MATCH_SETTLEMENT_ASSET"
    UNKNOWN = "UNKNOWN"


class ObjectiveMeasurementMode(StrEnum):
    NATIVE_ASSET_UNITS = "NATIVE_ASSET_UNITS"
    REFERENCE_ASSET_VALUE = "REFERENCE_ASSET_VALUE"
    COLLATERAL_ADJUSTED_REFERENCE_VALUE = "COLLATERAL_ADJUSTED_REFERENCE_VALUE"
    EXPLICIT_CONVERSION_REQUIRED = "EXPLICIT_CONVERSION_REQUIRED"
    UNKNOWN = "UNKNOWN"


class ObjectiveAssetCompatibility(StrEnum):
    DIRECT_MATCH = "DIRECT_MATCH"
    VALUATION_REQUIRED = "VALUATION_REQUIRED"
    CONVERSION_REQUIRED = "CONVERSION_REQUIRED"
    NOT_COMPATIBLE = "NOT_COMPATIBLE"
    UNKNOWN = "UNKNOWN"


class ObjectiveAssetDecisionReason(StrEnum):
    READY = "READY"
    POLICY_DISABLED = "POLICY_DISABLED"
    OBJECTIVE_ASSET_MISSING = "OBJECTIVE_ASSET_MISSING"
    OBJECTIVE_POLICY_UNKNOWN = "OBJECTIVE_POLICY_UNKNOWN"
    OBJECTIVE_MEASUREMENT_UNKNOWN = "OBJECTIVE_MEASUREMENT_UNKNOWN"
    PNL_ASSET_MISMATCH = "PNL_ASSET_MISMATCH"
    SETTLEMENT_ASSET_MISMATCH = "SETTLEMENT_ASSET_MISMATCH"
    REFERENCE_ASSET_MISMATCH = "REFERENCE_ASSET_MISMATCH"
    VALUATION_REQUIRED = "VALUATION_REQUIRED"
    VALUATION_NOT_READY = "VALUATION_NOT_READY"
    CONVERSION_REQUIRED = "CONVERSION_REQUIRED"
    CONVERSION_NOT_AVAILABLE = "CONVERSION_NOT_AVAILABLE"
    COLLATERAL_VALUATION_NOT_READY = "COLLATERAL_VALUATION_NOT_READY"
    NOT_READY = "NOT_READY"


class ObjectiveAssetPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: ObjectiveAssetPolicyId | None = None
    policy_kind: ObjectivePolicyKind
    objective_asset: AssetSymbol | None = None
    reference_asset: AssetSymbol | None = None
    measurement_mode: ObjectiveMeasurementMode
    valuation_required: bool
    conversion_required: bool
    collateral_adjustment_required: bool
    allow_direct_asset_match: bool
    allow_reference_asset_measurement: bool
    allow_collateral_adjusted_measurement: bool
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @classmethod
    def accumulate(
        cls,
        asset: AssetSymbol | str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Self:
        return cls(
            policy_kind=ObjectivePolicyKind.ACCUMULATE_ASSET,
            objective_asset=_asset_symbol(asset),
            measurement_mode=ObjectiveMeasurementMode.NATIVE_ASSET_UNITS,
            valuation_required=False,
            conversion_required=False,
            collateral_adjustment_required=False,
            allow_direct_asset_match=True,
            allow_reference_asset_measurement=False,
            allow_collateral_adjusted_measurement=False,
            metadata={"factory": "accumulate"} if metadata is None else metadata,
        )

    @classmethod
    def maximize_reference_value(
        cls,
        reference_asset: AssetSymbol | str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Self:
        return cls(
            policy_kind=ObjectivePolicyKind.MAXIMIZE_REFERENCE_VALUE,
            reference_asset=_asset_symbol(reference_asset),
            measurement_mode=ObjectiveMeasurementMode.REFERENCE_ASSET_VALUE,
            valuation_required=True,
            conversion_required=False,
            collateral_adjustment_required=False,
            allow_direct_asset_match=True,
            allow_reference_asset_measurement=True,
            allow_collateral_adjusted_measurement=False,
            metadata=(
                {"factory": "maximize_reference_value"} if metadata is None else metadata
            ),
        )

    @classmethod
    def preserve_collateral_asset(
        cls,
        asset: AssetSymbol | str | None = None,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Self:
        return cls(
            policy_kind=ObjectivePolicyKind.PRESERVE_COLLATERAL_ASSET,
            objective_asset=None if asset is None else _asset_symbol(asset),
            measurement_mode=ObjectiveMeasurementMode.NATIVE_ASSET_UNITS,
            valuation_required=False,
            conversion_required=False,
            collateral_adjustment_required=False,
            allow_direct_asset_match=True,
            allow_reference_asset_measurement=False,
            allow_collateral_adjusted_measurement=False,
            metadata=(
                {"factory": "preserve_collateral_asset"}
                if metadata is None
                else metadata
            ),
        )

    @classmethod
    def disabled(cls, *, metadata: Mapping[str, Any] | None = None) -> Self:
        return cls(
            policy_kind=ObjectivePolicyKind.UNKNOWN,
            measurement_mode=ObjectiveMeasurementMode.UNKNOWN,
            valuation_required=False,
            conversion_required=False,
            collateral_adjustment_required=False,
            allow_direct_asset_match=False,
            allow_reference_asset_measurement=False,
            allow_collateral_adjusted_measurement=False,
            metadata={"policy_disabled": True} if metadata is None else metadata,
        )

    @field_validator("objective_asset", "reference_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol | None:
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
        if (
            self.policy_kind is ObjectivePolicyKind.ACCUMULATE_ASSET
            and self.objective_asset is None
        ):
            raise ValueError("ACCUMULATE_ASSET requires objective_asset")
        if (
            self.policy_kind is ObjectivePolicyKind.MAXIMIZE_REFERENCE_VALUE
            and self.reference_asset is None
        ):
            raise ValueError("MAXIMIZE_REFERENCE_VALUE requires reference_asset")
        if (
            self.measurement_mode
            is ObjectiveMeasurementMode.COLLATERAL_ADJUSTED_REFERENCE_VALUE
            and not self.collateral_adjustment_required
        ):
            raise ValueError("collateral-adjusted measurement requires adjustment gate")
        expected = deterministic_objective_asset_policy_id(self)
        if self.policy_id is not None and self.policy_id != expected:
            raise ValueError("policy_id is not deterministic")
        object.__setattr__(self, "policy_id", expected)
        return self


class ObjectiveAssetReadinessDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: ObjectiveAssetReadinessDecisionId | None = None
    policy_id: ObjectiveAssetPolicyId
    objective_asset: AssetSymbol | None = None
    reference_asset: AssetSymbol | None = None
    pnl_asset: AssetSymbol | None = None
    settlement_asset: AssetSymbol | None = None
    collateral_asset: AssetSymbol | None = None
    ready: bool
    reason: ObjectiveAssetDecisionReason
    compatibility: ObjectiveAssetCompatibility
    valuation_decision_id: ObjectiveAssetMeasurementId | None = None
    collateral_valuation_decision_id: CollateralValuationDecisionId | None = None
    checked_at: datetime
    details: Any = Field(default_factory=dict)

    @field_validator(
        "objective_asset",
        "reference_asset",
        "pnl_asset",
        "settlement_asset",
        "collateral_asset",
        mode="before",
    )
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
        if self.ready and self.reason is not ObjectiveAssetDecisionReason.READY:
            raise ValueError("ready objective asset decision requires READY reason")
        if not self.ready and self.reason is ObjectiveAssetDecisionReason.READY:
            raise ValueError("not-ready objective asset decision requires non-READY reason")
        if self.ready and self.compatibility in {
            ObjectiveAssetCompatibility.UNKNOWN,
            ObjectiveAssetCompatibility.NOT_COMPATIBLE,
        }:
            raise ValueError("ready objective asset decision requires compatible assets")
        expected = deterministic_objective_asset_readiness_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


def deterministic_objective_asset_policy_id(
    policy: ObjectiveAssetPolicy,
) -> ObjectiveAssetPolicyId:
    digest = _digest(_model_identity(policy, exclude={"policy_id"}))
    return ObjectiveAssetPolicyId(value=f"objective-asset-policy:{digest}")


def deterministic_objective_asset_readiness_decision_id(
    decision: ObjectiveAssetReadinessDecision,
) -> ObjectiveAssetReadinessDecisionId:
    digest = _digest(_model_identity(decision, exclude={"decision_id"}))
    return ObjectiveAssetReadinessDecisionId(value=f"objective-asset-readiness:{digest}")


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
