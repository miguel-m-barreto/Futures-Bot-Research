from __future__ import annotations

from datetime import datetime
from typing import Any

from futures_bot.domain.asset_conversion import AssetConversionReadinessDecision
from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.collateral_valuation import CollateralValuationReadinessDecision
from futures_bot.domain.ids import ObjectiveAssetMeasurementId
from futures_bot.domain.objective_assets import (
    ObjectiveAssetCompatibility,
    ObjectiveAssetDecisionReason,
    ObjectiveAssetPolicy,
    ObjectiveAssetReadinessDecision,
    ObjectiveMeasurementMode,
    ObjectivePolicyKind,
)
from futures_bot.domain.time import ensure_aware_utc


def evaluate_objective_asset_readiness(  # noqa: PLR0911, PLR0913
    *,
    policy: ObjectiveAssetPolicy,
    checked_at: datetime,
    pnl_asset: AssetSymbol | str | None = None,
    settlement_asset: AssetSymbol | str | None = None,
    collateral_asset: AssetSymbol | str | None = None,
    valuation_decision: Any = None,
    conversion_decision: AssetConversionReadinessDecision | None = None,
    collateral_valuation_decision: CollateralValuationReadinessDecision | None = None,
) -> ObjectiveAssetReadinessDecision:
    checked_at = ensure_aware_utc(checked_at)
    pnl = _asset_or_none(pnl_asset)
    settlement = _asset_or_none(settlement_asset)
    collateral = _asset_or_none(collateral_asset)

    if _policy_disabled(policy):
        return _decision(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl,
            settlement_asset=settlement,
            collateral_asset=collateral,
            reason=ObjectiveAssetDecisionReason.POLICY_DISABLED,
            compatibility=ObjectiveAssetCompatibility.UNKNOWN,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details={"policy_disabled": True},
        )

    if policy.policy_kind is ObjectivePolicyKind.UNKNOWN:
        return _decision(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl,
            settlement_asset=settlement,
            collateral_asset=collateral,
            reason=ObjectiveAssetDecisionReason.OBJECTIVE_POLICY_UNKNOWN,
            compatibility=ObjectiveAssetCompatibility.UNKNOWN,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details={"policy_kind": policy.policy_kind.value},
        )

    if policy.measurement_mode is ObjectiveMeasurementMode.UNKNOWN:
        return _decision(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl,
            settlement_asset=settlement,
            collateral_asset=collateral,
            reason=ObjectiveAssetDecisionReason.OBJECTIVE_MEASUREMENT_UNKNOWN,
            compatibility=ObjectiveAssetCompatibility.UNKNOWN,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details={"measurement_mode": policy.measurement_mode.value},
        )

    if policy.collateral_adjustment_required and not _collateral_ready(
        collateral_valuation_decision,
    ):
        return _decision(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl,
            settlement_asset=settlement,
            collateral_asset=collateral,
            reason=ObjectiveAssetDecisionReason.COLLATERAL_VALUATION_NOT_READY,
            compatibility=ObjectiveAssetCompatibility.VALUATION_REQUIRED,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details={"collateral_adjustment_required": True},
        )

    if policy.policy_kind is ObjectivePolicyKind.ACCUMULATE_ASSET:
        return _evaluate_accumulate(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl,
            settlement_asset=settlement,
            collateral_asset=collateral,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
        )
    if policy.policy_kind is ObjectivePolicyKind.MAXIMIZE_REFERENCE_VALUE:
        return _evaluate_reference_value(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl,
            settlement_asset=settlement,
            collateral_asset=collateral,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
        )
    if policy.policy_kind is ObjectivePolicyKind.PRESERVE_COLLATERAL_ASSET:
        return _evaluate_preserve_collateral(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl,
            settlement_asset=settlement,
            collateral_asset=collateral,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
        )
    if policy.policy_kind is ObjectivePolicyKind.MATCH_SETTLEMENT_ASSET:
        return _evaluate_match_settlement(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl,
            settlement_asset=settlement,
            collateral_asset=collateral,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
        )
    return _decision(
        policy=policy,
        checked_at=checked_at,
        pnl_asset=pnl,
        settlement_asset=settlement,
        collateral_asset=collateral,
        reason=ObjectiveAssetDecisionReason.NOT_READY,
        compatibility=ObjectiveAssetCompatibility.UNKNOWN,
        valuation_decision=valuation_decision,
        conversion_decision=conversion_decision,
        collateral_valuation_decision=collateral_valuation_decision,
        details={"policy_kind": policy.policy_kind.value},
    )


