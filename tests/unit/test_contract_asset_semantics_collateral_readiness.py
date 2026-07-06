from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from futures_bot.domain.asset_semantics import (
    AssetClass,
    AssetDescriptor,
    AssetSemanticsReadinessReason,
    CollateralMode,
    ContractAssetSemantics,
    ContractPayoffKind,
    SettlementMode,
    validate_contract_asset_semantics_collateral_readiness,
)
from futures_bot.domain.collateral_valuation import (
    CollateralEligibilityRule,
    CollateralEligibilityStatus,
    CollateralHaircutKind,
    CollateralHaircutRule,
    CollateralValuationDecisionReason,
    CollateralValuationHealth,
    CollateralValuationPolicy,
    CollateralValuationReadinessDecision,
    CollateralValuationSnapshot,
    CollateralValuationSourceKind,
    CollateralValuationTrust,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _asset(symbol: str, asset_class: AssetClass = AssetClass.CRYPTO) -> AssetDescriptor:
    return AssetDescriptor(symbol=symbol, asset_class=asset_class)


def _stable(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.STABLECOIN)


def _semantics(**overrides: object) -> ContractAssetSemantics:
    values = {
        "venue_id": "kucoin",
        "instrument_id": "ETHUSDT",
        "base_asset": _asset("ETH"),
        "quote_asset": _stable("USDT"),
        "margin_asset": _asset("ETH"),
        "settlement_asset": _stable("USDT"),
        "pnl_asset": _stable("USDT"),
        "collateral_assets": (_asset("ETH"),),
        "valuation_reference_asset": _asset("USD", AssetClass.FIAT),
        "payoff_kind": ContractPayoffKind.LINEAR,
        "collateral_mode": CollateralMode.MULTI_ASSET,
        "settlement_mode": SettlementMode.SINGLE_ASSET,
        "contract_size": Decimal("1"),
        "requires_collateral_valuation": True,
        "requires_haircut_rules": True,
        "requires_conversion_rules": False,
        "requires_objective_valuation": False,
        "collateral_valuation_policy_id": CollateralValuationPolicy.strict(
            reference_asset="USD"
        ).policy_id,
        "metadata": {},
    }
    values.update(overrides)
    return ContractAssetSemantics(**values)


def _ready_decision(*, include_haircut: bool = True) -> CollateralValuationReadinessDecision:
    snapshot = CollateralValuationSnapshot(
        collateral_asset="ETH",
        reference_asset="USD",
        price=Decimal("3000"),
        source_kind=CollateralValuationSourceKind.ORACLE_PRICE,
        trust=CollateralValuationTrust.OFFICIAL,
        health=CollateralValuationHealth.HEALTHY,
        observed_at=NOW,
        captured_at=NOW,
        metadata={},
    )
    haircut = (
        CollateralHaircutRule(
            collateral_asset="ETH",
            reference_asset="USD",
            haircut_kind=CollateralHaircutKind.FIXED_PERCENTAGE,
            haircut_rate=Decimal("0.20"),
            effective_at=NOW,
            metadata={},
        )
        if include_haircut
        else None
    )
    return CollateralValuationReadinessDecision(
        collateral_asset="ETH",
        reference_asset="USD",
        ready=True,
        reason=CollateralValuationDecisionReason.READY,
        valuation_snapshot=snapshot,
        haircut_rule=haircut,
        eligibility_rule=CollateralEligibilityRule(
            collateral_asset="ETH",
            eligibility_status=CollateralEligibilityStatus.ELIGIBLE,
            effective_at=NOW,
            metadata={},
        ),
        checked_at=NOW,
        effective_value_multiplier=Decimal("0.80") if include_haircut else None,
        details={},
    )


def test_existing_readiness_behavior_unchanged_without_collateral_decisions() -> None:
    decision = validate_contract_asset_semantics_collateral_readiness(_semantics(), None)

    assert decision.reason is AssetSemanticsReadinessReason.HAIRCUT_RULES_REQUIRED


def test_requires_collateral_valuation_not_ready_without_decision() -> None:
    decision = validate_contract_asset_semantics_collateral_readiness(_semantics(), ())

    assert decision.reason is AssetSemanticsReadinessReason.VALUATION_REQUIRED


def test_ready_collateral_decision_satisfies_collateral_valuation_requirement() -> None:
    semantics = _semantics(requires_haircut_rules=False)
    decision = validate_contract_asset_semantics_collateral_readiness(
        semantics,
        (_ready_decision(),),
    )

    assert decision.ready


def test_haircut_requirement_cannot_be_bypassed_by_valuation_alone() -> None:
    decision = validate_contract_asset_semantics_collateral_readiness(
        _semantics(),
        (_ready_decision(include_haircut=False),),
    )

    assert decision.reason is AssetSemanticsReadinessReason.HAIRCUT_RULES_REQUIRED


def test_no_implicit_eth_usd_conversion_is_created() -> None:
    decision = validate_contract_asset_semantics_collateral_readiness(
        _semantics(valuation_reference_asset=_stable("USDT")),
        (_ready_decision(),),
    )

    assert decision.reason is AssetSemanticsReadinessReason.VALUATION_REQUIRED
