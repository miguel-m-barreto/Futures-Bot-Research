from __future__ import annotations

from decimal import Decimal

from futures_bot.domain.asset_semantics import (
    AssetClass,
    AssetDescriptor,
    ContractPayoffKind,
    CrossVenueExposureComparabilityReason,
    EconomicExposureDescriptor,
    compare_cross_venue_economic_exposures,
    economic_exposures_are_comparable,
)


def _asset(symbol: str, asset_class: AssetClass = AssetClass.CRYPTO) -> AssetDescriptor:
    return AssetDescriptor(symbol=symbol, asset_class=asset_class, canonical_symbol=symbol)


def _stable(symbol: str) -> AssetDescriptor:
    return _asset(symbol, AssetClass.STABLECOIN)


def _exposure(**overrides: object) -> EconomicExposureDescriptor:
    values = {
        "venue_id": "binance",
        "instrument_id": "ETHUSDT",
        "base_asset": _asset("ETH"),
        "quote_asset": _stable("USDT"),
        "payoff_kind": ContractPayoffKind.LINEAR,
        "settlement_asset": _stable("USDT"),
        "pnl_asset": _stable("USDT"),
        "valuation_reference_asset": _stable("USDT"),
        "contract_size": Decimal("1"),
        "metadata": {},
    }
    values.update(overrides)
    return EconomicExposureDescriptor(**values)


def test_same_binance_and_kucoin_ethusdt_exposure_comparable() -> None:
    left = _exposure(venue_id="binance", instrument_id="ETHUSDT")
    right = _exposure(venue_id="kucoin", instrument_id="ETH-USDT")

    decision = compare_cross_venue_economic_exposures(left, right)

    assert decision.comparable
    assert decision.reason is CrossVenueExposureComparabilityReason.COMPARABLE
    assert economic_exposures_are_comparable(left, right)


def test_different_base_asset_not_comparable() -> None:
    decision = compare_cross_venue_economic_exposures(
        _exposure(),
        _exposure(base_asset=_asset("BTC")),
    )

    assert decision.reason is CrossVenueExposureComparabilityReason.BASE_ASSET_MISMATCH


def test_different_quote_asset_not_comparable() -> None:
    decision = compare_cross_venue_economic_exposures(
        _exposure(),
        _exposure(quote_asset=_asset("USD", AssetClass.FIAT)),
    )

    assert decision.reason is CrossVenueExposureComparabilityReason.QUOTE_ASSET_MISMATCH


def test_linear_vs_inverse_not_comparable_by_default() -> None:
    decision = compare_cross_venue_economic_exposures(
        _exposure(),
        _exposure(payoff_kind=ContractPayoffKind.INVERSE),
    )

    assert decision.reason is CrossVenueExposureComparabilityReason.PAYOFF_KIND_MISMATCH


def test_different_settlement_asset_not_comparable_without_conversion_semantics() -> None:
    decision = compare_cross_venue_economic_exposures(
        _exposure(),
        _exposure(settlement_asset=_asset("BTC"), pnl_asset=_asset("BTC")),
    )

    assert decision.reason is (
        CrossVenueExposureComparabilityReason.SETTLEMENT_ASSET_MISMATCH
    )


def test_different_contract_size_not_comparable() -> None:
    decision = compare_cross_venue_economic_exposures(
        _exposure(),
        _exposure(contract_size=Decimal("0.1")),
    )

    assert decision.reason is CrossVenueExposureComparabilityReason.CONTRACT_SIZE_MISMATCH


def test_price_dislocation_example_only_comparable_after_exposure_match() -> None:
    binance_price = Decimal("1200")
    kucoin_price = Decimal("1333")
    left = _exposure(venue_id="binance", instrument_id="ETHUSDT")
    right = _exposure(venue_id="kucoin", instrument_id="ETHUSDT")

    assert kucoin_price > binance_price
    assert compare_cross_venue_economic_exposures(left, right).comparable