def _evaluate_accumulate(  # noqa: PLR0913
    *,
    policy: ObjectiveAssetPolicy,
    checked_at: datetime,
    pnl_asset: AssetSymbol | None,
    settlement_asset: AssetSymbol | None,
    collateral_asset: AssetSymbol | None,
    valuation_decision: Any,
    conversion_decision: AssetConversionReadinessDecision | None,
    collateral_valuation_decision: CollateralValuationReadinessDecision | None,
) -> ObjectiveAssetReadinessDecision:
    objective = policy.objective_asset
    if objective is None:
        return _missing_objective(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl_asset,
            settlement_asset=settlement_asset,
            collateral_asset=collateral_asset,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
        )
    if policy.allow_direct_asset_match and objective in (pnl_asset, settlement_asset):
        return _ready(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl_asset,
            settlement_asset=settlement_asset,
            collateral_asset=collateral_asset,
            compatibility=ObjectiveAssetCompatibility.DIRECT_MATCH,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details={"objective_asset": str(objective)},
        )
    return _explicit_evidence_or_required(
        policy=policy,
        checked_at=checked_at,
        pnl_asset=pnl_asset,
        settlement_asset=settlement_asset,
        collateral_asset=collateral_asset,
        valuation_decision=valuation_decision,
        conversion_decision=conversion_decision,
        collateral_valuation_decision=collateral_valuation_decision,
        conversion_from_assets=_asset_tuple(pnl_asset, settlement_asset),
        conversion_to_asset=objective,
        missing_reason=(
            ObjectiveAssetDecisionReason.CONVERSION_REQUIRED
            if policy.conversion_required
            else ObjectiveAssetDecisionReason.VALUATION_REQUIRED
        ),
        not_ready_reason=(
            ObjectiveAssetDecisionReason.CONVERSION_NOT_AVAILABLE
            if policy.conversion_required
            else ObjectiveAssetDecisionReason.VALUATION_NOT_READY
        ),
        compatibility=(
            ObjectiveAssetCompatibility.CONVERSION_REQUIRED
            if policy.conversion_required
            else ObjectiveAssetCompatibility.VALUATION_REQUIRED
        ),
        details={
            "objective_asset": str(objective),
            "pnl_asset": None if pnl_asset is None else str(pnl_asset),
            "settlement_asset": None if settlement_asset is None else str(settlement_asset),
        },
    )


