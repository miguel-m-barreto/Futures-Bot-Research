import pytest
from pydantic import ValidationError

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.instruments import (
    InstrumentMetadata,
    InstrumentSymbol,
    VenueId,
    normalize_instrument_symbol,
)
from futures_bot.domain.replay import ReplayInstrumentRef


@pytest.mark.parametrize("symbol", ["BTC/USDT", "ETH/USDT", "SOL/USDC", "BTC/USD"])
def test_valid_logical_instrument_symbols(symbol: str) -> None:
    instrument = InstrumentSymbol(symbol)

    assert str(instrument) == symbol
    assert isinstance(instrument.base_asset, AssetSymbol)
    assert isinstance(instrument.quote_asset, AssetSymbol)


@pytest.mark.parametrize("symbol", ["bnb/usdt", "BTCUSDT", "BTC/USDT/PERP", "/USDT", "BTC/"])
def test_invalid_logical_instrument_symbols(symbol: str) -> None:
    with pytest.raises(ValidationError):
        InstrumentSymbol(symbol)


def test_instrument_metadata_defaults_assets_from_symbol() -> None:
    metadata = InstrumentMetadata(instrument="BTC/USDT")

    assert metadata.base_asset == AssetSymbol("BTC")
    assert metadata.quote_asset == AssetSymbol("USDT")


@pytest.mark.parametrize(
    "raw",
    ["BTC/USD", "BTCUSD", "btc/usd", "btc-usd", "BTC_USD", " BTCUSD "],
)
def test_normalize_instrument_symbol_common_external_spellings(raw: str) -> None:
    assert normalize_instrument_symbol(raw) == InstrumentSymbol("BTC/USD")


def test_normalize_instrument_symbol_preserves_distinct_quotes() -> None:
    assert normalize_instrument_symbol("BTCUSD") == InstrumentSymbol("BTC/USD")
    assert normalize_instrument_symbol("BTCUSDT") == InstrumentSymbol("BTC/USDT")
    assert normalize_instrument_symbol("BTCUSDC") == InstrumentSymbol("BTC/USDC")


def test_normalize_instrument_symbol_custom_quotes_and_duplicates() -> None:
    assert normalize_instrument_symbol(
        "ETHBTC",
        known_quote_assets=("BTC", AssetSymbol("BTC"), "USDT"),
    ) == InstrumentSymbol("ETH/BTC")


def test_normalize_instrument_symbol_revalidates_existing_symbol() -> None:
    symbol = InstrumentSymbol("BTC/USD")

    assert normalize_instrument_symbol(symbol) == symbol


@pytest.mark.parametrize(
    "raw",
    [
        "BTCETH",
        "B/USD",
        "BTC/U",
        "BTC//USD",
        "BTC/USD/USDT",
        "BTC-USD_USDT",
        "BTCUSD_PERP",
        "BTC-USD-SWAP",
    ],
)
def test_normalize_instrument_symbol_rejects_malformed_external_spellings(
    raw: str,
) -> None:
    with pytest.raises(ValueError):
        normalize_instrument_symbol(raw)


def test_normalize_instrument_symbol_does_not_convert_aliases() -> None:
    assert normalize_instrument_symbol("XBTUSD") == InstrumentSymbol("XBT/USD")


@pytest.mark.parametrize(
    "raw",
    ["btc\u00dfusd", "btc\u017fusd", "\uff22\uff34\uff23USD", "BTC\u20acUSD"],
)
def test_normalize_instrument_symbol_rejects_non_ascii_before_upper(raw: str) -> None:
    with pytest.raises(ValueError, match="ASCII"):
        normalize_instrument_symbol(raw)


def test_normalize_instrument_symbol_rejects_non_ascii_known_quote_asset() -> None:
    with pytest.raises(ValueError, match="ASCII"):
        normalize_instrument_symbol("BTCUSD", known_quote_assets=("usd", "u\u017fd"))


def test_normalize_instrument_symbol_accepts_only_canonical_serialized_mapping() -> None:
    assert normalize_instrument_symbol({"value": "BTC/USD"}) == InstrumentSymbol("BTC/USD")

    for bad in (
        {"value": "BTCUSD"},
        {"value": "btc/usd"},
        {"value": "BTC/USD", "extra": "x"},
    ):
        with pytest.raises(ValueError):
            normalize_instrument_symbol(bad)


def test_instrument_metadata_canonicalizes_external_symbol_input() -> None:
    metadata = InstrumentMetadata(instrument="btcusd")

    assert metadata.instrument == InstrumentSymbol("BTC/USD")
    assert metadata.base_asset == AssetSymbol("BTC")
    assert metadata.quote_asset == AssetSymbol("USD")


def test_instrument_metadata_model_dump_round_trip_and_serialized_assets() -> None:
    metadata = InstrumentMetadata(
        instrument="BTCUSD",
        venue=VenueId(value="binance"),
    )

    revalidated = InstrumentMetadata.model_validate(metadata.model_dump())

    assert revalidated == metadata
    assert InstrumentMetadata(
        instrument={"value": "BTC/USD"},
        base_asset={"value": "BTC"},
        quote_asset={"value": "USD"},
    ) == InstrumentMetadata(instrument="BTC/USD")


@pytest.mark.parametrize(
    "payload",
    (
        {"instrument": {"value": "BTCUSD"}},
        {"instrument": {"value": "btc/usd"}},
        {"instrument": {"value": "BTC/USD", "extra": "x"}},
        {
            "instrument": {"value": "BTC/USD"},
            "base_asset": {"value": "btc"},
            "quote_asset": {"value": "USD"},
        },
        {
            "instrument": {"value": "BTC/USD"},
            "base_asset": {"value": "BTC", "extra": "x"},
            "quote_asset": {"value": "USD"},
        },
    ),
)
def test_instrument_metadata_rejects_tampered_serialized_nested_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        InstrumentMetadata.model_validate(payload)


def test_replay_instrument_ref_keeps_raw_exchange_symbol() -> None:
    ref = ReplayInstrumentRef(
        venue="binance",
        symbol="BTCUSDT",
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
    )

    assert ref.symbol == "BTCUSDT"


def test_instrument_metadata_rejects_mismatched_assets() -> None:
    with pytest.raises(ValidationError, match="base_asset"):
        InstrumentMetadata(instrument="BTC/USDT", base_asset="ETH")


def test_instrument_symbol_non_string_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        InstrumentSymbol(123)  # type: ignore[arg-type]


def test_instrument_metadata_non_string_instrument_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        InstrumentMetadata(instrument=123)  # type: ignore[arg-type]


def test_instrument_metadata_invalid_asset_type_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        InstrumentMetadata(instrument="BTC/USDT", base_asset=object())  # type: ignore[arg-type]
