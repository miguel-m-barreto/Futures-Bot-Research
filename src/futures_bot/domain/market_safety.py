from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.instruments import InstrumentSymbol


class MarketSafetyBlockReason(StrEnum):
    UNSAFE_ASSET = "UNSAFE_ASSET"
    SCAM_CONFIRMED = "SCAM_CONFIRMED"
    HONEYPOT_CONFIRMED = "HONEYPOT_CONFIRMED"
    FROZEN_MARKET = "FROZEN_MARKET"
    NON_TRADABLE = "NON_TRADABLE"
    UNSUPPORTED_VENUE = "UNSUPPORTED_VENUE"
    UNSUPPORTED_INSTRUMENT = "UNSUPPORTED_INSTRUMENT"
    INVALID_SYMBOL = "INVALID_SYMBOL"
    CORRUPTED_MARKET_DATA = "CORRUPTED_MARKET_DATA"
    UNUSABLE_MARKET_DATA = "UNUSABLE_MARKET_DATA"
    MISSING_REQUIRED_METADATA = "MISSING_REQUIRED_METADATA"
    MISSING_EXECUTION_CONSTRAINTS = "MISSING_EXECUTION_CONSTRAINTS"
    IMPOSSIBLE_LIQUIDITY = "IMPOSSIBLE_LIQUIDITY"
    SIMULATION_NOT_PLAUSIBLE = "SIMULATION_NOT_PLAUSIBLE"
    EXCHANGE_NOT_ACCESSIBLE = "EXCHANGE_NOT_ACCESSIBLE"


class MarketSafetyDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: InstrumentSymbol
    allowed: bool
    block_reasons: tuple[MarketSafetyBlockReason, ...] = ()
    notes: str | None = None

    @field_validator("instrument", mode="before")
    @classmethod
    def _coerce_instrument(cls, value: object) -> InstrumentSymbol:
        return _coerce_instrument(value)

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _optional_trimmed(value, "notes")

    @model_validator(mode="after")
    def _validate_decision(self) -> Self:
        if self.allowed and self.block_reasons:
            raise ValueError("allowed market safety decision must not have block reasons")
        if not self.allowed and not self.block_reasons:
            raise ValueError("blocked market safety decision requires at least one block reason")
        if len(set(self.block_reasons)) != len(self.block_reasons):
            raise ValueError("duplicate market safety block reasons are not allowed")
        return self

    @classmethod
    def allow(cls, instrument: InstrumentSymbol | str, notes: str | None = None) -> Self:
        return cls.model_validate({"instrument": instrument, "allowed": True, "notes": notes})

    @classmethod
    def block(
        cls,
        instrument: InstrumentSymbol | str,
        reasons: tuple[MarketSafetyBlockReason, ...] | list[MarketSafetyBlockReason],
        notes: str | None = None,
    ) -> Self:
        return cls.model_validate(
            {
                "instrument": instrument,
                "allowed": False,
                "block_reasons": tuple(reasons),
                "notes": notes,
            }
        )


def _coerce_instrument(value: object) -> InstrumentSymbol:
    if isinstance(value, InstrumentSymbol):
        return value
    if isinstance(value, str):
        return InstrumentSymbol(value)
    raise ValueError("instrument must be an InstrumentSymbol or string")


def _optional_trimmed(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value
