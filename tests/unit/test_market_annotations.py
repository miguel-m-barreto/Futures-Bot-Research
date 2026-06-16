from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.market_annotations import (
    MarketAnnotation,
    MarketAnnotationKind,
    MarketAnnotationSet,
)


def test_market_annotation_confidence_accepts_decimal_string_and_int() -> None:
    assert MarketAnnotation(
        instrument="BTC/USDT",
        kind=MarketAnnotationKind.HIGH_VOLATILITY,
        source="scanner",
        confidence=Decimal("0.25"),
    ).confidence == Decimal("0.25")
    assert MarketAnnotation(
        instrument="BTC/USDT",
        kind=MarketAnnotationKind.HIGH_VOLATILITY,
        source="scanner",
        confidence="0.5",
    ).confidence == Decimal("0.5")
    assert MarketAnnotation(
        instrument="BTC/USDT",
        kind=MarketAnnotationKind.HIGH_VOLATILITY,
        source="scanner",
        confidence=1,
    ).confidence == Decimal("1")


@pytest.mark.parametrize("confidence", [0.5, True, "-0.1", "1.1"])
def test_market_annotation_confidence_rejects_invalid_values(confidence: object) -> None:
    with pytest.raises(ValidationError):
        MarketAnnotation(
            instrument="BTC/USDT",
            kind=MarketAnnotationKind.HIGH_VOLATILITY,
            source="scanner",
            confidence=confidence,
        )


@pytest.mark.parametrize("bad", ["abc", "", "not-a-number"])
def test_market_annotation_confidence_invalid_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        MarketAnnotation(
            instrument="BTC/USDT",
            kind=MarketAnnotationKind.HIGH_VOLATILITY,
            source="scanner",
            confidence=bad,
        )


@pytest.mark.parametrize("bad", [" 0.5", "0.5 ", " 0.5 "])
def test_market_annotation_confidence_whitespace_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        MarketAnnotation(
            instrument="BTC/USDT",
            kind=MarketAnnotationKind.HIGH_VOLATILITY,
            source="scanner",
            confidence=bad,
        )


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_market_annotation_confidence_non_finite_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        MarketAnnotation(
            instrument="BTC/USDT",
            kind=MarketAnnotationKind.HIGH_VOLATILITY,
            source="scanner",
            confidence=bad,
        )


def test_market_annotation_source_and_notes_must_be_trimmed() -> None:
    with pytest.raises(ValidationError, match="source"):
        MarketAnnotation(
            instrument="BTC/USDT",
            kind=MarketAnnotationKind.DATA_LIMITED,
            source=" scanner ",
        )
    with pytest.raises(ValidationError, match="notes"):
        MarketAnnotation(
            instrument="BTC/USDT",
            kind=MarketAnnotationKind.DATA_LIMITED,
            source="scanner",
            notes=" bad ",
        )


def test_market_annotation_invalid_instrument_type_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        MarketAnnotation(
            instrument=123,  # type: ignore[arg-type]
            kind=MarketAnnotationKind.HIGH_VOLATILITY,
            source="scanner",
        )
    with pytest.raises(ValidationError):
        MarketAnnotationSet(instrument=123)  # type: ignore[arg-type]


def test_market_annotation_set_rejects_mismatched_instruments_and_duplicates() -> None:
    annotation = MarketAnnotation(
        instrument="BTC/USDT",
        kind=MarketAnnotationKind.LOW_MARKET_CAP,
        source="scanner",
    )

    with pytest.raises(ValidationError, match="must match"):
        MarketAnnotationSet(instrument="ETH/USDT", annotations=(annotation,))

    with pytest.raises(ValidationError, match="duplicate"):
        MarketAnnotationSet(instrument="BTC/USDT", annotations=(annotation, annotation))


def test_market_annotations_normalize_alternate_external_spellings() -> None:
    annotation = MarketAnnotation(
        instrument="BTC/USD",
        kind=MarketAnnotationKind.LOW_MARKET_CAP,
        source="scanner",
    )
    annotations = MarketAnnotationSet(instrument="BTCUSD", annotations=(annotation,))

    assert annotations.instrument == annotation.instrument
    assert str(annotations.instrument) == "BTC/USD"


def test_market_annotation_set_lookup_methods() -> None:
    volatility = MarketAnnotation(
        instrument="BTC/USDT",
        kind=MarketAnnotationKind.HIGH_VOLATILITY,
        source="scanner",
    )
    rsi = MarketAnnotation(
        instrument="BTC/USDT",
        kind=MarketAnnotationKind.RSI_OVERBOUGHT,
        source="indicator",
    )
    annotations = MarketAnnotationSet(instrument="BTC/USDT", annotations=(volatility, rsi))

    assert annotations.has(MarketAnnotationKind.HIGH_VOLATILITY)
    assert annotations.kinds() == frozenset(
        {MarketAnnotationKind.HIGH_VOLATILITY, MarketAnnotationKind.RSI_OVERBOUGHT},
    )
    assert annotations.by_kind(MarketAnnotationKind.RSI_OVERBOUGHT) == (rsi,)


def test_market_annotation_models_model_dump_round_trip_and_tampering() -> None:
    annotation = MarketAnnotation(
        instrument="BTCUSD",
        kind=MarketAnnotationKind.HIGH_VOLATILITY,
        source="scanner",
    )
    annotations = MarketAnnotationSet(instrument="BTC/USD", annotations=(annotation,))

    assert MarketAnnotation.model_validate(annotation.model_dump()) == annotation
    assert MarketAnnotationSet.model_validate(annotations.model_dump()) == annotations

    tampered = annotation.model_copy(update={"instrument": {"value": "BTCUSD"}})
    with pytest.raises(ValidationError):
        MarketAnnotationSet(instrument="BTC/USD", annotations=(tampered,))
