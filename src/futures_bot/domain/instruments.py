from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.assets import AssetSymbol


class InstrumentSymbol(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str

    def __init__(self, value: str | None = None, **data: Any) -> None:
        if value is not None:
            if data:
                raise TypeError("pass either a positional value or keyword fields, not both")
            data = {"value": value}
        super().__init__(**data)

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("instrument symbol must be a string")
        if value.count("/") != 1:
            raise ValueError("instrument symbol must use logical BASE/QUOTE format")
        base, quote = value.split("/")
        AssetSymbol(base)
        AssetSymbol(quote)
        return value

    @property
    def base_asset(self) -> AssetSymbol:
        return AssetSymbol(self.value.split("/")[0])

    @property
    def quote_asset(self) -> AssetSymbol:
        return AssetSymbol(self.value.split("/")[1])

    @classmethod
    def from_str(cls, value: str) -> Self:
        return cls(value)

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"InstrumentSymbol({self.value!r})"


def normalize_instrument_symbol(
    value: str | InstrumentSymbol | Mapping[str, object],
    *,
    known_quote_assets: tuple[str | AssetSymbol, ...] = ("USDT", "USDC", "USD"),
) -> InstrumentSymbol:
    """Normalize common external pair spellings into logical BASE/QUOTE format.

    This establishes only the logical asset pair. Tradable instrument identity can
    still differ by venue, kind, settlement/collateral asset, contract type, or
    exchange instrument identifier.
    """
    if isinstance(value, InstrumentSymbol):
        return InstrumentSymbol.model_validate(value.model_dump())
    if isinstance(value, Mapping):
        if set(value) != {"value"}:
            raise ValueError(
                "serialized instrument symbol must contain only the 'value' field"
            )
        return InstrumentSymbol.model_validate(dict(value))
    if not isinstance(value, str):
        raise ValueError(
            "instrument symbol input must be a string, InstrumentSymbol, "
            "or serialized mapping"
        )
    stripped = value.strip()
    if not stripped:
        raise ValueError("instrument symbol input must be non-empty")
    if not stripped.isascii():
        raise ValueError("instrument symbol input must contain ASCII characters only")
    normalized = stripped.upper()
    quote_assets = _normalize_known_quote_assets(known_quote_assets)
    if "/" in normalized:
        return _normalize_slash_instrument_symbol(normalized)
    if "-" in normalized or "_" in normalized:
        return _normalize_separated_instrument_symbol(normalized, quote_assets)
    return _normalize_compact_instrument_symbol(normalized, quote_assets)


class VenueId(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("venue id must be a non-empty trimmed string")
        return value


class InstrumentKind(StrEnum):
    SPOT = "SPOT"
    STABLECOIN_COLLATERAL_FUTURE = "STABLECOIN_COLLATERAL_FUTURE"
    RESEARCH_ONLY = "RESEARCH_ONLY"


class InstrumentMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: InstrumentSymbol
    base_asset: AssetSymbol | None = None
    quote_asset: AssetSymbol | None = None
    kind: InstrumentKind | None = None
    venue: VenueId | None = None
    metadata_version: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_assets_from_instrument(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        instrument_value = data.get("instrument")
        if instrument_value is None:
            return data
        if not isinstance(instrument_value, str | InstrumentSymbol | Mapping):
            raise ValueError(
                "instrument must be an InstrumentSymbol, string, or serialized mapping"
            )
        instrument = normalize_instrument_symbol(instrument_value)
        updated = dict(data)
        updated.setdefault("base_asset", instrument.base_asset)
        updated.setdefault("quote_asset", instrument.quote_asset)
        return updated

    @field_validator("instrument", mode="before")
    @classmethod
    def _coerce_instrument(cls, value: object) -> InstrumentSymbol:
        if not isinstance(value, str | InstrumentSymbol | Mapping):
            raise ValueError(
                "instrument must be an InstrumentSymbol, string, or serialized mapping"
            )
        return normalize_instrument_symbol(value)

    @field_validator("base_asset", "quote_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol | None:
        if value is None:
            return value
        if isinstance(value, AssetSymbol):
            return AssetSymbol.model_validate(value.model_dump())
        if isinstance(value, str):
            return AssetSymbol(value)
        if isinstance(value, Mapping):
            if set(value) != {"value"}:
                raise ValueError("serialized asset symbol must contain only value")
            return AssetSymbol.model_validate(dict(value))
        raise ValueError("asset must be an AssetSymbol, string, or serialized mapping")

    @model_validator(mode="after")
    def _validate_assets(self) -> InstrumentMetadata:
        if self.base_asset != self.instrument.base_asset:
            raise ValueError("base_asset must match instrument base")
        if self.quote_asset != self.instrument.quote_asset:
            raise ValueError("quote_asset must match instrument quote")
        return self


def _normalize_known_quote_assets(
    known_quote_assets: tuple[str | AssetSymbol, ...],
) -> tuple[AssetSymbol, ...]:
    assets: set[AssetSymbol] = set()
    for value in known_quote_assets:
        if isinstance(value, AssetSymbol):
            asset = AssetSymbol.model_validate(value.model_dump())
        elif isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("known quote asset must be non-empty")
            if not stripped.isascii():
                raise ValueError("known quote asset must contain ASCII characters only")
            asset = AssetSymbol(stripped.upper())
        else:
            raise ValueError("known quote assets must be strings or AssetSymbol values")
        assets.add(asset)
    if not assets:
        raise ValueError("known_quote_assets must be non-empty")
    return tuple(sorted(assets, key=lambda asset: (-len(str(asset)), str(asset))))


def _normalize_slash_instrument_symbol(value: str) -> InstrumentSymbol:
    if value.count("/") != 1:
        raise ValueError("slash instrument symbol must contain exactly one slash")
    base, quote = value.split("/")
    if not base or not quote:
        raise ValueError("slash instrument symbol requires non-empty base and quote")
    return InstrumentSymbol(f"{AssetSymbol(base)}/{AssetSymbol(quote)}")


def _normalize_separated_instrument_symbol(
    value: str,
    known_quote_assets: tuple[AssetSymbol, ...],
) -> InstrumentSymbol:
    has_hyphen = "-" in value
    has_underscore = "_" in value
    if has_hyphen and has_underscore:
        raise ValueError("instrument symbol must not mix hyphen and underscore")
    separator = "-" if has_hyphen else "_"
    if value.count(separator) != 1:
        raise ValueError("separated instrument symbol must contain exactly one separator")
    base, quote = value.split(separator)
    if not base or not quote:
        raise ValueError("separated instrument symbol requires non-empty base and quote")
    quote_asset = AssetSymbol(quote)
    if quote_asset not in known_quote_assets:
        raise ValueError("separated instrument symbol quote is not a known quote asset")
    return InstrumentSymbol(f"{AssetSymbol(base)}/{quote_asset}")


def _normalize_compact_instrument_symbol(
    value: str,
    known_quote_assets: tuple[AssetSymbol, ...],
) -> InstrumentSymbol:
    matches: list[tuple[AssetSymbol, AssetSymbol]] = []
    for quote in known_quote_assets:
        quote_text = str(quote)
        if not value.endswith(quote_text):
            continue
        base_text = value[: -len(quote_text)]
        if not base_text:
            continue
        try:
            base = AssetSymbol(base_text)
        except ValueError:
            continue
        matches.append((base, quote))
    if not matches:
        raise ValueError("compact instrument symbol has no valid known quote suffix")
    best_length = len(str(matches[0][1]))
    best = tuple(match for match in matches if len(str(match[1])) == best_length)
    if len(best) != 1:
        raise ValueError("compact instrument symbol has ambiguous quote suffix")
    base, quote = best[0]
    return InstrumentSymbol(f"{base}/{quote}")
