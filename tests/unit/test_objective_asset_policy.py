from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from futures_bot.domain.collateral_valuation import (
    CollateralValuationDecisionReason,
    CollateralValuationReadinessDecision,
)
from futures_bot.domain.objective_assets import (
    ObjectiveAssetCompatibility,
    ObjectiveAssetDecisionReason,
    ObjectiveAssetPolicy,
    ObjectiveMeasurementMode,
    ObjectivePolicyKind,
)
from futures_bot.objective_assets.policies import evaluate_objective_asset_readiness

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _collateral_decision(*, ready: bool = True) -> CollateralValuationReadinessDecision:
    return CollateralValuationReadinessDecision(
        collateral_asset="ETH",
        reference_asset="USD",
        ready=ready,
        reason=(
            CollateralValuationDecisionReason.READY
            if ready
            else CollateralValuationDecisionReason.NOT_READY
        ),
        checked_at=NOW,
        effective_value_multiplier=Decimal("0.80") if ready else None,
        details={},
    )


def _ready_collateral_decision(
    *,
    collateral_asset: str,
    reference_asset: str,
) -> CollateralValuationReadinessDecision:
    return CollateralValuationReadinessDecision(
        collateral_asset=collateral_asset,
        reference_asset=reference_asset,
        ready=True,
        reason=CollateralValuationDecisionReason.READY,
        checked_at=NOW,
        effective_value_multiplier=Decimal("0.80"),
        details={},
    )


def test_unknown_policy_kind_is_not_ready() -> None:
    policy = ObjectiveAssetPolicy(
        policy_kind=ObjectivePolicyKind.UNKNOWN,
        measurement_mode=ObjectiveMeasurementMode.NATIVE_ASSET_UNITS,
        valuation_required=False,
        conversion_required=False,
        collateral_adjustment_required=False,
        allow_direct_asset_match=True,
        allow_reference_asset_measurement=False,
        allow_collateral_adjusted_measurement=False,
        metadata={},
    )

    decision = evaluate_objective_asset_readiness(
        policy=policy,
        checked_at=NOW,
        pnl_asset="USDT",
    )

    assert not decision.ready
    assert decision.reason is ObjectiveAssetDecisionReason.OBJECTIVE_POLICY_UNKNOWN


def test_unknown_measurement_mode_is_not_ready() -> None:
    policy = ObjectiveAssetPolicy(
        policy_kind=ObjectivePolicyKind.MATCH_SETTLEMENT_ASSET,
        measurement_mode=ObjectiveMeasurementMode.UNKNOWN,
        valuation_required=False,
        conversion_required=False,
        collateral_adjustment_required=False,
        allow_direct_asset_match=True,
        allow_reference_asset_measurement=False,
        allow_collateral_adjusted_measurement=False,
        metadata={},
    )

    decision = evaluate_objective_asset_readiness(
        policy=policy,
        checked_at=NOW,
        pnl_asset="USDT",
        settlement_asset="USDT",
    )

    assert not decision.ready
    assert decision.reason is ObjectiveAssetDecisionReason.OBJECTIVE_MEASUREMENT_UNKNOWN


def test_accumulate_usdt_with_usdt_pnl_ready_direct_match() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.accumulate("USDT"),
        checked_at=NOW,
        pnl_asset="USDT",
    )

    assert decision.ready
    assert decision.compatibility is ObjectiveAssetCompatibility.DIRECT_MATCH


def test_accumulate_btc_with_usdt_pnl_rejected_without_valuation_or_conversion() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.accumulate("BTC"),
        checked_at=NOW,
        pnl_asset="USDT",
    )

    assert not decision.ready
    assert decision.reason is ObjectiveAssetDecisionReason.VALUATION_REQUIRED


def test_accumulate_btc_with_unrelated_collateral_valuation_remains_not_ready() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.accumulate("BTC"),
        checked_at=NOW,
        pnl_asset="USDT",
        collateral_asset="ETH",
        collateral_valuation_decision=_ready_collateral_decision(
            collateral_asset="ETH",
            reference_asset="USD",
        ),
    )

    assert not decision.ready
    assert decision.reason is ObjectiveAssetDecisionReason.VALUATION_REQUIRED


def test_accumulate_eth_with_eth_settlement_ready_direct_match() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.accumulate("ETH"),
        checked_at=NOW,
        pnl_asset="USDT",
        settlement_asset="ETH",
    )

    assert decision.ready
    assert decision.compatibility is ObjectiveAssetCompatibility.DIRECT_MATCH


def test_maximize_usd_reference_with_usd_pnl_ready_if_direct_measurement_allowed() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.maximize_reference_value("USD"),
        checked_at=NOW,
        pnl_asset="USD",
    )

    assert decision.ready
    assert decision.compatibility is ObjectiveAssetCompatibility.DIRECT_MATCH


def test_maximize_usd_reference_with_eth_pnl_requires_valuation() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.maximize_reference_value("USD"),
        checked_at=NOW,
        pnl_asset="ETH",
    )

    assert not decision.ready
    assert decision.reason is ObjectiveAssetDecisionReason.VALUATION_REQUIRED


