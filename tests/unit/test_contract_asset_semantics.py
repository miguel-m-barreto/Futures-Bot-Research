from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.asset_semantics import (
    AssetClass,
    AssetDescriptor,
    AssetSemanticsReadinessReason,
    CollateralMode,
    ContractAssetSemantics,
    ContractPayoffKind,
    SettlementMode,
    validate_contract_asset_semantics_readiness,
)


def _asset(symbol: str, asset_class: AssetClass = AssetClass.CRYPTO) -> AssetDescriptor:
    return AssetDescriptor(symbol=symbol, asset_class=asset_class)


def _stable(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.STABLECOIN)


def _semantics(**overrides: object) -> ContractAssetSemantics:
    values = {
        "venue_id": "phemex",
        "instrument_id": "BTCUSDT",
        "base_asset": _asset("BTC"),
        "quote_asset": _stable("USDT"),
        "margin_asset": _stable("USDT"),
        "settlement_asset": _stable("USDT"),
        "pnl_asset": _stable("USDT"),
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
        "metadata": {},
    }
    values.update(overrides)
    return ContractAssetSemantics(**values)


def test_multi_collateral_btcusdt_semantics_can_be_represented() -> None:
    semantics = _semantics(
        collateral_assets=(_stable("USDT"), _asset("BTC"), _asset("ETH")),
        collateral_mode=CollateralMode.MULTI_ASSET,
    )

    assert semantics.collateral_mode is CollateralMode.MULTI_ASSET
    assert tuple(asset.symbol for asset in semantics.collateral_assets) == (
        "USDT",
        "BTC",
        "ETH",
    )


def test_objective_asset_different_from_pnl_asset_requires_objective_valuation() -> None:
    semantics = _semantics(
        objective_asset=_asset("ETH"),
        requires_objective_valuation=True,
    )
    decision = validate_contract_asset_semantics_readiness(semantics)

    assert decision.reason is (
        AssetSemanticsReadinessReason.OBJECTIVE_ASSET_VALUATION_REQUIRED
    )


def test_contract_size_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="contract_size"):
        _semantics(contract_size=Decimal("0"))


def test_collateral_assets_must_be_non_empty() -> None:
    with pytest.raises(ValidationError, match="collateral_assets"):
        _semantics(collateral_assets=())


def test_inverse_and_quanto_contract_value_asset_is_explicit() -> None:
    with pytest.raises(ValidationError, match="contract_value_asset"):
        _semantics(payoff_kind=ContractPayoffKind.INVERSE)

    usd = _asset("USD", AssetClass.FIAT)
    semantics = _semantics(
        payoff_kind=ContractPayoffKind.INVERSE,
        settlement_asset=_asset("BTC"),
        pnl_asset=_asset("BTC"),
        margin_asset=_asset("BTC"),
        collateral_assets=(_asset("BTC"),),
        quote_asset=usd,
        valuation_reference_asset=usd,
        contract_value_asset=usd,
    )
    assert semantics.contract_value_asset == usd
