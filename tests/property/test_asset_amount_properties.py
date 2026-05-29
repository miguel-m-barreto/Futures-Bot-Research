from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from futures_bot.domain.assets import AssetAmount, AssetDelta

decimal_amounts = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=8,
)

signed_decimal_amounts = st.decimals(
    min_value=Decimal("-1000000"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=8,
)


@given(decimal_amounts)
def test_adding_zero_preserves_value(amount: Decimal) -> None:
    value = AssetAmount(asset="USDT", amount=amount)

    assert value + AssetAmount.zero("USDT") == value


@given(decimal_amounts, decimal_amounts)
def test_same_asset_addition_is_commutative(left: Decimal, right: Decimal) -> None:
    left_amount = AssetAmount(asset="USDC", amount=left)
    right_amount = AssetAmount(asset="USDC", amount=right)

    assert left_amount + right_amount == right_amount + left_amount


@given(decimal_amounts, decimal_amounts)
def test_same_asset_add_subtract_roundtrip(left: Decimal, right: Decimal) -> None:
    left_amount = AssetAmount(asset="USDT", amount=left)
    right_amount = AssetAmount(asset="USDT", amount=right)

    assert (left_amount + right_amount) - right_amount == left_amount


@given(decimal_amounts, decimal_amounts)
def test_cross_asset_operations_reject(left: Decimal, right: Decimal) -> None:
    left_amount = AssetAmount(asset="USDT", amount=left)
    right_amount = AssetAmount(asset="ETH", amount=right)

    with pytest.raises(ValueError):
        _ = left_amount + right_amount
    with pytest.raises(ValueError):
        _ = left_amount - right_amount


@given(decimal_amounts, decimal_amounts)
def test_usdt_and_usdc_never_combine_implicitly(left: Decimal, right: Decimal) -> None:
    left_amount = AssetAmount(asset="USDT", amount=left)
    right_amount = AssetAmount(asset="USDC", amount=right)

    with pytest.raises(ValueError):
        _ = left_amount + right_amount


@given(signed_decimal_amounts)
def test_adding_zero_delta_preserves_value(amount: Decimal) -> None:
    value = AssetDelta(asset="USDT", amount=amount)

    assert value + AssetDelta.zero("USDT") == value


@given(signed_decimal_amounts, signed_decimal_amounts)
def test_same_asset_delta_addition_is_commutative(left: Decimal, right: Decimal) -> None:
    left_delta = AssetDelta(asset="USDC", amount=left)
    right_delta = AssetDelta(asset="USDC", amount=right)

    assert left_delta + right_delta == right_delta + left_delta


@given(signed_decimal_amounts, signed_decimal_amounts)
def test_cross_asset_delta_operations_reject(left: Decimal, right: Decimal) -> None:
    left_delta = AssetDelta(asset="USDT", amount=left)
    right_delta = AssetDelta(asset="USDC", amount=right)

    with pytest.raises(ValueError):
        _ = left_delta + right_delta
    with pytest.raises(ValueError):
        _ = left_delta - right_delta
