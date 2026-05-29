from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.assets import (
    AssetAmount,
    AssetDelta,
    AssetSymbol,
    StableCollateralAsset,
)


def test_asset_symbol_validation() -> None:
    assert str(AssetSymbol("USDT")) == "USDT"

    for value in ["", "usd", "US DT", "A", "TOO_LONG_ASSET_SYMBOL"]:
        with pytest.raises(ValidationError):
            AssetSymbol(value)


def test_stable_collateral_accepts_usdt_and_usdc_only() -> None:
    assert str(StableCollateralAsset("USDT")) == "USDT"
    assert str(StableCollateralAsset("USDC")) == "USDC"

    for value in ["ETH", "BTC", "BNB", "SOL", "USD"]:
        with pytest.raises(ValidationError):
            StableCollateralAsset(value)


def test_asset_amount_rejects_float_input() -> None:
    with pytest.raises(ValidationError, match="float input is prohibited"):
        AssetAmount(asset="USDT", amount=1.0)


def test_decimal_string_and_decimal_input_are_preserved() -> None:
    from_string = AssetAmount(asset="USDT", amount="1.2300")
    from_decimal = AssetAmount(asset="USDT", amount=Decimal("1.2300"))

    assert from_string.amount == Decimal("1.2300")
    assert from_decimal.amount == Decimal("1.2300")
    assert from_string.amount.as_tuple().exponent == -4


def test_same_asset_addition_and_subtraction() -> None:
    left = AssetAmount(asset="USDT", amount="10.5")
    right = AssetAmount(asset="USDT", amount="2.25")

    assert (left + right) == AssetAmount(asset="USDT", amount="12.75")
    assert (left - right) == AssetAmount(asset="USDT", amount="8.25")


def test_asset_amount_subtraction_below_zero_raises() -> None:
    left = AssetAmount(asset="USDT", amount="2")
    right = AssetAmount(asset="USDT", amount="3")

    with pytest.raises(ValidationError, match="non-negative"):
        _ = left - right


def test_cross_asset_operations_are_rejected() -> None:
    usdt = AssetAmount(asset="USDT", amount="10")
    eth = AssetAmount(asset="ETH", amount="1")

    with pytest.raises(ValueError, match="cross-asset"):
        _ = usdt + eth
    with pytest.raises(ValueError, match="cross-asset"):
        _ = usdt - eth


def test_usdt_and_usdc_never_combine_implicitly() -> None:
    usdt = AssetAmount(asset="USDT", amount="100")
    usdc = AssetAmount(asset="USDC", amount="100")

    with pytest.raises(ValueError, match="cross-asset"):
        _ = usdt + usdc


def test_negative_handling_helpers() -> None:
    with pytest.raises(ValidationError, match="non-negative"):
        AssetAmount(asset="USDT", amount="-1")

    negative_delta = AssetDelta(asset="USDT", amount="-1")
    assert negative_delta.amount == Decimal("-1")

    with pytest.raises(ValidationError, match="non-negative"):
        AssetAmount.non_negative("USDT", "-1")
    with pytest.raises(ValueError, match="positive"):
        AssetAmount.positive("USDT", "0")


def test_asset_delta_allows_signed_and_zero_values() -> None:
    assert AssetDelta(asset="USDT", amount="-1").amount == Decimal("-1")
    assert AssetDelta(asset="USDT", amount="0").amount == Decimal("0")
    assert AssetDelta(asset="USDT", amount="1").amount == Decimal("1")


def test_asset_delta_rejects_float_input() -> None:
    with pytest.raises(ValidationError, match="float input is prohibited"):
        AssetDelta(asset="USDT", amount=1.0)


def test_asset_delta_same_asset_arithmetic() -> None:
    positive = AssetDelta(asset="USDT", amount="3.20")
    negative = AssetDelta(asset="USDT", amount="-1.10")

    assert positive + negative == AssetDelta(asset="USDT", amount="2.10")
    assert positive - negative == AssetDelta(asset="USDT", amount="4.30")


def test_asset_delta_rejects_cross_asset_arithmetic() -> None:
    usdt = AssetDelta(asset="USDT", amount="1")
    usdc = AssetDelta(asset="USDC", amount="1")

    with pytest.raises(ValueError, match="cross-asset"):
        _ = usdt + usdc
    with pytest.raises(ValueError, match="cross-asset"):
        _ = usdt - usdc


def test_no_implicit_conversion_to_usd() -> None:
    amount = AssetAmount(asset="USDT", amount="100")
    delta = AssetDelta(asset="USDT", amount="-1")

    assert not hasattr(amount, "to_usd")
    assert not hasattr(delta, "to_usd")


def test_asset_symbol_non_string_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        AssetSymbol(123)  # type: ignore[arg-type]


def test_stable_collateral_non_symbol_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        StableCollateralAsset(object())  # type: ignore[arg-type]


def test_asset_amount_invalid_asset_type_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        AssetAmount(asset=object(), amount="1")  # type: ignore[arg-type]


def test_asset_delta_invalid_asset_type_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        AssetDelta(asset=object(), amount="0")  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["abc", "", "not-a-number", "1e.5", "--1"])
def test_asset_amount_invalid_decimal_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        AssetAmount(asset="USDT", amount=bad)


@pytest.mark.parametrize("bad", ["abc", "", "not-a-number"])
def test_asset_delta_invalid_decimal_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        AssetDelta(asset="USDT", amount=bad)


@pytest.mark.parametrize("bad", [" 0.5", "1 ", " 1.0 "])
def test_asset_amount_whitespace_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        AssetAmount(asset="USDT", amount=bad)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_asset_amount_non_finite_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        AssetAmount(asset="USDT", amount=bad)
