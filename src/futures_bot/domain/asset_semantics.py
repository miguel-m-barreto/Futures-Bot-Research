from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from math import isfinite
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from futures_bot.domain.collateral_valuation import (
    CollateralValuationDecisionReason,
    CollateralValuationReadinessDecision,
)
from futures_bot.domain.ids import (
    AssetSemanticsId,
    AssetSymbolId,
    CollateralValuationPolicyId,
    ContractAssetSemanticsId,
    EconomicExposureId,
    ObjectiveAssetPolicyId,
)
from futures_bot.domain.time import ensure_aware_utc


class AssetClass(StrEnum):
    STABLECOIN = "STABLECOIN"
    CRYPTO = "CRYPTO"
    FIAT = "FIAT"
    EXCHANGE_TOKEN = "EXCHANGE_TOKEN"
    SYNTHETIC = "SYNTHETIC"
    UNKNOWN = "UNKNOWN"


class AssetRole(StrEnum):
    BASE = "BASE"
    QUOTE = "QUOTE"
    MARGIN = "MARGIN"
    COLLATERAL = "COLLATERAL"
    SETTLEMENT = "SETTLEMENT"
    PNL = "PNL"
    FEE = "FEE"
    OBJECTIVE = "OBJECTIVE"
    VALUATION_REFERENCE = "VALUATION_REFERENCE"
    INDEX_REFERENCE = "INDEX_REFERENCE"


class ContractPayoffKind(StrEnum):
    LINEAR = "LINEAR"
    INVERSE = "INVERSE"
    QUANTO = "QUANTO"
    UNKNOWN = "UNKNOWN"


class CollateralMode(StrEnum):
    SINGLE_ASSET = "SINGLE_ASSET"
    MULTI_ASSET = "MULTI_ASSET"
    PORTFOLIO_MARGIN = "PORTFOLIO_MARGIN"
    CROSS_COLLATERAL = "CROSS_COLLATERAL"
    UNKNOWN = "UNKNOWN"


class SettlementMode(StrEnum):
    SINGLE_ASSET = "SINGLE_ASSET"
    MULTI_ASSET = "MULTI_ASSET"
    EXCHANGE_DEFINED = "EXCHANGE_DEFINED"
    UNKNOWN = "UNKNOWN"


