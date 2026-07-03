from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.asset_semantics import (
    AssetClass,
    AssetDescriptor,
    AssetRole,
    AssetRoleBinding,
    AssetSemanticsReadinessReason,
    CollateralMode,
    ContractAssetSemantics,
    ContractPayoffKind,
    SettlementMode,
    ValuationRequirement,
    validate_contract_asset_semantics_readiness,
)


def _asset(symbol: str, asset_class: AssetClass = AssetClass.CRYPTO) -> AssetDescriptor:
    return AssetDescriptor(symbol=symbol, asset_class=asset_class)


def _stable(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.STABLECOIN)


def _linear_semantics(**overrides: object) -> ContractAssetSemantics:
    values = {
        "venue_id": "binance",
        "instrument_id": "ETHUSDT",
        "base_asset": _asset("ETH"),
        "quote_asset": _stable("USDT"),
        "margin_asset": _stable("USDT"),
        "settlement_asset": _stable("USDT"),
        "pnl_asset": _stable("USDT"),
        "fee_asset": _stable("USDT"),
        "collateral_assets": (_stable("USDT"),),
        "valuation_reference_asset": _stable("USDT"),
        "payoff_kind": ContractPayoffKind.LINEAR,
        "collateral_mode": CollateralMode.SINGLE_ASSET,
        "settlement_mode": SettlementMode.SINGLE_ASSET,
        "contract_size": Decimal("1"),
        "requires_collateral_valuation": False,
        "requires_haircut_rules": False,
        "requires_conversion_rules": False,
        "requires_objective_valuation": False,
        "metadata": {"source": "unit-test"},
    }
    values.update(overrides)
    return ContractAssetSemantics(**values)


def test_asset_descriptor_deterministic_id() -> None:
    first = AssetDescriptor(symbol="eth", asset_class=AssetClass.CRYPTO)
    second = AssetDescriptor(symbol=" ETH ", asset_class=AssetClass.CRYPTO)

    assert first.asset_id == second.asset_id
    assert first.symbol == "ETH"


def test_asset_descriptor_rejects_empty_symbol() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        AssetDescriptor(symbol=" ", asset_class=AssetClass.CRYPTO)


def test_asset_role_binding_deterministic() -> None:
    asset = _asset("BTC")
    first = AssetRoleBinding(role=AssetRole.BASE, asset=asset)
    second = AssetRoleBinding(role=AssetRole.BASE, asset=asset)

    assert first.binding_id == second.binding_id


def test_contract_asset_semantics_deterministic_id() -> None:
    assert _linear_semantics().semantics_id == _linear_semantics().semantics_id


def test_linear_usdt_margined_ethusdt_semantics_can_be_represented() -> None:
    semantics = _linear_semantics()

    assert semantics.base_asset.symbol == "ETH"
    assert semantics.margin_asset.symbol == "USDT"
    assert semantics.settlement_asset.symbol == "USDT"
    assert semantics.pnl_asset.symbol == "USDT"
    assert semantics.payoff_kind is ContractPayoffKind.LINEAR


def test_inverse_btc_margined_btcusd_semantics_can_be_represented() -> None:
    btc = _asset("BTC")
    usd = _asset("USD", AssetClass.FIAT)
    semantics = _linear_semantics(
        venue_id="coinex",
        instrument_id="BTCUSD-INVERSE",
        base_asset=btc,
        quote_asset=usd,
        margin_asset=btc,
        settlement_asset=btc,
        pnl_asset=btc,
        fee_asset=btc,
        collateral_assets=(btc,),
        valuation_reference_asset=usd,
        payoff_kind=ContractPayoffKind.INVERSE,
        contract_size=Decimal("100"),
        contract_value_asset=usd,
    )

    assert semantics.payoff_kind is ContractPayoffKind.INVERSE
    assert semantics.margin_asset.symbol == "BTC"
    assert semantics.settlement_asset.symbol == "BTC"


def test_metadata_must_be_json_compatible() -> None:
    with pytest.raises(ValidationError, match="JSON-compatible"):
        _linear_semantics(metadata={"bad": object()})


def test_unknown_asset_class_is_not_execution_ready() -> None:
    decision = validate_contract_asset_semantics_readiness(
        _linear_semantics(base_asset=_asset("ETH", AssetClass.UNKNOWN))
    )

    assert not decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.ASSET_MISSING


def test_readiness_ready_for_complete_linear_semantics() -> None:
    decision = validate_contract_asset_semantics_readiness(_linear_semantics())

    assert decision.ready
    assert decision.reason is AssetSemanticsReadinessReason.READY
    assert decision.valuation_requirements == (ValuationRequirement.NOT_REQUIRED,)


def test_readiness_rejects_unknown_payoff_kind() -> None:
    decision = validate_contract_asset_semantics_readiness(
        _linear_semantics(payoff_kind=ContractPayoffKind.UNKNOWN)
    )

    assert decision.reason is AssetSemanticsReadinessReason.PAYOFF_KIND_UNKNOWN


def test_readiness_rejects_unknown_collateral_mode() -> None:
    decision = validate_contract_asset_semantics_readiness(
        _linear_semantics(collateral_mode=CollateralMode.UNKNOWN)
    )

    assert decision.reason is AssetSemanticsReadinessReason.COLLATERAL_MODE_UNKNOWN


def test_readiness_rejects_unknown_settlement_mode() -> None:
    decision = validate_contract_asset_semantics_readiness(
        _linear_semantics(settlement_mode=SettlementMode.UNKNOWN)
    )

    assert decision.reason is AssetSemanticsReadinessReason.SETTLEMENT_MODE_UNKNOWN


def test_readiness_rejects_required_haircut_rules() -> None:
    decision = validate_contract_asset_semantics_readiness(
        _linear_semantics(requires_haircut_rules=True)
    )

    assert decision.reason is AssetSemanticsReadinessReason.HAIRCUT_RULES_REQUIRED


def test_readiness_rejects_required_conversion_rules() -> None:
    decision = validate_contract_asset_semantics_readiness(
        _linear_semantics(requires_conversion_rules=True)
    )

    assert decision.reason is AssetSemanticsReadinessReason.CONVERSION_RULES_REQUIRED


def test_readiness_rejects_required_collateral_valuation_without_policy() -> None:
    decision = validate_contract_asset_semantics_readiness(
        _linear_semantics(requires_collateral_valuation=True)
    )

    assert decision.reason is AssetSemanticsReadinessReason.VALUATION_REQUIRED
