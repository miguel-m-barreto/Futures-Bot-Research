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
    validate_contract_asset_semantics_execution_cost_readiness,
)
from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.collateral_valuation import (
    CollateralValuationDecisionReason,
    CollateralValuationReadinessDecision,
)
from futures_bot.domain.execution_costs import (
    DepthModelKind,
    ExecutionCostCompatibility,
    ExecutionCostDecisionReason,
    ExecutionCostPolicy,
    ExecutionCostReadinessDecision,
    ExecutionCostRuleSnapshot,
    ExecutionCostSourceHealth,
    ExecutionCostSourceKind,
    ExecutionCostSourceTrust,
    FeeModelKind,
    FundingModelKind,
)
from futures_bot.domain.margin_liquidation import (
    MarginLiquidationCompatibility,
    MarginLiquidationDecisionReason,
    MarginLiquidationPolicy,
    MarginLiquidationReadinessDecision,
    MarginMode,
)
from futures_bot.domain.objective_assets import (
    ObjectiveAssetCompatibility,
    ObjectiveAssetDecisionReason,
    ObjectiveAssetPolicy,
    ObjectiveAssetReadinessDecision,
)
from futures_bot.execution_costs.policies import evaluate_execution_cost_readiness

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _asset(symbol: str, asset_class: AssetClass = AssetClass.CRYPTO) -> AssetDescriptor:
    return AssetDescriptor(symbol=symbol, asset_class=asset_class)


def _stable(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.STABLECOIN)


def _fiat(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.FIAT)


def _policy(**overrides: object) -> ExecutionCostPolicy:
    values = {
        "max_snapshot_age": 60_000,
        "require_source_record": True,
        "allowed_source_kinds": (ExecutionCostSourceKind.VENUE_FEE_SCHEDULE,),
        "allowed_source_trust": (ExecutionCostSourceTrust.OFFICIAL,),
        "allowed_source_health": (ExecutionCostSourceHealth.HEALTHY,),
        "allowed_fee_models": (FeeModelKind.MAKER_TAKER_BPS,),
        "allowed_funding_models": (FundingModelKind.PERIODIC_RATE,),
        "allowed_depth_models": (DepthModelKind.ORDER_BOOK_DEPTH,),
        "require_fee_model": True,
        "require_maker_fee": True,
        "require_taker_fee": True,
        "require_fee_asset_match": True,
        "require_funding_model": True,
        "require_funding_interval": True,
        "require_funding_asset_match": True,
        "require_depth_model": True,
        "require_min_depth_notional": True,
        "require_depth_reference_asset_match": True,
        "require_max_spread_bps": True,
        "metadata": {},
    }
    values.update(overrides)
    return ExecutionCostPolicy(**values)


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
        "fee_asset": _stable("USDT"),
        "funding_asset": _stable("USDT"),
        "depth_reference_asset": _stable("USDT"),
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
        "requires_fee_rules": True,
        "requires_funding_rules": True,
        "requires_depth_rules": True,
        "execution_cost_policy_id": policy.policy_id,
        "metadata": {},
    }
    values.update(overrides)
    return ContractAssetSemantics(**values)


def _snapshot(**overrides: object) -> ExecutionCostRuleSnapshot:
    values = {
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "fee_asset": "USDT",
        "funding_asset": "USDT",
        "depth_reference_asset": "USDT",
        "fee_model_kind": FeeModelKind.MAKER_TAKER_BPS,
        "maker_fee_rate": Decimal("0.0002"),
        "taker_fee_rate": Decimal("0.0006"),
        "fee_tier_id": "tier-1",
        "funding_model_kind": FundingModelKind.PERIODIC_RATE,
        "funding_interval_ms": 28_800_000,
        "funding_rate_cap": Decimal("0.01"),
        "depth_model_kind": DepthModelKind.ORDER_BOOK_DEPTH,
        "min_depth_notional": Decimal("1000"),
        "max_spread_bps": Decimal("5"),
        "observed_at": NOW - timedelta(seconds=1),
        "captured_at": NOW - timedelta(seconds=1),
        "source_kind": ExecutionCostSourceKind.VENUE_FEE_SCHEDULE,
        "source_trust": ExecutionCostSourceTrust.OFFICIAL,
        "source_health": ExecutionCostSourceHealth.HEALTHY,
        "source_record_id": "source-record-1",
        "metadata": {},
    }
    values.update(overrides)
    return ExecutionCostRuleSnapshot(**values)


def _cost_decision(
    *,
    policy: ExecutionCostPolicy | None = None,
    snapshot: ExecutionCostRuleSnapshot | None = None,
) -> ExecutionCostReadinessDecision:
    return evaluate_execution_cost_readiness(
        policy=_policy() if policy is None else policy,
        checked_at=NOW,
        snapshot=_snapshot() if snapshot is None else snapshot,
        venue_id="kucoin",
        instrument_id="BTCUSDTM",
        fee_asset="USDT",
        funding_asset="USDT",
        depth_reference_asset="USDT",
    )


def _ready_cost_decision(**overrides: object) -> ExecutionCostReadinessDecision:
    policy = _policy()
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    values = {
        "policy_id": policy.policy_id,
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "fee_asset": AssetSymbol("USDT"),
        "funding_asset": AssetSymbol("USDT"),
        "depth_reference_asset": AssetSymbol("USDT"),
        "ready": True,
        "reason": ExecutionCostDecisionReason.READY,
        "compatibility": ExecutionCostCompatibility.DIRECT_MATCH,
        "checked_at": NOW,
        "details": {},
    }
    values.update(overrides)
    return ExecutionCostReadinessDecision(**values)