class ValuationRequirement(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED_FOR_COLLATERAL = "REQUIRED_FOR_COLLATERAL"
    REQUIRED_FOR_OBJECTIVE = "REQUIRED_FOR_OBJECTIVE"
    REQUIRED_FOR_MARGIN = "REQUIRED_FOR_MARGIN"
    REQUIRED_FOR_PNL = "REQUIRED_FOR_PNL"
    REQUIRED_FOR_CROSS_VENUE_COMPARISON = "REQUIRED_FOR_CROSS_VENUE_COMPARISON"
    REQUIRED_UNKNOWN = "REQUIRED_UNKNOWN"


class AssetSemanticsReadinessReason(StrEnum):
    READY = "READY"
    ASSET_MISSING = "ASSET_MISSING"
    PAYOFF_KIND_UNKNOWN = "PAYOFF_KIND_UNKNOWN"
    COLLATERAL_MODE_UNKNOWN = "COLLATERAL_MODE_UNKNOWN"
    SETTLEMENT_MODE_UNKNOWN = "SETTLEMENT_MODE_UNKNOWN"
    VALUATION_REQUIRED = "VALUATION_REQUIRED"
    HAIRCUT_RULES_REQUIRED = "HAIRCUT_RULES_REQUIRED"
    CONVERSION_RULES_REQUIRED = "CONVERSION_RULES_REQUIRED"
    OBJECTIVE_ASSET_VALUATION_REQUIRED = "OBJECTIVE_ASSET_VALUATION_REQUIRED"
    ECONOMIC_EXPOSURE_MISMATCH = "ECONOMIC_EXPOSURE_MISMATCH"


class CrossVenueExposureComparabilityReason(StrEnum):
    COMPARABLE = "COMPARABLE"
    BASE_ASSET_MISMATCH = "BASE_ASSET_MISMATCH"
    QUOTE_ASSET_MISMATCH = "QUOTE_ASSET_MISMATCH"
    PAYOFF_KIND_MISMATCH = "PAYOFF_KIND_MISMATCH"
    SETTLEMENT_ASSET_MISMATCH = "SETTLEMENT_ASSET_MISMATCH"
    PNL_ASSET_MISMATCH = "PNL_ASSET_MISMATCH"
    CONTRACT_SIZE_MISMATCH = "CONTRACT_SIZE_MISMATCH"
    VALUATION_REFERENCE_MISMATCH = "VALUATION_REFERENCE_MISMATCH"


class AssetDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    asset_id: AssetSymbolId | None = None
    symbol: str
    asset_class: AssetClass
    venue_id: str | None = None
    canonical_symbol: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("symbol", "canonical_symbol", mode="before")
    @classmethod
    def _normalize_symbol(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("asset symbol must be a string")
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("asset symbol must be non-empty")
        return normalized

    @field_validator("venue_id")
    @classmethod
    def _validate_venue_id(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "venue_id")

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_identity(self) -> Self:
        expected = deterministic_asset_symbol_id(self)
        if self.asset_id is not None and self.asset_id != expected:
            raise ValueError("asset_id is not deterministic")
        object.__setattr__(self, "asset_id", expected)
        return self


class AssetRoleBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: AssetSemanticsId | None = None
    role: AssetRole
    asset: AssetDescriptor

    @model_validator(mode="after")
    def _validate_identity(self) -> Self:
        expected = deterministic_asset_role_binding_id(self)
        if self.binding_id is not None and self.binding_id != expected:
            raise ValueError("binding_id is not deterministic")
        object.__setattr__(self, "binding_id", expected)
        return self


class ContractAssetSemantics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    semantics_id: ContractAssetSemanticsId | None = None
    venue_id: str
    instrument_id: str
    base_asset: AssetDescriptor
    quote_asset: AssetDescriptor
    margin_asset: AssetDescriptor
    settlement_asset: AssetDescriptor
    pnl_asset: AssetDescriptor
    fee_asset: AssetDescriptor | None = None
    collateral_assets: tuple[AssetDescriptor, ...]
    valuation_reference_asset: AssetDescriptor
    objective_asset: AssetDescriptor | None = None
    payoff_kind: ContractPayoffKind
    collateral_mode: CollateralMode
    settlement_mode: SettlementMode
    contract_size: Decimal | None = None
    contract_value_asset: AssetDescriptor | None = None
    requires_collateral_valuation: bool
    requires_haircut_rules: bool
    requires_conversion_rules: bool
    requires_objective_valuation: bool
    collateral_valuation_policy_id: CollateralValuationPolicyId | None = None
    objective_asset_policy_id: ObjectiveAssetPolicyId | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("venue_id", "instrument_id")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _trimmed(value, "contract asset semantics text")

    @field_validator("contract_size", mode="before")
    @classmethod
    def _coerce_contract_size(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if not self.collateral_assets:
            raise ValueError("collateral_assets must be non-empty")
        if self.contract_size is not None and self.contract_size <= 0:
            raise ValueError("contract_size must be > 0")
        if (
            self.payoff_kind in {ContractPayoffKind.INVERSE, ContractPayoffKind.QUANTO}
            and self.contract_value_asset is None
        ):
            raise ValueError("inverse/quanto contracts require contract_value_asset")
        expected = deterministic_contract_asset_semantics_id(self)
        if self.semantics_id is not None and self.semantics_id != expected:
            raise ValueError("semantics_id is not deterministic")
        object.__setattr__(self, "semantics_id", expected)
        return self


class ContractAssetSemanticsReadinessDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: AssetSemanticsId | None = None
    semantics_id: ContractAssetSemanticsId
    ready: bool
    reason: AssetSemanticsReadinessReason
    valuation_requirements: tuple[ValuationRequirement, ...]
    details: Any

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.ready and self.reason is not AssetSemanticsReadinessReason.READY:
            raise ValueError("ready asset semantics require READY reason")
        if not self.ready and self.reason is AssetSemanticsReadinessReason.READY:
            raise ValueError("not-ready asset semantics require non-READY reason")
        expected = deterministic_contract_asset_semantics_readiness_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


class EconomicExposureDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    exposure_id: EconomicExposureId | None = None
    venue_id: str
    instrument_id: str
    base_asset: AssetDescriptor
    quote_asset: AssetDescriptor
    payoff_kind: ContractPayoffKind
    settlement_asset: AssetDescriptor
    pnl_asset: AssetDescriptor
    valuation_reference_asset: AssetDescriptor
    contract_size: Decimal | None = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("venue_id", "instrument_id")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _trimmed(value, "economic exposure text")

    @field_validator("contract_size", mode="before")
    @classmethod
    def _coerce_contract_size(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_identity(self) -> Self:
        if self.contract_size is not None and self.contract_size <= 0:
            raise ValueError("contract_size must be > 0")
        expected = deterministic_economic_exposure_id(self)
        if self.exposure_id is not None and self.exposure_id != expected:
            raise ValueError("exposure_id is not deterministic")
        object.__setattr__(self, "exposure_id", expected)
        return self


class CrossVenueExposureComparabilityDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: AssetSemanticsId | None = None
    comparable: bool
    reason: CrossVenueExposureComparabilityReason
    details: Any

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.comparable and self.reason is not CrossVenueExposureComparabilityReason.COMPARABLE:
            raise ValueError("comparable exposures require COMPARABLE reason")
        if not self.comparable and self.reason is CrossVenueExposureComparabilityReason.COMPARABLE:
            raise ValueError("non-comparable exposures require non-COMPARABLE reason")
        expected = deterministic_cross_venue_exposure_comparability_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


def validate_contract_asset_semantics_readiness(
    semantics: ContractAssetSemantics,
) -> ContractAssetSemanticsReadinessDecision:
    valuation_requirements = _valuation_requirements(semantics)
    reason = _readiness_reason(semantics)
    ready = reason is AssetSemanticsReadinessReason.READY
    return ContractAssetSemanticsReadinessDecision(
        semantics_id=_required_contract_asset_semantics_id(semantics),
        ready=ready,
        reason=reason,
        valuation_requirements=valuation_requirements,
        details={
            "venue_id": semantics.venue_id,
            "instrument_id": semantics.instrument_id,
            "payoff_kind": semantics.payoff_kind.value,
            "collateral_mode": semantics.collateral_mode.value,
            "settlement_mode": semantics.settlement_mode.value,
        },
    )


def validate_contract_asset_semantics_collateral_readiness(
    semantics: ContractAssetSemantics,
    collateral_decisions: Sequence[CollateralValuationReadinessDecision] | None = None,
) -> ContractAssetSemanticsReadinessDecision:
    if collateral_decisions is None:
        return validate_contract_asset_semantics_readiness(semantics)
    valuation_requirements = _valuation_requirements(semantics)
    reason = _readiness_reason_with_collateral_decisions(
        semantics,
        tuple(collateral_decisions),
    )
    ready = reason is AssetSemanticsReadinessReason.READY
    return ContractAssetSemanticsReadinessDecision(
        semantics_id=_required_contract_asset_semantics_id(semantics),
        ready=ready,
        reason=reason,
        valuation_requirements=valuation_requirements,
        details={
            "venue_id": semantics.venue_id,
            "instrument_id": semantics.instrument_id,
            "payoff_kind": semantics.payoff_kind.value,
            "collateral_mode": semantics.collateral_mode.value,
            "settlement_mode": semantics.settlement_mode.value,
            "collateral_decision_ids": tuple(
                str(decision.decision_id)
                for decision in collateral_decisions
                if decision.decision_id is not None
            ),
        },
    )


def compare_cross_venue_economic_exposures(
    left: EconomicExposureDescriptor,
    right: EconomicExposureDescriptor,
) -> CrossVenueExposureComparabilityDecision:
    reason = _comparability_reason(left, right)
    return CrossVenueExposureComparabilityDecision(
        comparable=reason is CrossVenueExposureComparabilityReason.COMPARABLE,
        reason=reason,
        details={
            "left": _exposure_details(left),
            "right": _exposure_details(right),
        },
    )


def economic_exposures_are_comparable(
    left: EconomicExposureDescriptor,
    right: EconomicExposureDescriptor,
) -> bool:
    return compare_cross_venue_economic_exposures(left, right).comparable


def deterministic_asset_symbol_id(asset: AssetDescriptor) -> AssetSymbolId:
    digest = _digest(_model_identity(asset, exclude={"asset_id"}))
    return AssetSymbolId(value=f"asset-symbol:{digest}")


def deterministic_asset_role_binding_id(binding: AssetRoleBinding) -> AssetSemanticsId:
    digest = _digest(_model_identity(binding, exclude={"binding_id"}))
    return AssetSemanticsId(value=f"asset-role-binding:{digest}")


def deterministic_contract_asset_semantics_id(
    semantics: ContractAssetSemantics,
) -> ContractAssetSemanticsId:
    digest = _digest(_model_identity(semantics, exclude={"semantics_id"}))
    return ContractAssetSemanticsId(value=f"contract-asset-semantics:{digest}")


def deterministic_contract_asset_semantics_readiness_decision_id(
    decision: ContractAssetSemanticsReadinessDecision,
) -> AssetSemanticsId:
    digest = _digest(_model_identity(decision, exclude={"decision_id"}))
    return AssetSemanticsId(value=f"asset-semantics-readiness:{digest}")


def deterministic_economic_exposure_id(
    exposure: EconomicExposureDescriptor,
) -> EconomicExposureId:
    digest = _digest(_model_identity(exposure, exclude={"exposure_id"}))
    return EconomicExposureId(value=f"economic-exposure:{digest}")


def deterministic_cross_venue_exposure_comparability_decision_id(
    decision: CrossVenueExposureComparabilityDecision,
) -> AssetSemanticsId:
    digest = _digest(_model_identity(decision, exclude={"decision_id"}))
    return AssetSemanticsId(value=f"cross-venue-exposure-comparability:{digest}")


def _required_contract_asset_semantics_id(
    semantics: ContractAssetSemantics,
) -> ContractAssetSemanticsId:
    if semantics.semantics_id is None:
        raise ValueError("semantics_id is required")
    return semantics.semantics_id


def _readiness_reason(
    semantics: ContractAssetSemantics,
) -> AssetSemanticsReadinessReason:
    checks = (
        (
            any(
                asset.asset_class is AssetClass.UNKNOWN
                for asset in _all_semantic_assets(semantics)
            ),
            AssetSemanticsReadinessReason.ASSET_MISSING,
        ),
        (
            semantics.payoff_kind is ContractPayoffKind.UNKNOWN,
            AssetSemanticsReadinessReason.PAYOFF_KIND_UNKNOWN,
        ),
        (
            semantics.collateral_mode is CollateralMode.UNKNOWN,
            AssetSemanticsReadinessReason.COLLATERAL_MODE_UNKNOWN,
        ),
        (
            semantics.settlement_mode is SettlementMode.UNKNOWN,
            AssetSemanticsReadinessReason.SETTLEMENT_MODE_UNKNOWN,
        ),
        (
            semantics.requires_collateral_valuation
            and semantics.collateral_valuation_policy_id is None,
            AssetSemanticsReadinessReason.VALUATION_REQUIRED,
        ),
        (
            semantics.requires_haircut_rules,
            AssetSemanticsReadinessReason.HAIRCUT_RULES_REQUIRED,
        ),
        (
            semantics.requires_conversion_rules,
            AssetSemanticsReadinessReason.CONVERSION_RULES_REQUIRED,
        ),
        (
            _objective_valuation_is_missing(semantics),
            AssetSemanticsReadinessReason.OBJECTIVE_ASSET_VALUATION_REQUIRED,
        ),
    )
    for failed, reason in checks:
        if failed:
            return reason
    return AssetSemanticsReadinessReason.READY


def _readiness_reason_with_collateral_decisions(
    semantics: ContractAssetSemantics,
    collateral_decisions: Sequence[CollateralValuationReadinessDecision],
) -> AssetSemanticsReadinessReason:
    base_reason = _readiness_reason_for_semantic_shape(semantics)
    if base_reason is not AssetSemanticsReadinessReason.READY:
        return base_reason
    if semantics.requires_collateral_valuation and not _collateral_valuation_ready(
        semantics,
        collateral_decisions,
    ):
        return AssetSemanticsReadinessReason.VALUATION_REQUIRED
    if semantics.requires_haircut_rules and not _collateral_haircuts_ready(
        semantics,
        collateral_decisions,
    ):
        return AssetSemanticsReadinessReason.HAIRCUT_RULES_REQUIRED
    if semantics.requires_conversion_rules:
        return AssetSemanticsReadinessReason.CONVERSION_RULES_REQUIRED
    if _objective_valuation_is_missing(semantics):
        return AssetSemanticsReadinessReason.OBJECTIVE_ASSET_VALUATION_REQUIRED
    return AssetSemanticsReadinessReason.READY


def _readiness_reason_for_semantic_shape(
    semantics: ContractAssetSemantics,
) -> AssetSemanticsReadinessReason:
    checks = (
        (
            any(
                asset.asset_class is AssetClass.UNKNOWN
                for asset in _all_semantic_assets(semantics)
            ),
            AssetSemanticsReadinessReason.ASSET_MISSING,
        ),
        (
            semantics.payoff_kind is ContractPayoffKind.UNKNOWN,
            AssetSemanticsReadinessReason.PAYOFF_KIND_UNKNOWN,
        ),
        (
            semantics.collateral_mode is CollateralMode.UNKNOWN,
            AssetSemanticsReadinessReason.COLLATERAL_MODE_UNKNOWN,
        ),
        (
            semantics.settlement_mode is SettlementMode.UNKNOWN,
            AssetSemanticsReadinessReason.SETTLEMENT_MODE_UNKNOWN,
        ),
    )
    for failed, reason in checks:
        if failed:
            return reason
    return AssetSemanticsReadinessReason.READY


def _collateral_valuation_ready(
    semantics: ContractAssetSemantics,
    collateral_decisions: Sequence[CollateralValuationReadinessDecision],
) -> bool:
    decisions_by_asset = {
        str(decision.collateral_asset): decision for decision in collateral_decisions
    }
    reference_asset = _asset_key(semantics.valuation_reference_asset)
    for collateral_asset in semantics.collateral_assets:
        decision = decisions_by_asset.get(_asset_key(collateral_asset))
        if decision is None:
            return False
        if not decision.ready or decision.reason is not CollateralValuationDecisionReason.READY:
            return False
        if str(decision.reference_asset) != reference_asset:
            return False
    return True


def _collateral_haircuts_ready(
    semantics: ContractAssetSemantics,
    collateral_decisions: Sequence[CollateralValuationReadinessDecision],
) -> bool:
    if not _collateral_valuation_ready(semantics, collateral_decisions):
        return False
    decisions_by_asset = {
        str(decision.collateral_asset): decision for decision in collateral_decisions
    }
    for collateral_asset in semantics.collateral_assets:
        decision = decisions_by_asset.get(_asset_key(collateral_asset))
        if decision is None or decision.haircut_rule is None:
            return False
    return True


def _objective_valuation_is_missing(semantics: ContractAssetSemantics) -> bool:
    return (
        semantics.objective_asset is not None
        and _asset_key(semantics.objective_asset) != _asset_key(semantics.pnl_asset)
        and semantics.requires_objective_valuation
        and semantics.objective_asset_policy_id is None
    )


def _valuation_requirements(
    semantics: ContractAssetSemantics,
) -> tuple[ValuationRequirement, ...]:
    requirements: list[ValuationRequirement] = []
    if semantics.requires_collateral_valuation:
        requirements.append(ValuationRequirement.REQUIRED_FOR_COLLATERAL)
    if semantics.requires_objective_valuation:
        requirements.append(ValuationRequirement.REQUIRED_FOR_OBJECTIVE)
    if semantics.requires_conversion_rules:
        requirements.append(ValuationRequirement.REQUIRED_UNKNOWN)
    if not requirements:
        requirements.append(ValuationRequirement.NOT_REQUIRED)
    return tuple(requirements)


def _all_semantic_assets(
    semantics: ContractAssetSemantics,
) -> tuple[AssetDescriptor, ...]:
    assets = [
        semantics.base_asset,
        semantics.quote_asset,
        semantics.margin_asset,
        semantics.settlement_asset,
        semantics.pnl_asset,
        *semantics.collateral_assets,
        semantics.valuation_reference_asset,
    ]
    for optional_asset in (
        semantics.fee_asset,
        semantics.objective_asset,
        semantics.contract_value_asset,
    ):
        assets.extend([optional_asset] if optional_asset is not None else [])
    return tuple(assets)


def _comparability_reason(
    left: EconomicExposureDescriptor,
    right: EconomicExposureDescriptor,
) -> CrossVenueExposureComparabilityReason:
    checks = (
        (
            _asset_key(left.base_asset) != _asset_key(right.base_asset),
            CrossVenueExposureComparabilityReason.BASE_ASSET_MISMATCH,
        ),
        (
            _asset_key(left.quote_asset) != _asset_key(right.quote_asset),
            CrossVenueExposureComparabilityReason.QUOTE_ASSET_MISMATCH,
        ),
        (
            left.payoff_kind is not right.payoff_kind,
            CrossVenueExposureComparabilityReason.PAYOFF_KIND_MISMATCH,
        ),
        (
            _asset_key(left.settlement_asset) != _asset_key(right.settlement_asset),
            CrossVenueExposureComparabilityReason.SETTLEMENT_ASSET_MISMATCH,
        ),
        (
            _asset_key(left.pnl_asset) != _asset_key(right.pnl_asset),
            CrossVenueExposureComparabilityReason.PNL_ASSET_MISMATCH,
        ),
        (
            left.contract_size != right.contract_size,
            CrossVenueExposureComparabilityReason.CONTRACT_SIZE_MISMATCH,
        ),
        (
            _asset_key(left.valuation_reference_asset)
            != _asset_key(right.valuation_reference_asset),
            CrossVenueExposureComparabilityReason.VALUATION_REFERENCE_MISMATCH,
        ),
    )
    for failed, reason in checks:
        if failed:
            return reason
    return CrossVenueExposureComparabilityReason.COMPARABLE


def _exposure_details(exposure: EconomicExposureDescriptor) -> dict[str, Any]:
    return {
        "venue_id": exposure.venue_id,
        "instrument_id": exposure.instrument_id,
        "base_asset": _asset_key(exposure.base_asset),
        "quote_asset": _asset_key(exposure.quote_asset),
        "payoff_kind": exposure.payoff_kind.value,
        "settlement_asset": _asset_key(exposure.settlement_asset),
        "pnl_asset": _asset_key(exposure.pnl_asset),
        "valuation_reference_asset": _asset_key(exposure.valuation_reference_asset),
        "contract_size": None
        if exposure.contract_size is None
        else format(exposure.contract_size, "f"),
    }


def _asset_key(asset: AssetDescriptor) -> str:
    return asset.canonical_symbol or asset.symbol


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


def _coerce_decimal(value: object) -> Decimal:
    if isinstance(value, bool | float):
        raise ValueError("decimal value must be Decimal, int, or string")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        if value != value.strip():
            raise ValueError("decimal string must be trimmed")
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid decimal string") from exc
    else:
        raise ValueError("decimal value must be Decimal, int, or string")
    if not result.is_finite():
        raise ValueError("decimal value must be finite")
    return result


def _trimmed(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty and trimmed")
    return value
