from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.assets import (
    AssetAmount,
    AssetDelta,
    AssetSymbol,
    ConversionRateSnapshot,
    StableCollateralAsset,
    _strict_stable_collateral_input,
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


@pytest.mark.parametrize("symbol", ["USDT", "USDC"])
def test_stable_collateral_model_dump_round_trip(symbol: str) -> None:
    stable = StableCollateralAsset(symbol)

    assert StableCollateralAsset.model_validate(stable.model_dump()) == stable
    assert StableCollateralAsset.model_validate(
        {"symbol": {"value": symbol}}
    ) == stable


def test_asset_models_model_dump_round_trip_with_nested_asset_symbols() -> None:
    amount = AssetAmount(asset=StableCollateralAsset("USDT"), amount="1.0000")
    delta = AssetDelta(asset=StableCollateralAsset("USDT"), amount="-1.0000")
    rate = ConversionRateSnapshot(
        source_asset=AssetSymbol("USDT"),
        target_asset=AssetSymbol("USDC"),
        rate="1.0000",
        source="fixture",
        snapshot_id="snapshot-1",
    )

    assert AssetAmount.model_validate(amount.model_dump()) == amount
    assert AssetDelta.model_validate(delta.model_dump()) == delta
    assert ConversionRateSnapshot.model_validate(rate.model_dump()) == rate
    assert amount.asset == AssetSymbol("USDT")
    assert delta.asset == AssetSymbol("USDT")


def test_stable_collateral_rejects_tampered_nested_asset_symbol() -> None:
    bad_symbol = AssetSymbol("USDT").model_copy(update={"value": "bad!"})
    bad_stable = StableCollateralAsset("USDT").model_copy(update={"symbol": bad_symbol})

    with pytest.raises(ValidationError):
        StableCollateralAsset(bad_symbol)
    with pytest.raises(ValidationError):
        StableCollateralAsset.model_validate(bad_stable.model_dump())
    with pytest.raises(ValidationError):
        AssetAmount(asset=bad_stable, amount="1")
    with pytest.raises(ValidationError):
        AssetDelta(asset=bad_stable, amount="1")


def test_conversion_rate_snapshot_rejects_tampered_asset_symbols() -> None:
    bad_symbol = AssetSymbol("USDT").model_copy(update={"value": "bad!"})

    with pytest.raises(ValidationError):
        ConversionRateSnapshot(
            source_asset=bad_symbol,
            target_asset="USDC",
            rate="1",
            source="fixture",
            snapshot_id="snapshot-1",
        )
    with pytest.raises(ValidationError):
        ConversionRateSnapshot(
            source_asset="USDT",
            target_asset=bad_symbol,
            rate="1",
            source="fixture",
            snapshot_id="snapshot-1",
        )


@pytest.mark.parametrize(
    "value",
    (
        {"value": "usdt"},
        {"value": "bad!"},
        {"value": "USDT", "extra": "x"},
        {},
        object(),
    ),
)
def test_canonical_asset_symbol_mappings_are_strict(value: object) -> None:
    with pytest.raises(ValidationError):
        AssetAmount(asset=value, amount="1")


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


# ---------------------------------------------------------------------------
# _strict_stable_collateral_input helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("symbol", ["USDT", "USDC"])
def test_strict_stable_collateral_input_accepts_valid_wrappers(symbol: str) -> None:
    original = StableCollateralAsset(symbol)
    result = _strict_stable_collateral_input(original)
    assert str(result) == symbol
    assert isinstance(result, StableCollateralAsset)
    assert isinstance(result.symbol, AssetSymbol)


@pytest.mark.parametrize("bad_value", ["USD", "BTC", "ETH"])
def test_strict_stable_collateral_input_rejects_corrupted_symbol_to_non_stable(
    bad_value: str,
) -> None:
    bad_stable = StableCollateralAsset("USDT").model_copy(
        update={"symbol": AssetSymbol(bad_value)}
    )
    with pytest.raises(ValueError):
        _strict_stable_collateral_input(bad_stable)


def test_strict_stable_collateral_input_rejects_corrupted_nested_asset_symbol() -> None:
    bad_symbol = AssetSymbol("USDT").model_copy(update={"value": "bad!"})
    bad_stable = StableCollateralAsset("USDT").model_copy(update={"symbol": bad_symbol})
    with pytest.raises(ValueError):
        _strict_stable_collateral_input(bad_stable)


def test_strict_stable_collateral_input_rejects_raw_string_nested_state() -> None:
    bad_stable = StableCollateralAsset("USDT").model_copy(update={"symbol": "USDT"})
    with pytest.raises(ValueError, match="corrupted symbol"):
        _strict_stable_collateral_input(bad_stable)


def test_strict_stable_collateral_input_rejects_mapping_nested_state() -> None:
    bad_stable = StableCollateralAsset("USDT").model_copy(
        update={"symbol": {"value": "USDT"}}
    )
    with pytest.raises(ValueError, match="corrupted symbol"):
        _strict_stable_collateral_input(bad_stable)


# ---------------------------------------------------------------------------
# Corrupted StableCollateralAsset wrappers rejected by accounting models
# ---------------------------------------------------------------------------


def _make_corrupted_wrappers() -> list[StableCollateralAsset]:
    return [
        StableCollateralAsset("USDT").model_copy(
            update={"symbol": AssetSymbol("USD")}
        ),
        StableCollateralAsset("USDT").model_copy(
            update={"symbol": AssetSymbol("BTC")}
        ),
        StableCollateralAsset("USDT").model_copy(
            update={
                "symbol": AssetSymbol("USDT").model_copy(update={"value": "bad!"})
            }
        ),
        StableCollateralAsset("USDT").model_copy(update={"symbol": "USDT"}),
        StableCollateralAsset("USDT").model_copy(
            update={"symbol": {"value": "USDT"}}
        ),
    ]


def test_corrupted_stable_collateral_wrapper_rejected_by_asset_amount() -> None:
    for bad_stable in _make_corrupted_wrappers():
        with pytest.raises(ValidationError):
            AssetAmount(asset=bad_stable, amount="1")


def test_corrupted_stable_collateral_wrapper_rejected_by_asset_delta() -> None:
    for bad_stable in _make_corrupted_wrappers():
        with pytest.raises(ValidationError):
            AssetDelta(asset=bad_stable, amount="1")


def test_corrupted_stable_collateral_wrapper_rejected_by_conversion_rate_snapshot_source() -> None:
    for bad_stable in _make_corrupted_wrappers():
        with pytest.raises(ValidationError):
            ConversionRateSnapshot(
                source_asset=bad_stable,
                target_asset=AssetSymbol("USDC"),
                rate="1",
                source="fixture",
                snapshot_id="snapshot-1",
            )


def test_corrupted_stable_collateral_wrapper_rejected_by_conversion_rate_snapshot_target() -> None:
    for bad_stable in _make_corrupted_wrappers():
        with pytest.raises(ValidationError):
            ConversionRateSnapshot(
                source_asset=AssetSymbol("USDT"),
                target_asset=bad_stable,
                rate="1",
                source="fixture",
                snapshot_id="snapshot-1",
            )
