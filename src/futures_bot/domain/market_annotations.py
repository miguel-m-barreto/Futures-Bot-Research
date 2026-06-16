from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.instruments import InstrumentSymbol, normalize_instrument_symbol


class MarketAnnotationKind(StrEnum):
    LOW_VOLUME = "LOW_VOLUME"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    HIGH_SPREAD = "HIGH_SPREAD"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_MARKET_CAP = "LOW_MARKET_CAP"
    RECENT_LISTING = "RECENT_LISTING"
    SHITCOIN_LIKE_PROFILE = "SHITCOIN_LIKE_PROFILE"
    HIGH_DAILY_SWING_PROFILE = "HIGH_DAILY_SWING_PROFILE"
    POSSIBLE_MANIPULATION_RISK = "POSSIBLE_MANIPULATION_RISK"
    FUNDING_UNFAVORABLE = "FUNDING_UNFAVORABLE"
    SHORT_HISTORY = "SHORT_HISTORY"
    RSI_OVERBOUGHT = "RSI_OVERBOUGHT"
    RSI_OVERSOLD = "RSI_OVERSOLD"
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    CHOPPY_MARKET = "CHOPPY_MARKET"
    REGIME_UNKNOWN = "REGIME_UNKNOWN"
    DATA_LIMITED = "DATA_LIMITED"


class MarketAnnotation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: InstrumentSymbol
    kind: MarketAnnotationKind
    source: str
    confidence: Decimal | None = None
    notes: str | None = None

    @field_validator("instrument", mode="before")
    @classmethod
    def _coerce_instrument(cls, value: object) -> InstrumentSymbol:
        return _coerce_instrument(value)

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: str) -> str:
        return _trimmed(value, "source")

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return _coerce_decimal(value)

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: Decimal | None) -> Decimal | None:
        return _optional_probability(value, "confidence")

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _optional_trimmed(value, "notes")


class MarketAnnotationSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: InstrumentSymbol
    annotations: tuple[MarketAnnotation, ...] = ()

    @field_validator("instrument", mode="before")
    @classmethod
    def _coerce_instrument(cls, value: object) -> InstrumentSymbol:
        return _coerce_instrument(value)

    @field_validator("annotations", mode="before")
    @classmethod
    def _revalidate_annotations(cls, value: object) -> tuple[MarketAnnotation, ...]:
        if value is None:
            return ()
        if not isinstance(value, tuple | list):
            raise ValueError("annotations must be a tuple or list")
        return tuple(
            MarketAnnotation.model_validate(
                item.model_dump() if isinstance(item, MarketAnnotation) else item
            )
            for item in value
        )

    @model_validator(mode="after")
    def _validate_annotations(self) -> Self:
        seen: set[tuple[MarketAnnotationKind, str]] = set()
        for annotation in self.annotations:
            if annotation.instrument != self.instrument:
                raise ValueError("annotation instrument must match annotation set instrument")
            key = (annotation.kind, annotation.source)
            if key in seen:
                raise ValueError("duplicate annotation kind/source is not allowed")
            seen.add(key)
        return self

    def has(self, kind: MarketAnnotationKind) -> bool:
        return any(annotation.kind is kind for annotation in self.annotations)

    def kinds(self) -> frozenset[MarketAnnotationKind]:
        return frozenset(annotation.kind for annotation in self.annotations)

    def by_kind(self, kind: MarketAnnotationKind) -> tuple[MarketAnnotation, ...]:
        return tuple(annotation for annotation in self.annotations if annotation.kind is kind)


def _coerce_instrument(value: object) -> InstrumentSymbol:
    if not isinstance(value, str | InstrumentSymbol | Mapping):
        raise ValueError(
            "instrument must be an InstrumentSymbol, string, or serialized mapping"
        )
    return normalize_instrument_symbol(value)


def _trimmed(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value


def _optional_trimmed(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _trimmed(value, field_name)


def _coerce_decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("decimal value must not be bool")
    if isinstance(value, float):
        raise ValueError("float input is prohibited")
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, str):
        if value != value.strip():
            raise ValueError("decimal string must not have leading or trailing whitespace")
        try:
            decimal_value = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"decimal string is not a valid number: {value!r}") from exc
    else:
        raise ValueError("decimal value must be Decimal, int, or string")
    if not decimal_value.is_finite():
        raise ValueError("decimal value must be finite")
    return decimal_value


def _optional_probability(value: Decimal | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if value < 0 or value > 1:
        raise ValueError(f"{field_name} must be between 0 and 1 inclusive")
    return value