def _evaluate_reference_value(  # noqa: PLR0913
    *,
    policy: ObjectiveAssetPolicy,
    checked_at: datetime,
    pnl_asset: AssetSymbol | None,
    settlement_asset: AssetSymbol | None,
    collateral_asset: AssetSymbol | None,
    valuation_decision: Any,
    conversion_decision: AssetConversionReadinessDecision | None,
    collateral_valuation_decision: CollateralValuationReadinessDecision | None,
) -> ObjectiveAssetReadinessDecision:
    reference = policy.reference_asset
    if reference is None:
        return _decision(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl_asset,
            settlement_asset=settlement_asset,
            collateral_asset=collateral_asset,
            reason=ObjectiveAssetDecisionReason.REFERENCE_ASSET_MISMATCH,
            compatibility=ObjectiveAssetCompatibility.UNKNOWN,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details={"missing": "reference_asset"},
        )
    if policy.allow_reference_asset_measurement and reference in (
        pnl_asset,
        settlement_asset,
    ):
        return _ready(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl_asset,
            settlement_asset=settlement_asset,
            collateral_asset=collateral_asset,
            compatibility=ObjectiveAssetCompatibility.DIRECT_MATCH,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details={"reference_asset": str(reference)},
        )
    return _explicit_evidence_or_required(
        policy=policy,
        checked_at=checked_at,
        pnl_asset=pnl_asset,
        settlement_asset=settlement_asset,
        collateral_asset=collateral_asset,
        valuation_decision=valuation_decision,
        conversion_decision=conversion_decision,
        collateral_valuation_decision=collateral_valuation_decision,
        conversion_from_assets=_asset_tuple(pnl_asset, settlement_asset, collateral_asset),
        conversion_to_asset=reference,
        missing_reason=ObjectiveAssetDecisionReason.VALUATION_REQUIRED,
        not_ready_reason=ObjectiveAssetDecisionReason.VALUATION_NOT_READY,
        compatibility=ObjectiveAssetCompatibility.VALUATION_REQUIRED,
        details={
            "reference_asset": str(reference),
            "pnl_asset": None if pnl_asset is None else str(pnl_asset),
            "settlement_asset": None if settlement_asset is None else str(settlement_asset),
        },
    )


def _evaluate_preserve_collateral(  # noqa: PLR0913
    *,
    policy: ObjectiveAssetPolicy,
    checked_at: datetime,
    pnl_asset: AssetSymbol | None,
    settlement_asset: AssetSymbol | None,
    collateral_asset: AssetSymbol | None,
    valuation_decision: Any,
    conversion_decision: AssetConversionReadinessDecision | None,
    collateral_valuation_decision: CollateralValuationReadinessDecision | None,
) -> ObjectiveAssetReadinessDecision:
    objective = policy.objective_asset or collateral_asset
    if objective is None:
        return _missing_objective(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl_asset,
            settlement_asset=settlement_asset,
            collateral_asset=collateral_asset,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
        )
    if policy.allow_direct_asset_match and objective in (
        pnl_asset,
        settlement_asset,
        collateral_asset,
    ):
        return _ready(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl_asset,
            settlement_asset=settlement_asset,
            collateral_asset=collateral_asset,
            compatibility=ObjectiveAssetCompatibility.DIRECT_MATCH,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details={"objective_asset": str(objective)},
        )
    return _explicit_evidence_or_required(
        policy=policy,
        checked_at=checked_at,
        pnl_asset=pnl_asset,
        settlement_asset=settlement_asset,
        collateral_asset=collateral_asset,
        valuation_decision=valuation_decision,
        conversion_decision=conversion_decision,
        collateral_valuation_decision=collateral_valuation_decision,
        conversion_from_assets=_asset_tuple(pnl_asset, settlement_asset),
        conversion_to_asset=objective,
        missing_reason=ObjectiveAssetDecisionReason.CONVERSION_REQUIRED,
        not_ready_reason=ObjectiveAssetDecisionReason.CONVERSION_NOT_AVAILABLE,
        compatibility=ObjectiveAssetCompatibility.CONVERSION_REQUIRED,
        details={
            "objective_asset": str(objective),
            "pnl_asset": None if pnl_asset is None else str(pnl_asset),
        },
    )


