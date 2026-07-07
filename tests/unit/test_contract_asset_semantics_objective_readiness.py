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
    validate_contract_asset_semantics_objective_readiness,
    validate_contract_asset_semantics_readiness,
)
from futures_bot.domain.objective_assets import (
    ObjectiveAssetCompatibility,
    ObjectiveAssetDecisionReason,
    ObjectiveAssetPolicy,
    ObjectiveAssetReadinessDecision,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _asset(symbol: str, asset_class: AssetClass = AssetClass.CRYPTO) -> AssetDescriptor:
    return AssetDescriptor(symbol=symbol, asset_class=asset_class)


def _stable(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.STABLECOIN)


def _fiat(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.FIAT)


def _semantics(**overrides: object) -> ContractAssetSemantics:
    policy = ObjectiveAssetPolicy.accumulate("BTC")
    values = {
        "venue_id": "kucoin",
        "instrument_id": "ETHUSDT",
        "base_asset": _asset("ETH"),
        "quote_asset": _stable("USDT"),
        "margin_asset": _asset("ETH"),
        "settlement_asset": _stable("USDT"),
        "pnl_asset": _stable("USDT"),
        "collateral_assets": (_asset("ETH"),),
        "valuation_reference_asset": _fiat("USD"),
        "objective_asset": _asset("BTC"),
        "payoff_kind": ContractPayoffKind.LINEAR,
        "collateral_mode": CollateralMode.MULTI_ASSET,
        "settlement_mode": SettlementMode.SINGLE_ASSET,
        "contract_size": Decimal("1"),
        "requires_collateral_valuation": False,
        "requires_haircut_rules": False,
        "requires_conversion_rules": False,
        "requires_objective_valuation": True,
        "objective_asset_policy_id": policy.policy_id,
        "metadata": {},
    }
    values.update(overrides)
    return ContractAssetSemantics(**values)


def _objective_decision(
    *,
    ready: bool = True,
    compatibility: ObjectiveAssetCompatibility = ObjectiveAssetCompatibility.VALUATION_REQUIRED,
    policy: ObjectiveAssetPolicy | None = None,
    assets: dict[str, str | None] | None = None,
) -> ObjectiveAssetReadinessDecision:
    policy = ObjectiveAssetPolicy.accumulate("BTC") if policy is None else policy
    if policy.policy_id is None:
        raise AssertionError("policy_id was not assigned")
    asset_values: dict[str, str | None] = {
        "objective_asset": "BTC",
        "pnl_asset": "USDT",
        "settlement_asset": "USDT",
    }
    asset_values.update({} if assets is None else assets)
    return ObjectiveAssetReadinessDecision(
        policy_id=policy.policy_id,
        objective_asset=asset_values["objective_asset"],
        pnl_asset=asset_values["pnl_asset"],
        settlement_asset=asset_values["settlement_asset"],
        ready=ready,
        reason=(
            ObjectiveAssetDecisionReason.READY
            if ready
            else ObjectiveAssetDecisionReason.VALUATION_REQUIRED
        ),
        compatibility=compatibility,
        checked_at=NOW,
        details={},
    )


def test_requires_objective_valuation_remains_not_ready_without_helper() -> None:
    semantics = _semantics(objective_asset_policy_id=None)
    decision = validate_contract_asset_semantics_readiness(semantics)

    assert not decision.ready
    assert decision.reason is (
        AssetSemanticsReadinessReason.OBJECTIVE_ASSET_VALUATION_REQUIRED
    )


def test_ready_objective_decision_satisfies_objective_valuation_requirement() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(),
        _objective_decision(),
    )

    assert decision.ready


def test_not_ready_objective_decision_does_not_satisfy_requirement() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(),
        _objective_decision(ready=False),
    )

    assert not decision.ready
    assert decision.reason is (
        AssetSemanticsReadinessReason.OBJECTIVE_ASSET_VALUATION_REQUIRED
    )


def test_rejects_objective_decision_for_unrelated_objective_asset() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(),
        _objective_decision(assets={"objective_asset": "ETH"}),
    )

    assert not decision.ready
    assert decision.reason is (
        AssetSemanticsReadinessReason.OBJECTIVE_ASSET_VALUATION_REQUIRED
    )


def test_rejects_objective_decision_with_wrong_policy_id() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(),
        _objective_decision(policy=ObjectiveAssetPolicy.accumulate("ETH")),
    )

    assert not decision.ready
    assert decision.reason is (
        AssetSemanticsReadinessReason.OBJECTIVE_ASSET_VALUATION_REQUIRED
    )


def test_rejects_objective_decision_with_wrong_pnl_asset() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(),
        _objective_decision(assets={"pnl_asset": "ETH"}),
    )

    assert not decision.ready
    assert decision.reason is (
        AssetSemanticsReadinessReason.OBJECTIVE_ASSET_VALUATION_REQUIRED
    )


def test_rejects_objective_decision_with_missing_pnl_asset() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(),
        _objective_decision(assets={"pnl_asset": None}),
    )

    assert not decision.ready
    assert decision.reason is (
        AssetSemanticsReadinessReason.OBJECTIVE_ASSET_VALUATION_REQUIRED
    )


def test_rejects_objective_decision_with_wrong_settlement_asset() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(),
        _objective_decision(assets={"settlement_asset": "ETH"}),
    )

    assert not decision.ready
    assert decision.reason is (
        AssetSemanticsReadinessReason.OBJECTIVE_ASSET_VALUATION_REQUIRED
    )


def test_rejects_objective_decision_with_missing_settlement_asset() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(),
        _objective_decision(assets={"settlement_asset": None}),
    )

    assert not decision.ready
    assert decision.reason is (
        AssetSemanticsReadinessReason.OBJECTIVE_ASSET_VALUATION_REQUIRED
    )


def test_conversion_rules_requirement_cannot_be_bypassed_by_direct_unrelated_asset() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(requires_conversion_rules=True),
        _objective_decision(compatibility=ObjectiveAssetCompatibility.DIRECT_MATCH),
    )

    assert not decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.CONVERSION_RULES_REQUIRED


def test_conversion_rules_requirement_rejects_missing_pnl_asset() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(requires_conversion_rules=True),
        _objective_decision(
            compatibility=ObjectiveAssetCompatibility.CONVERSION_REQUIRED,
            assets={"pnl_asset": None},
        ),
    )

    assert not decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.CONVERSION_RULES_REQUIRED


def test_conversion_rules_requirement_rejects_missing_settlement_asset() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(requires_conversion_rules=True),
        _objective_decision(
            compatibility=ObjectiveAssetCompatibility.CONVERSION_REQUIRED,
            assets={"settlement_asset": None},
        ),
    )

    assert not decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.CONVERSION_RULES_REQUIRED


def test_explicit_objective_conversion_evidence_satisfies_conversion_requirement() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(requires_conversion_rules=True),
        _objective_decision(compatibility=ObjectiveAssetCompatibility.CONVERSION_REQUIRED),
    )

    assert decision.ready


def test_objective_readiness_cannot_bypass_collateral_valuation_requirement() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(requires_collateral_valuation=True),
        _objective_decision(),
    )

    assert not decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.VALUATION_REQUIRED


def test_objective_readiness_cannot_bypass_haircut_requirement() -> None:
    decision = validate_contract_asset_semantics_objective_readiness(
        _semantics(requires_haircut_rules=True),
        _objective_decision(),
    )

    assert not decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.HAIRCUT_RULES_REQUIRED