def test_fee_funding_and_depth_requirements_reject_without_decision() -> None:
    for semantics in (
        _semantics(requires_funding_rules=False, requires_depth_rules=False),
        _semantics(requires_fee_rules=False, requires_depth_rules=False),
        _semantics(requires_fee_rules=False, requires_funding_rules=False),
    ):
        decision = validate_contract_asset_semantics_execution_cost_readiness(
            semantics,
            None,
        )

        assert not decision.ready
        assert decision.reason is (
            AssetSemanticsReadinessReason.EXECUTION_COST_RULES_REQUIRED
        )


def test_matching_ready_cost_decision_satisfies_requirement() -> None:
    decision = validate_contract_asset_semantics_execution_cost_readiness(
        _semantics(),
        _cost_decision(),
    )

    assert decision.ready


def test_unknown_cost_assets_reject_as_semantic_shape_problem() -> None:
    cases = (
        _semantics(
            fee_asset=_asset("USDT", AssetClass.UNKNOWN),
            requires_funding_rules=False,
            requires_depth_rules=False,
        ),
        _semantics(
            funding_asset=_asset("USDT", AssetClass.UNKNOWN),
            requires_fee_rules=False,
            requires_depth_rules=False,
        ),
        _semantics(
            depth_reference_asset=_asset("USDT", AssetClass.UNKNOWN),
            requires_fee_rules=False,
            requires_funding_rules=False,
        ),
    )

    for semantics in cases:
        decision = validate_contract_asset_semantics_execution_cost_readiness(
            semantics,
            _cost_decision(),
        )

        assert not decision.ready
        assert decision.reason is AssetSemanticsReadinessReason.ASSET_MISSING


def test_not_ready_wrong_policy_and_wrong_assets_reject() -> None:
    not_ready = validate_contract_asset_semantics_execution_cost_readiness(
        _semantics(),
        _cost_decision(snapshot=_snapshot(maker_fee_rate=None)),
    )
    wrong_policy = validate_contract_asset_semantics_execution_cost_readiness(
        _semantics(),
        _cost_decision(policy=_policy(require_max_spread_bps=False)),
    )
    wrong_fee = validate_contract_asset_semantics_execution_cost_readiness(
        _semantics(),
        _cost_decision(snapshot=_snapshot(fee_asset="USDC")),
    )
    wrong_funding = validate_contract_asset_semantics_execution_cost_readiness(
        _semantics(),
        _cost_decision(snapshot=_snapshot(funding_asset="USDC")),
    )
    wrong_depth = validate_contract_asset_semantics_execution_cost_readiness(
        _semantics(),
        _cost_decision(snapshot=_snapshot(depth_reference_asset="USD")),
    )

    assert not_ready.reason is AssetSemanticsReadinessReason.EXECUTION_COST_RULES_REQUIRED
    assert wrong_policy.reason is (
        AssetSemanticsReadinessReason.EXECUTION_COST_RULES_REQUIRED
    )
    assert wrong_fee.reason is AssetSemanticsReadinessReason.EXECUTION_COST_RULES_REQUIRED
    assert wrong_funding.reason is (
        AssetSemanticsReadinessReason.EXECUTION_COST_RULES_REQUIRED
    )
    assert wrong_depth.reason is AssetSemanticsReadinessReason.EXECUTION_COST_RULES_REQUIRED


def test_ready_cost_decision_with_wrong_or_missing_scope_rejects() -> None:
    cases = (
        _ready_cost_decision(venue_id="binance"),
        _ready_cost_decision(instrument_id="ETHUSDT"),
        _ready_cost_decision(venue_id=None),
        _ready_cost_decision(instrument_id=None),
    )

    for cost_decision in cases:
        semantics_decision = validate_contract_asset_semantics_execution_cost_readiness(
            _semantics(),
            cost_decision,
        )

        assert not semantics_decision.ready
        assert semantics_decision.reason is (
            AssetSemanticsReadinessReason.EXECUTION_COST_RULES_REQUIRED
        )


def test_unrelated_readiness_gates_cannot_bypass_cost_rules() -> None:
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
    margin_policy = MarginLiquidationPolicy.strict_official(metadata={})
    if margin_policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    margin_decision = MarginLiquidationReadinessDecision(
        policy_id=margin_policy.policy_id,
        venue_id="kucoin",
        instrument_id="BTCUSDTM",
        margin_mode=MarginMode.ISOLATED,
        collateral_asset=AssetSymbol("USDT"),
        margin_asset=AssetSymbol("USDT"),
        settlement_asset=AssetSymbol("USDT"),
        ready=True,
        reason=MarginLiquidationDecisionReason.READY,
        compatibility=MarginLiquidationCompatibility.DIRECT_MATCH,
        checked_at=NOW,
        details={},
    )

    assert objective_decision.ready
    assert collateral_decision.ready
    assert conversion_decision.ready
    assert margin_decision.ready

    for other_decision in (
        objective_decision,
        collateral_decision,
        conversion_decision,
        margin_decision,
    ):
        decision = validate_contract_asset_semantics_execution_cost_readiness(
            _semantics(),
            other_decision,  # type: ignore[arg-type]
        )

        assert not decision.ready
        assert decision.reason is (
            AssetSemanticsReadinessReason.EXECUTION_COST_RULES_REQUIRED
        )
