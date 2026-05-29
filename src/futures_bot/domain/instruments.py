from __future__ import annotations

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
        instrument = (
            instrument_value
            if isinstance(instrument_value, InstrumentSymbol)
            else InstrumentSymbol(str(instrument_value))
        )
        updated = dict(data)
        updated.setdefault("base_asset", instrument.base_asset)
        updated.setdefault("quote_asset", instrument.quote_asset)
        return updated

    @field_validator("instrument", mode="before")
    @classmethod
    def _coerce_instrument(cls, value: object) -> InstrumentSymbol:
        if isinstance(value, InstrumentSymbol):
            return value
        if isinstance(value, str):
            return InstrumentSymbol(value)
        raise ValueError("instrument must be an InstrumentSymbol or string")

    @field_validator("base_asset", "quote_asset", mode="before")
    @classmethod
    def _coerce_asset(cls, value: object) -> AssetSymbol | None:
        if value is None or isinstance(value, AssetSymbol):
            return value
        if isinstance(value, str):
            return AssetSymbol(value)
        raise ValueError("asset must be an AssetSymbol or string")

    @model_validator(mode="after")
    def _validate_assets(self) -> InstrumentMetadata:
        if self.base_asset != self.instrument.base_asset:
            raise ValueError("base_asset must match instrument base")
        if self.quote_asset != self.instrument.quote_asset:
            raise ValueError("quote_asset must match instrument quote")
        return self
