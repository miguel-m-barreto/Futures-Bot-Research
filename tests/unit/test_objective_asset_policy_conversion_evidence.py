from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from futures_bot.asset_conversion.policies import evaluate_asset_conversion_readiness
from futures_bot.domain.asset_conversion import (
    AssetConversionEvidenceKind,
    AssetConversionPolicy,
    AssetConversionRateSnapshot,
    AssetConversionReadinessDecision,
    AssetConversionSourceHealth,
    AssetConversionSourceKind,
    AssetConversionSourceTrust,
)
from futures_bot.domain.assets import AssetSymbol
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


def _conversion_policy(**overrides: object) -> AssetConversionPolicy:
    values = {
        "max_rate_age": 60_000,
        "require_source_record": True,
        "allowed_source_trust": (AssetConversionSourceTrust.OFFICIAL,),
        "allowed_source_health": (AssetConversionSourceHealth.HEALTHY,),
        "allow_same_asset_direct_match": False,
        "allow_inverse_rate": False,
        "allow_triangulation": False,
        "require_bid_ask": False,
        "metadata": {},
    }
    values.update(overrides)
    return AssetConversionPolicy(**values)


def _snapshot(
    from_asset: str,
    to_asset: str,
    *,
    evidence_kind: AssetConversionEvidenceKind = (
        AssetConversionEvidenceKind.DIRECT_PAIR_RATE
    ),
) -> AssetConversionRateSnapshot:
    return AssetConversionRateSnapshot(
        from_asset=AssetSymbol(from_asset),
        to_asset=AssetSymbol(to_asset),
        rate=Decimal("2"),
        observed_at=NOW - timedelta(seconds=1),
        captured_at=NOW - timedelta(seconds=1),
        source_kind=AssetConversionSourceKind.ORACLE_PRICE,
        source_trust=AssetConversionSourceTrust.OFFICIAL,
        source_health=AssetConversionSourceHealth.HEALTHY,
        evidence_kind=evidence_kind,
        source_record_id=f"{from_asset}-{to_asset}",
        metadata={},
    )


def _conversion_decision(
    from_asset: str,
    to_asset: str,
    *,
    evidence_kind: AssetConversionEvidenceKind = (
        AssetConversionEvidenceKind.DIRECT_PAIR_RATE
    ),
) -> AssetConversionReadinessDecision:
    return evaluate_asset_conversion_readiness(
        policy=_conversion_policy(),
        checked_at=NOW,
        from_asset=from_asset,
        to_asset=to_asset,
        rate_snapshot=_snapshot(from_asset, to_asset, evidence_kind=evidence_kind),
    )


def _collateral_decision() -> CollateralValuationReadinessDecision:
    return CollateralValuationReadinessDecision(
        collateral_asset=AssetSymbol("ETH"),
        reference_asset=AssetSymbol("USD"),
        ready=True,
        reason=CollateralValuationDecisionReason.READY,
        checked_at=NOW,
        effective_value_multiplier=Decimal("0.80"),
        details={},
    )


def test_accumulate_btc_with_usdt_pnl_requires_matching_conversion() -> None:
    ready = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.accumulate("BTC"),
        checked_at=NOW,
        pnl_asset="USDT",
        conversion_decision=_conversion_decision("USDT", "BTC"),
    )
    unrelated = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.accumulate("BTC"),
        checked_at=NOW,
        pnl_asset="USDT",
        conversion_decision=_conversion_decision("ETH", "BTC"),
    )

    assert ready.ready
    assert ready.compatibility is ObjectiveAssetCompatibility.VALUATION_REQUIRED
    assert not unrelated.ready
    assert unrelated.reason is ObjectiveAssetDecisionReason.VALUATION_NOT_READY


def test_unknown_evidence_kind_does_not_satisfy_objective_conversion() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.accumulate("BTC"),
        checked_at=NOW,
        pnl_asset="USDT",
        conversion_decision=_conversion_decision(
            "USDT",
            "BTC",
            evidence_kind=AssetConversionEvidenceKind.UNKNOWN,
        ),
    )

    assert not decision.ready
    assert decision.reason is ObjectiveAssetDecisionReason.VALUATION_NOT_READY


def test_match_settlement_requires_pnl_to_settlement_conversion() -> None:
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

    ready = evaluate_objective_asset_readiness(
        policy=policy,
        checked_at=NOW,
        pnl_asset="BTC",
        settlement_asset="USDT",
        conversion_decision=_conversion_decision("BTC", "USDT"),
    )
    wrong_direction = evaluate_objective_asset_readiness(
        policy=policy,
        checked_at=NOW,
        pnl_asset="BTC",
        settlement_asset="USDT",
        conversion_decision=_conversion_decision("USDT", "BTC"),
    )

    assert ready.ready
    assert not wrong_direction.ready
    assert wrong_direction.reason is ObjectiveAssetDecisionReason.CONVERSION_NOT_AVAILABLE


def test_maximize_usd_reference_requires_measured_asset_to_reference_conversion() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.maximize_reference_value("USD"),
        checked_at=NOW,
        pnl_asset="ETH",
        conversion_decision=_conversion_decision("ETH", "USD"),
    )

    assert decision.ready
    assert decision.conversion_decision_id == _conversion_decision("ETH", "USD").decision_id


def test_no_usdt_usd_direct_readiness_without_explicit_conversion() -> None:
    missing = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.maximize_reference_value("USD"),
        checked_at=NOW,
        pnl_asset="USDT",
    )
    explicit = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.maximize_reference_value("USD"),
        checked_at=NOW,
        pnl_asset="USDT",
        conversion_decision=_conversion_decision("USDT", "USD"),
    )

    assert not missing.ready
    assert explicit.ready


def test_collateral_valuation_alone_does_not_satisfy_accumulate_conversion() -> None:
    decision = evaluate_objective_asset_readiness(
        policy=ObjectiveAssetPolicy.accumulate("BTC"),
        checked_at=NOW,
        pnl_asset="USDT",
        collateral_asset="ETH",
        collateral_valuation_decision=_collateral_decision(),
    )

    assert not decision.ready
    assert decision.reason is ObjectiveAssetDecisionReason.VALUATION_REQUIRED