def _evaluate_match_settlement(  # noqa: PLR0913
    *,
    policy: ObjectiveAssetPolicy,
    checked_at: datetime,
    pnl_asset: AssetSymbol | None,
    settlement_asset: AssetSymbol | None,
    collateral_asset: AssetSymbol | None,
    valuation_decision: Any,
    conversion_decision: AssetConversionReadinessDecision | None,
    collateral_valuation_decision: CollateralValuationReadinessDecision | None,
) -> ObjectiveAssetReadinessDecision:
    if settlement_asset is None:
        return _decision(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl_asset,
            settlement_asset=settlement_asset,
            collateral_asset=collateral_asset,
            reason=ObjectiveAssetDecisionReason.SETTLEMENT_ASSET_MISMATCH,
            compatibility=ObjectiveAssetCompatibility.UNKNOWN,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details={"missing": "settlement_asset"},
        )
    if policy.allow_direct_asset_match and pnl_asset == settlement_asset:
        return _ready(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl_asset,
            settlement_asset=settlement_asset,
            collateral_asset=collateral_asset,
            compatibility=ObjectiveAssetCompatibility.DIRECT_MATCH,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details={"settlement_asset": str(settlement_asset)},
        )
    if not policy.conversion_required:
        return _decision(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl_asset,
            settlement_asset=settlement_asset,
            collateral_asset=collateral_asset,
            reason=ObjectiveAssetDecisionReason.SETTLEMENT_ASSET_MISMATCH,
            compatibility=ObjectiveAssetCompatibility.NOT_COMPATIBLE,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details={
                "pnl_asset": None if pnl_asset is None else str(pnl_asset),
                "settlement_asset": str(settlement_asset),
            },
        )
    return _explicit_evidence_or_required(
        policy=policy,
        checked_at=checked_at,
        pnl_asset=pnl_asset,
        settlement_asset=settlement_asset,
        collateral_asset=collateral_asset,
        valuation_decision=valuation_decision,
        conversion_decision=conversion_decision,
        collateral_valuation_decision=collateral_valuation_decision,
        conversion_from_assets=_asset_tuple(pnl_asset),
        conversion_to_asset=settlement_asset,
        missing_reason=ObjectiveAssetDecisionReason.CONVERSION_REQUIRED,
        not_ready_reason=ObjectiveAssetDecisionReason.CONVERSION_NOT_AVAILABLE,
        compatibility=ObjectiveAssetCompatibility.CONVERSION_REQUIRED,
        details={
            "pnl_asset": None if pnl_asset is None else str(pnl_asset),
            "settlement_asset": str(settlement_asset),
        },
    )


def _explicit_evidence_or_required(  # noqa: PLR0913
    *,
    policy: ObjectiveAssetPolicy,
    checked_at: datetime,
    pnl_asset: AssetSymbol | None,
    settlement_asset: AssetSymbol | None,
    collateral_asset: AssetSymbol | None,
    valuation_decision: Any,
    conversion_decision: AssetConversionReadinessDecision | None,
    collateral_valuation_decision: CollateralValuationReadinessDecision | None,
    conversion_from_assets: tuple[AssetSymbol, ...],
    conversion_to_asset: AssetSymbol | None,
    missing_reason: ObjectiveAssetDecisionReason,
    not_ready_reason: ObjectiveAssetDecisionReason,
    compatibility: ObjectiveAssetCompatibility,
    details: dict[str, Any],
) -> ObjectiveAssetReadinessDecision:
    typed_conversion_decision = _typed_conversion_decision(
        conversion_decision,
        valuation_decision,
    )
    if typed_conversion_decision is not None:
        if _conversion_decision_supports_path(
            typed_conversion_decision,
            from_assets=conversion_from_assets,
            to_asset=conversion_to_asset,
        ):
            return _ready(
                policy=policy,
                checked_at=checked_at,
                pnl_asset=pnl_asset,
                settlement_asset=settlement_asset,
                collateral_asset=collateral_asset,
                compatibility=compatibility,
                valuation_decision=valuation_decision,
                conversion_decision=typed_conversion_decision,
                collateral_valuation_decision=collateral_valuation_decision,
                details=details,
            )
        return _decision(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl_asset,
            settlement_asset=settlement_asset,
            collateral_asset=collateral_asset,
            reason=not_ready_reason,
            compatibility=compatibility,
            valuation_decision=valuation_decision,
            conversion_decision=typed_conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details=details,
        )
    if collateral_valuation_decision is not None:
        if _collateral_valuation_supports_policy(
            policy=policy,
            collateral_asset=collateral_asset,
            collateral_valuation_decision=collateral_valuation_decision,
        ):
            return _ready(
                policy=policy,
                checked_at=checked_at,
                pnl_asset=pnl_asset,
                settlement_asset=settlement_asset,
                collateral_asset=collateral_asset,
                compatibility=compatibility,
                valuation_decision=valuation_decision,
                conversion_decision=conversion_decision,
                collateral_valuation_decision=collateral_valuation_decision,
                details=details,
            )
        reason = (
            ObjectiveAssetDecisionReason.COLLATERAL_VALUATION_NOT_READY
            if not _collateral_ready(collateral_valuation_decision)
            else missing_reason
        )
        return _decision(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl_asset,
            settlement_asset=settlement_asset,
            collateral_asset=collateral_asset,
            reason=reason,
            compatibility=compatibility,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details=details,
        )
    if valuation_decision is not None:
        return _decision(
            policy=policy,
            checked_at=checked_at,
            pnl_asset=pnl_asset,
            settlement_asset=settlement_asset,
            collateral_asset=collateral_asset,
            reason=not_ready_reason,
            compatibility=compatibility,
            valuation_decision=valuation_decision,
            conversion_decision=conversion_decision,
            collateral_valuation_decision=collateral_valuation_decision,
            details=details,
        )
    return _decision(
        policy=policy,
        checked_at=checked_at,
        pnl_asset=pnl_asset,
        settlement_asset=settlement_asset,
        collateral_asset=collateral_asset,
        reason=missing_reason,
        compatibility=compatibility,
        valuation_decision=valuation_decision,
        conversion_decision=conversion_decision,
        collateral_valuation_decision=collateral_valuation_decision,
        details=details,
    )