def test_not_ready_collateral_valuation_decision_rejects_objective_readiness() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.maximize_reference_value("USD"),
        checked_at=NOW,
        pnl_asset="ETH",
        collateral_valuation_decision=_collateral_decision(ready=False),
    )

    assert not decision.ready
    assert decision.reason is ObjectiveAssetDecisionReason.COLLATERAL_VALUATION_NOT_READY


def test_maximize_usd_reference_rejects_unrelated_collateral_valuation() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.maximize_reference_value("USD"),
        checked_at=NOW,
        pnl_asset="ETH",
        collateral_asset="ETH",
        collateral_valuation_decision=_ready_collateral_decision(
            collateral_asset="BTC",
            reference_asset="USD",
        ),
    )

    assert not decision.ready
    assert decision.reason is ObjectiveAssetDecisionReason.VALUATION_REQUIRED


def test_maximize_usd_reference_requires_matching_collateral_and_reference() -> None:
    wrong_reference = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.maximize_reference_value("USD"),
        checked_at=NOW,
        pnl_asset="ETH",
        collateral_asset="ETH",
        collateral_valuation_decision=_ready_collateral_decision(
            collateral_asset="ETH",
            reference_asset="USDT",
        ),
    )
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.maximize_reference_value("USD"),
        checked_at=NOW,
        pnl_asset="ETH",
        collateral_asset="ETH",
        collateral_valuation_decision=_ready_collateral_decision(
            collateral_asset="ETH",
            reference_asset="USD",
        ),
    )

    assert not wrong_reference.ready
    assert wrong_reference.reason is ObjectiveAssetDecisionReason.VALUATION_REQUIRED
    assert decision.ready
    assert decision.compatibility is ObjectiveAssetCompatibility.VALUATION_REQUIRED
    assert decision.collateral_valuation_decision_id == _ready_collateral_decision(
        collateral_asset="ETH",
        reference_asset="USD",
    ).decision_id


def test_preserve_collateral_asset_rejects_different_pnl_without_conversion() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.preserve_collateral_asset("ETH"),
        checked_at=NOW,
        pnl_asset="USDT",
        settlement_asset="USDT",
        collateral_asset="ETH",
    )

    assert decision.ready
    assert decision.compatibility is ObjectiveAssetCompatibility.DIRECT_MATCH

    mismatch = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.preserve_collateral_asset("ETH"),
        checked_at=NOW,
        pnl_asset="USDT",
        settlement_asset="USDT",
        collateral_asset="BTC",
    )

    assert not mismatch.ready
    assert mismatch.reason is ObjectiveAssetDecisionReason.CONVERSION_REQUIRED


def test_match_settlement_asset_rejects_pnl_settlement_mismatch() -> None:
    policy = ObjectiveAssetPolicy(
        policy_kind=ObjectivePolicyKind.MATCH_SETTLEMENT_ASSET,
        measurement_mode=ObjectiveMeasurementMode.NATIVE_ASSET_UNITS,
        valuation_required=False,
        conversion_required=False,
        collateral_adjustment_required=False,
        allow_direct_asset_match=True,
        allow_reference_asset_measurement=False,
        allow_collateral_adjusted_measurement=False,
        metadata={},
    )

    decision = evaluate_objective_asset_readiness(
        policy=policy,
        checked_at=NOW,
        pnl_asset="USDT",
        settlement_asset="ETH",
    )

    assert not decision.ready
    assert decision.reason is ObjectiveAssetDecisionReason.SETTLEMENT_ASSET_MISMATCH


def test_match_settlement_mismatch_not_approved_by_collateral_valuation() -> None:
    policy = ObjectiveAssetPolicy(
        policy_kind=ObjectivePolicyKind.MATCH_SETTLEMENT_ASSET,
        measurement_mode=ObjectiveMeasurementMode.EXPLICIT_CONVERSION_REQUIRED,
        valuation_required=False,
        conversion_required=True,
        collateral_adjustment_required=False,
        allow_direct_asset_match=True,
        allow_reference_asset_measurement=False,
        allow_collateral_adjusted_measurement=False,
        metadata={},
    )

    decision = evaluate_objective_asset_readiness(
        policy=policy,
        checked_at=NOW,
        pnl_asset="USDT",
        settlement_asset="ETH",
        collateral_asset="ETH",
        collateral_valuation_decision=_ready_collateral_decision(
            collateral_asset="ETH",
            reference_asset="USD",
        ),
    )

    assert not decision.ready
    assert decision.reason is ObjectiveAssetDecisionReason.CONVERSION_REQUIRED


def test_no_usdt_usd_implicit_equivalence() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.maximize_reference_value("USD"),
        checked_at=NOW,
        pnl_asset="USDT",
    )

    assert not decision.ready
    assert decision.reason is ObjectiveAssetDecisionReason.VALUATION_REQUIRED


def test_no_eth_btc_implicit_conversion() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.accumulate("BTC"),
        checked_at=NOW,
        pnl_asset="ETH",
    )

    assert not decision.ready
    assert decision.reason is ObjectiveAssetDecisionReason.VALUATION_REQUIRED
