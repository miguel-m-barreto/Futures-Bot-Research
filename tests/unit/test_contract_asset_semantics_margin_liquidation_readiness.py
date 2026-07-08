from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from futures_bot.asset_conversion.policies import evaluate_asset_conversion_readiness
from futures_bot.domain.asset_conversion import (
    AssetConversionEvidenceKind,
    AssetConversionPolicy,
    AssetConversionRateSnapshot,
    AssetConversionSourceHealth,
    AssetConversionSourceKind,
    AssetConversionSourceTrust,
)
from futures_bot.domain.asset_semantics import (
    AssetClass,
    AssetDescriptor,
    AssetSemanticsReadinessReason,
    CollateralMode,
    ContractAssetSemantics,
    ContractPayoffKind,
    SettlementMode,
    validate_contract_asset_semantics_margin_liquidation_readiness,
)
from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.collateral_valuation import (
    CollateralValuationDecisionReason,
    CollateralValuationReadinessDecision,
)
from futures_bot.domain.margin_liquidation import (
    LiquidationModelKind,
    MarginLiquidationCompatibility,
    MarginLiquidationDecisionReason,
    MarginLiquidationPolicy,
    MarginLiquidationReadinessDecision,
    MarginLiquidationRuleSnapshot,
    MarginLiquidationSourceHealth,
    MarginLiquidationSourceKind,
    MarginLiquidationSourceTrust,
    MarginMode,
)
from futures_bot.domain.objective_assets import (
    ObjectiveAssetCompatibility,
    ObjectiveAssetDecisionReason,
    ObjectiveAssetPolicy,
    ObjectiveAssetReadinessDecision,
)
from futures_bot.margin_liquidation.policies import (
    evaluate_margin_liquidation_readiness,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _asset(symbol: str, asset_class: AssetClass = AssetClass.CRYPTO) -> AssetDescriptor:
    return AssetDescriptor(symbol=symbol, asset_class=asset_class)


def _stable(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.STABLECOIN)


def _fiat(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.FIAT)


def _policy(**overrides: object) -> MarginLiquidationPolicy:
    values = {
        "max_snapshot_age": 60_000,
        "require_source_record": True,
        "allowed_source_kinds": (MarginLiquidationSourceKind.VENUE_RISK_BRACKET,),
        "allowed_source_trust": (MarginLiquidationSourceTrust.OFFICIAL,),
        "allowed_source_health": (MarginLiquidationSourceHealth.HEALTHY,),
        "allowed_margin_modes": (MarginMode.ISOLATED,),
        "require_initial_margin": True,
        "require_maintenance_margin": True,
        "require_liquidation_fee": True,
        "require_max_leverage": True,
        "require_liquidation_model": True,
        "require_risk_tier": True,
        "require_collateral_asset_match": True,
        "require_margin_asset_match": True,
        "require_settlement_asset_match": True,
        "metadata": {},
    }
    values.update(overrides)
    return MarginLiquidationPolicy(**values)


def _semantics(**overrides: object) -> ContractAssetSemantics:
    policy = _policy()
    values = {
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "base_asset": _asset("BTC"),
        "quote_asset": _stable("USDT"),
        "margin_asset": _stable("USDT"),
        "settlement_asset": _stable("USDT"),
        "pnl_asset": _stable("USDT"),
        "collateral_assets": (_stable("USDT"),),
        "valuation_reference_asset": _fiat("USD"),
        "payoff_kind": ContractPayoffKind.LINEAR,
        "collateral_mode": CollateralMode.SINGLE_ASSET,
        "settlement_mode": SettlementMode.SINGLE_ASSET,
        "contract_size": Decimal("1"),
        "requires_collateral_valuation": False,
        "requires_haircut_rules": False,
        "requires_conversion_rules": False,
        "requires_objective_valuation": False,
        "requires_margin_rules": True,
        "requires_liquidation_rules": True,
        "margin_liquidation_policy_id": policy.policy_id,
        "metadata": {},
    }
    values.update(overrides)
    return ContractAssetSemantics(**values)


def _snapshot(**overrides: object) -> MarginLiquidationRuleSnapshot:
    values = {
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "margin_mode": MarginMode.ISOLATED,
        "collateral_asset": "USDT",
        "margin_asset": "USDT",
        "settlement_asset": "USDT",
        "initial_margin_rate": Decimal("0.01"),
        "maintenance_margin_rate": Decimal("0.005"),
        "liquidation_fee_rate": Decimal("0.002"),
        "max_leverage": Decimal("100"),
        "liquidation_model_kind": LiquidationModelKind.VENUE_FORMULA,
        "risk_tier_id": "tier-1",
        "observed_at": NOW - timedelta(seconds=1),
        "captured_at": NOW - timedelta(seconds=1),
        "source_kind": MarginLiquidationSourceKind.VENUE_RISK_BRACKET,
        "source_trust": MarginLiquidationSourceTrust.OFFICIAL,
        "source_health": MarginLiquidationSourceHealth.HEALTHY,
        "source_record_id": "source-record-1",
        "metadata": {},
    }
    values.update(overrides)
    return MarginLiquidationRuleSnapshot(**values)


def _margin_decision(
    *,
    policy: MarginLiquidationPolicy | None = None,
    snapshot: MarginLiquidationRuleSnapshot | None = None,
) -> MarginLiquidationReadinessDecision:
    return evaluate_margin_liquidation_readiness(
        policy=_policy() if policy is None else policy,
        checked_at=NOW,
        snapshot=_snapshot() if snapshot is None else snapshot,
        venue_id="kucoin",
        instrument_id="BTCUSDTM",
        margin_mode=MarginMode.ISOLATED,
        collateral_asset="USDT",
        margin_asset="USDT",
        settlement_asset="USDT",
    )


def _ready_margin_decision(**overrides: object) -> MarginLiquidationReadinessDecision:
    policy = _policy()
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    values = {
        "policy_id": policy.policy_id,
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "margin_mode": MarginMode.ISOLATED,
        "collateral_asset": AssetSymbol("USDT"),
        "margin_asset": AssetSymbol("USDT"),
        "settlement_asset": AssetSymbol("USDT"),
        "ready": True,
        "reason": MarginLiquidationDecisionReason.READY,
        "compatibility": MarginLiquidationCompatibility.DIRECT_MATCH,
        "snapshot_id": None,
        "checked_at": NOW,
        "details": {},
    }
    values.update(overrides)
    return MarginLiquidationReadinessDecision(**values)


def test_margin_and_liquidation_requirements_reject_without_decision() -> None:
    margin_required = validate_contract_asset_semantics_margin_liquidation_readiness(
        _semantics(requires_liquidation_rules=False),
        None,
    )
    liquidation_required = validate_contract_asset_semantics_margin_liquidation_readiness(
        _semantics(requires_margin_rules=False),
        None,
    )

    assert margin_required.reason is AssetSemanticsReadinessReason.MARGIN_RULES_REQUIRED
    assert liquidation_required.reason is (
        AssetSemanticsReadinessReason.LIQUIDATION_RULES_REQUIRED
    )


def test_matching_ready_margin_decision_satisfies_requirement() -> None:
    decision = validate_contract_asset_semantics_margin_liquidation_readiness(
        _semantics(),
        _margin_decision(),
    )

    assert decision.ready


def test_unknown_source_kind_margin_decision_cannot_satisfy_requirement() -> None:
    margin_decision = _margin_decision(
        snapshot=_snapshot(source_kind=MarginLiquidationSourceKind.UNKNOWN),
    )
    semantics_decision = validate_contract_asset_semantics_margin_liquidation_readiness(
        _semantics(),
        margin_decision,
    )

    assert not margin_decision.ready
    assert margin_decision.reason is MarginLiquidationDecisionReason.SOURCE_KIND_UNKNOWN
    assert not semantics_decision.ready
    assert semantics_decision.reason is (
        AssetSemanticsReadinessReason.MARGIN_RULES_REQUIRED
    )


def test_ready_margin_decision_with_wrong_or_missing_scope_rejects() -> None:
    cases = (
        _ready_margin_decision(venue_id="binance"),
        _ready_margin_decision(instrument_id="ETHUSDT"),
        _ready_margin_decision(venue_id=None),
        _ready_margin_decision(instrument_id=None),
    )

    for margin_decision in cases:
        semantics_decision = validate_contract_asset_semantics_margin_liquidation_readiness(
            _semantics(),
            margin_decision,
        )

        assert not semantics_decision.ready
        assert semantics_decision.reason is (
            AssetSemanticsReadinessReason.MARGIN_RULES_REQUIRED
        )


def test_not_ready_wrong_policy_and_wrong_assets_reject() -> None:
    not_ready = validate_contract_asset_semantics_margin_liquidation_readiness(
        _semantics(),
        _margin_decision(snapshot=_snapshot(initial_margin_rate=None)),
    )
    wrong_policy = validate_contract_asset_semantics_margin_liquidation_readiness(
        _semantics(),
        _margin_decision(policy=_policy(require_risk_tier=False)),
    )
    wrong_margin = validate_contract_asset_semantics_margin_liquidation_readiness(
        _semantics(),
        _margin_decision(snapshot=_snapshot(margin_asset="USDC")),
    )
    wrong_settlement = validate_contract_asset_semantics_margin_liquidation_readiness(
        _semantics(),
        _margin_decision(snapshot=_snapshot(settlement_asset="USDC")),
    )
    wrong_collateral = validate_contract_asset_semantics_margin_liquidation_readiness(
        _semantics(),
        _margin_decision(snapshot=_snapshot(collateral_asset="BTC")),
    )

    assert not_ready.reason is AssetSemanticsReadinessReason.MARGIN_RULES_REQUIRED
    assert wrong_policy.reason is AssetSemanticsReadinessReason.MARGIN_RULES_REQUIRED
    assert wrong_margin.reason is AssetSemanticsReadinessReason.MARGIN_RULES_REQUIRED
    assert wrong_settlement.reason is AssetSemanticsReadinessReason.MARGIN_RULES_REQUIRED
    assert wrong_collateral.reason is AssetSemanticsReadinessReason.MARGIN_RULES_REQUIRED


def test_other_readiness_gates_cannot_bypass_margin_rules() -> None:
    objective_policy = ObjectiveAssetPolicy.accumulate("USDT")
    if objective_policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    objective_decision = ObjectiveAssetReadinessDecision(
        policy_id=objective_policy.policy_id,
        objective_asset=AssetSymbol("USDT"),
        pnl_asset=AssetSymbol("USDT"),
        settlement_asset=AssetSymbol("USDT"),
        ready=True,
        reason=ObjectiveAssetDecisionReason.READY,
        compatibility=ObjectiveAssetCompatibility.DIRECT_MATCH,
        checked_at=NOW,
        details={},
    )
    collateral_decision = CollateralValuationReadinessDecision(
        collateral_asset=AssetSymbol("USDT"),
        reference_asset=AssetSymbol("USD"),
        ready=True,
        reason=CollateralValuationDecisionReason.READY,
        checked_at=NOW,
        effective_value_multiplier=Decimal("1"),
        details={},
    )
    conversion_policy = AssetConversionPolicy.strict(
        from_asset="USDT",
        to_asset="USD",
        metadata={},
    )
    conversion_snapshot = AssetConversionRateSnapshot(
        from_asset=AssetSymbol("USDT"),
        to_asset=AssetSymbol("USD"),
        rate=Decimal("1"),
        observed_at=NOW - timedelta(seconds=1),
        captured_at=NOW - timedelta(seconds=1),
        source_kind=AssetConversionSourceKind.ORACLE_PRICE,
        source_trust=AssetConversionSourceTrust.OFFICIAL,
        source_health=AssetConversionSourceHealth.HEALTHY,
        evidence_kind=AssetConversionEvidenceKind.DIRECT_PAIR_RATE,
        source_record_id="conversion-source",
        metadata={},
    )
    conversion_decision = evaluate_asset_conversion_readiness(
        policy=conversion_policy,
        checked_at=NOW,
        from_asset="USDT",
        to_asset="USD",
        rate_snapshot=conversion_snapshot,
    )

    assert objective_decision.ready
    assert collateral_decision.ready
    assert conversion_decision.ready

    decision = validate_contract_asset_semantics_margin_liquidation_readiness(
        _semantics(),
        None,
    )

    assert not decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.MARGIN_RULES_REQUIRED