def _missing_objective(  # noqa: PLR0913
    *,
    policy: ObjectiveAssetPolicy,
    checked_at: datetime,
    pnl_asset: AssetSymbol | None,
    settlement_asset: AssetSymbol | None,
    collateral_asset: AssetSymbol | None,
    valuation_decision: Any,
    conversion_decision: AssetConversionReadinessDecision | None,
    collateral_valuation_decision: CollateralValuationReadinessDecision | None,
) -> ObjectiveAssetReadinessDecision:
    return _decision(
        policy=policy,
        checked_at=checked_at,
        pnl_asset=pnl_asset,
        settlement_asset=settlement_asset,
        collateral_asset=collateral_asset,
        reason=ObjectiveAssetDecisionReason.OBJECTIVE_ASSET_MISSING,
        compatibility=ObjectiveAssetCompatibility.UNKNOWN,
        valuation_decision=valuation_decision,
        conversion_decision=conversion_decision,
        collateral_valuation_decision=collateral_valuation_decision,
        details={"missing": "objective_asset"},
    )


def _ready(  # noqa: PLR0913
    *,
    policy: ObjectiveAssetPolicy,
    checked_at: datetime,
    pnl_asset: AssetSymbol | None,
    settlement_asset: AssetSymbol | None,
    collateral_asset: AssetSymbol | None,
    compatibility: ObjectiveAssetCompatibility,
    valuation_decision: Any,
    conversion_decision: AssetConversionReadinessDecision | None,
    collateral_valuation_decision: CollateralValuationReadinessDecision | None,
    details: dict[str, Any],
) -> ObjectiveAssetReadinessDecision:
    return _decision(
        policy=policy,
        checked_at=checked_at,
        pnl_asset=pnl_asset,
        settlement_asset=settlement_asset,
        collateral_asset=collateral_asset,
        ready=True,
        reason=ObjectiveAssetDecisionReason.READY,
        compatibility=compatibility,
        valuation_decision=valuation_decision,
        conversion_decision=conversion_decision,
        collateral_valuation_decision=collateral_valuation_decision,
        details=details,
    )


