from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.ids import EvidenceId
from futures_bot.domain.instruments import InstrumentSymbol


class EvidenceSourceKind(StrEnum):
    MARKET_ANNOTATION = "MARKET_ANNOTATION"
    TECHNICAL_INDICATOR = "TECHNICAL_INDICATOR"
    STATISTICAL_MODEL = "STATISTICAL_MODEL"
    ML_MODEL = "ML_MODEL"
    NEURAL_MODEL = "NEURAL_MODEL"
    LLM = "LLM"
    RULE_BASED = "RULE_BASED"
    MANUAL_RESEARCH = "MANUAL_RESEARCH"
    HYBRID = "HYBRID"


class EvidenceDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
    NO_TRADE = "NO_TRADE"
    UNKNOWN = "UNKNOWN"


class TechnicalEvidence(BaseModel):
    """Information for a bot/DecisionStack; not an order, trade, or selected target."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: EvidenceId
    instrument: InstrumentSymbol
    source_kind: EvidenceSourceKind
    source_id: str
    direction: EvidenceDirection
    confidence: Decimal | None = None
    tags: tuple[str, ...] = ()
    notes: str | None = None

    @field_validator("instrument", mode="before")
    @classmethod
    def _coerce_instrument(cls, value: object) -> InstrumentSymbol:
        return _coerce_instrument(value)

    @field_validator("source_id")
    @classmethod
    def _validate_source_id(cls, value: str) -> str:
        return _trimmed(value, "source_id")

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

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_trimmed_tuple(value, "tags")

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _optional_trimmed(value, "notes")


class EvidenceSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: InstrumentSymbol
    evidence: tuple[TechnicalEvidence, ...] = ()

    @field_validator("instrument", mode="before")
    @classmethod
    def _coerce_instrument(cls, value: object) -> InstrumentSymbol:
        return _coerce_instrument(value)

    @model_validator(mode="after")
    def _validate_evidence(self) -> Self:
        seen: set[EvidenceId] = set()
        for item in self.evidence:
            if item.instrument != self.instrument:
                raise ValueError("evidence instrument must match evidence set instrument")
            if item.evidence_id in seen:
                raise ValueError("duplicate evidence_id is not allowed")
            seen.add(item.evidence_id)
        return self

    def has_source_kind(self, kind: EvidenceSourceKind) -> bool:
        return any(item.source_kind is kind for item in self.evidence)

    def directions(self) -> frozenset[EvidenceDirection]:
        return frozenset(item.direction for item in self.evidence)


def _coerce_instrument(value: object) -> InstrumentSymbol:
    if isinstance(value, InstrumentSymbol):
        return value
    if isinstance(value, str):
        return InstrumentSymbol(value)
    raise ValueError("instrument must be an InstrumentSymbol or string")


def _trimmed(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value


def _optional_trimmed(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _trimmed(value, field_name)


def _unique_trimmed_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_trimmed(value, field_name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must be unique")
    return normalized


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
