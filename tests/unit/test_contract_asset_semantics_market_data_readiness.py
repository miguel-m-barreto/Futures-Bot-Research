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
    validate_contract_asset_semantics_market_data_readiness,
)
from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.collateral_valuation import (
    CollateralValuationDecisionReason,
    CollateralValuationReadinessDecision,
)
from futures_bot.domain.execution_costs import (
    ExecutionCostCompatibility,
    ExecutionCostDecisionReason,
    ExecutionCostPolicy,
    ExecutionCostReadinessDecision,
)
from futures_bot.domain.margin_liquidation import (
    MarginLiquidationCompatibility,
    MarginLiquidationDecisionReason,
    MarginLiquidationPolicy,
    MarginLiquidationReadinessDecision,
    MarginMode,
)
from futures_bot.domain.market_data import (
    MarketDataCompatibility,
    MarketDataContinuityStatus,
    MarketDataObservationKind,
    MarketDataObservationSnapshot,
    MarketDataReadinessDecision,
    MarketDataReadinessPolicy,
    MarketDataReadinessReason,
    MarketDataSourceHealth,
    MarketDataSourceKind,
    MarketDataSourceTrust,
)
from futures_bot.domain.objective_assets import (
    ObjectiveAssetCompatibility,
    ObjectiveAssetDecisionReason,
    ObjectiveAssetPolicy,
    ObjectiveAssetReadinessDecision,
)
from futures_bot.market_data.policies import evaluate_market_data_readiness

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _asset(symbol: str, asset_class: AssetClass = AssetClass.CRYPTO) -> AssetDescriptor:
    return AssetDescriptor(symbol=symbol, asset_class=asset_class)


def _stable(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.STABLECOIN)


def _fiat(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.FIAT)


def _policy(**overrides: object) -> MarketDataReadinessPolicy:
    values = {
        "max_observation_age": 5_000,
        "require_source_record": True,
        "allowed_source_kinds": (MarketDataSourceKind.VENUE_PUBLIC_MARKET_DATA,),
        "allowed_source_trust": (MarketDataSourceTrust.OFFICIAL,),
        "allowed_source_health": (MarketDataSourceHealth.HEALTHY,),
        "allowed_observation_kinds": (
            MarketDataObservationKind.BEST_BID_ASK,
            MarketDataObservationKind.ORDER_BOOK_DEPTH,
        ),
        "allowed_continuity_statuses": (MarketDataContinuityStatus.CONTINUOUS,),
        "require_sequence": True,
        "require_continuous_sequence": True,
        "require_best_bid": True,
        "require_best_ask": True,
        "require_bid_ask_not_crossed": True,
        "require_mark_price": False,
        "require_index_price": False,
        "require_last_trade_price": False,
        "require_depth_notional": False,
        "require_depth_reference_asset_match": False,
        "require_spread_bps": True,
        "metadata": {},
    }
    values.update(overrides)
    return MarketDataReadinessPolicy(**values)


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
        "requires_market_data_rules": True,
        "market_data_policy_id": policy.policy_id,
        "market_data_observation_kind": MarketDataObservationKind.BEST_BID_ASK,
        "metadata": {},
    }
    values.update(overrides)
    return ContractAssetSemantics(**values)


def _snapshot(**overrides: object) -> MarketDataObservationSnapshot:
    values = {
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "observation_kind": MarketDataObservationKind.BEST_BID_ASK,
        "best_bid_price": Decimal("100"),
        "best_ask_price": Decimal("101"),
        "depth_reference_asset": "USDT",
        "depth_notional": Decimal("1000"),
        "spread_bps": Decimal("10"),
        "sequence_number": 101,
        "previous_sequence_number": 100,
        "continuity_status": MarketDataContinuityStatus.CONTINUOUS,
        "observed_at": NOW - timedelta(seconds=1),
        "captured_at": NOW - timedelta(seconds=1),
        "source_kind": MarketDataSourceKind.VENUE_PUBLIC_MARKET_DATA,
        "source_trust": MarketDataSourceTrust.OFFICIAL,
        "source_health": MarketDataSourceHealth.HEALTHY,
        "source_record_id": "source-record-1",
        "metadata": {},
    }
    values.update(overrides)
    return MarketDataObservationSnapshot(**values)


def _market_data_decision(
    *,
    policy: MarketDataReadinessPolicy | None = None,
    snapshot: MarketDataObservationSnapshot | None = None,
    observation_kind: MarketDataObservationKind = MarketDataObservationKind.BEST_BID_ASK,
) -> MarketDataReadinessDecision:
    return evaluate_market_data_readiness(
        policy=_policy() if policy is None else policy,
        checked_at=NOW,
        snapshot=_snapshot() if snapshot is None else snapshot,
        venue_id="kucoin",
        instrument_id="BTCUSDTM",
        observation_kind=observation_kind,
        depth_reference_asset="USDT",
    )