def _decision(  # noqa: PLR0913
    *,
    policy: ObjectiveAssetPolicy,
    checked_at: datetime,
    pnl_asset: AssetSymbol | None,
    settlement_asset: AssetSymbol | None,
    collateral_asset: AssetSymbol | None,
    reason: ObjectiveAssetDecisionReason,
    compatibility: ObjectiveAssetCompatibility,
    valuation_decision: Any,
    conversion_decision: AssetConversionReadinessDecision | None,
    collateral_valuation_decision: CollateralValuationReadinessDecision | None,
    details: Any,
    ready: bool = False,
) -> ObjectiveAssetReadinessDecision:
    if policy.policy_id is None:
        raise ValueError("objective asset policy must have policy_id")
    return ObjectiveAssetReadinessDecision(
        policy_id=policy.policy_id,
        objective_asset=policy.objective_asset,
        reference_asset=policy.reference_asset,
        pnl_asset=pnl_asset,
        settlement_asset=settlement_asset,
        collateral_asset=collateral_asset,
        ready=ready,
        reason=reason,
        compatibility=compatibility,
        valuation_decision_id=_valuation_decision_id(valuation_decision),
        conversion_decision_id=(
            None if conversion_decision is None else conversion_decision.decision_id
        ),
        collateral_valuation_decision_id=(
            None
            if collateral_valuation_decision is None
            else collateral_valuation_decision.decision_id
        ),
        checked_at=checked_at,
        details=details,
    )


def _policy_disabled(policy: ObjectiveAssetPolicy) -> bool:
    disabled = policy.metadata.get("policy_disabled")
    return disabled is True


def _asset_or_none(value: AssetSymbol | str | None) -> AssetSymbol | None:
    if value is None:
        return None
    return value if isinstance(value, AssetSymbol) else AssetSymbol(value)


def _collateral_ready(
    collateral_valuation_decision: CollateralValuationReadinessDecision | None,
) -> bool:
    return (
        collateral_valuation_decision is not None
        and collateral_valuation_decision.ready
    )


def _typed_conversion_decision(
    conversion_decision: AssetConversionReadinessDecision | None,
    valuation_decision: Any,
) -> AssetConversionReadinessDecision | None:
    if conversion_decision is not None:
        return conversion_decision
    if isinstance(valuation_decision, AssetConversionReadinessDecision):
        return valuation_decision
    return None


def _conversion_decision_supports_path(
    conversion_decision: AssetConversionReadinessDecision,
    *,
    from_assets: tuple[AssetSymbol, ...],
    to_asset: AssetSymbol | None,
) -> bool:
    if not conversion_decision.ready:
        return False
    if conversion_decision.from_asset is None or conversion_decision.to_asset is None:
        return False
    if to_asset is None or str(conversion_decision.to_asset) != str(to_asset):
        return False
    return any(
        str(conversion_decision.from_asset) == str(source_asset)
        for source_asset in from_assets
    )


def _asset_tuple(*assets: AssetSymbol | None) -> tuple[AssetSymbol, ...]:
    return tuple(asset for asset in assets if asset is not None)


def _collateral_valuation_supports_policy(
    *,
    policy: ObjectiveAssetPolicy,
    collateral_asset: AssetSymbol | None,
    collateral_valuation_decision: CollateralValuationReadinessDecision,
) -> bool:
    collateral_matches = (
        collateral_asset is not None
        and str(collateral_valuation_decision.collateral_asset) == str(collateral_asset)
    )
    reference_matches = (
        policy.reference_asset is not None
        and str(collateral_valuation_decision.reference_asset)
        == str(policy.reference_asset)
    )
    policy_allows_reference_measurement = (
        policy.policy_kind is ObjectivePolicyKind.MAXIMIZE_REFERENCE_VALUE
        and (
            policy.allow_reference_asset_measurement
            or policy.allow_collateral_adjusted_measurement
        )
    )
    return (
        _collateral_ready(collateral_valuation_decision)
        and collateral_matches
        and reference_matches
        and policy_allows_reference_measurement
    )


def _valuation_decision_id(
    valuation_decision: Any,
) -> ObjectiveAssetMeasurementId | None:
    if valuation_decision is None:
        return None
    for attr in ("measurement_id", "decision_id", "valuation_decision_id"):
        value = getattr(valuation_decision, attr, None)
        if value is not None:
            return ObjectiveAssetMeasurementId(value=str(value))
    if isinstance(valuation_decision, ObjectiveAssetMeasurementId):
        return valuation_decision
    return None
