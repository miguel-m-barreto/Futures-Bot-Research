import pytest
from pydantic import ValidationError

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.instruments import InstrumentMetadata, InstrumentSymbol


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