def _ready_market_data_decision(**overrides: object) -> MarketDataReadinessDecision:
    policy = _policy()
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    values = {
        "policy_id": policy.policy_id,
        "venue_id": "kucoin",
        "instrument_id": "BTCUSDTM",
        "observation_kind": MarketDataObservationKind.BEST_BID_ASK,
        "depth_reference_asset": AssetSymbol("USDT"),
        "ready": True,
        "reason": MarketDataReadinessReason.READY,
        "compatibility": MarketDataCompatibility.DIRECT_MATCH,
        "checked_at": NOW,
        "details": {},
    }
    values.update(overrides)
    return MarketDataReadinessDecision(**values)


def test_market_data_requirements_reject_without_decision() -> None:
    for semantics in (
        _semantics(),
        _semantics(
            requires_market_data_rules=False,
            requires_order_book_depth=True,
            market_data_observation_kind=MarketDataObservationKind.ORDER_BOOK_DEPTH,
        ),
    ):
        decision = validate_contract_asset_semantics_market_data_readiness(
            semantics,
            None,
        )

        assert not decision.ready
        assert decision.reason is AssetSemanticsReadinessReason.MARKET_DATA_RULES_REQUIRED


def test_matching_ready_market_data_decision_satisfies_requirement() -> None:
    decision = validate_contract_asset_semantics_market_data_readiness(
        _semantics(),
        _market_data_decision(),
    )

    assert decision.ready


def test_not_ready_wrong_policy_kind_and_depth_asset_reject() -> None:
    not_ready = validate_contract_asset_semantics_market_data_readiness(
        _semantics(),
        _market_data_decision(snapshot=_snapshot(best_bid_price=None)),
    )
    wrong_policy = validate_contract_asset_semantics_market_data_readiness(
        _semantics(),
        _market_data_decision(policy=_policy(require_last_trade_price=True)),
    )
    wrong_kind = validate_contract_asset_semantics_market_data_readiness(
        _semantics(),
        _ready_market_data_decision(observation_kind=MarketDataObservationKind.MARK_PRICE),
    )
    wrong_depth_asset = validate_contract_asset_semantics_market_data_readiness(
        _semantics(
            requires_market_data_rules=False,
            requires_order_book_depth=True,
            market_data_observation_kind=MarketDataObservationKind.ORDER_BOOK_DEPTH,
        ),
        _ready_market_data_decision(
            observation_kind=MarketDataObservationKind.ORDER_BOOK_DEPTH,
            depth_reference_asset=AssetSymbol("USD"),
        ),
    )

    assert not_ready.reason is AssetSemanticsReadinessReason.MARKET_DATA_RULES_REQUIRED
    assert wrong_policy.reason is AssetSemanticsReadinessReason.MARKET_DATA_RULES_REQUIRED
    assert wrong_kind.reason is AssetSemanticsReadinessReason.MARKET_DATA_RULES_REQUIRED
    assert wrong_depth_asset.reason is (
        AssetSemanticsReadinessReason.MARKET_DATA_RULES_REQUIRED
    )


def test_ready_market_data_decision_with_wrong_or_missing_scope_rejects() -> None:
    cases = (
        _ready_market_data_decision(venue_id="binance"),
        _ready_market_data_decision(instrument_id="ETHUSDT"),
        _ready_market_data_decision(venue_id=None),
        _ready_market_data_decision(instrument_id=None),
    )

    for market_data_decision in cases:
        semantics_decision = validate_contract_asset_semantics_market_data_readiness(
            _semantics(),
            market_data_decision,
        )

        assert not semantics_decision.ready
        assert semantics_decision.reason is (
            AssetSemanticsReadinessReason.MARKET_DATA_RULES_REQUIRED
        )


def test_order_book_depth_requires_depth_observation_kind() -> None:
    decision = validate_contract_asset_semantics_market_data_readiness(
        _semantics(
            requires_market_data_rules=False,
            requires_order_book_depth=True,
            market_data_observation_kind=None,
        ),
        _ready_market_data_decision(
            observation_kind=MarketDataObservationKind.BEST_BID_ASK,
        ),
    )

    assert not decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.MARKET_DATA_RULES_REQUIRED


def test_unrelated_readiness_gates_cannot_bypass_market_data_rules() -> None:
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
    execution_policy = ExecutionCostPolicy.strict_official(metadata={})
    if execution_policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    execution_cost_decision = ExecutionCostReadinessDecision(
        policy_id=execution_policy.policy_id,
        venue_id="kucoin",
        instrument_id="BTCUSDTM",
        fee_asset=AssetSymbol("USDT"),
        funding_asset=AssetSymbol("USDT"),
        depth_reference_asset=AssetSymbol("USDT"),
        ready=True,
        reason=ExecutionCostDecisionReason.READY,
        compatibility=ExecutionCostCompatibility.DIRECT_MATCH,
        checked_at=NOW,
        details={},
    )

    for other_decision in (
        objective_decision,
        collateral_decision,
        conversion_decision,
        margin_decision,
        execution_cost_decision,
    ):
        decision = validate_contract_asset_semantics_market_data_readiness(
            _semantics(),
            other_decision,  # type: ignore[arg-type]
        )

        assert not decision.ready
        assert decision.reason is (
            AssetSemanticsReadinessReason.MARKET_DATA_RULES_REQUIRED
        )
