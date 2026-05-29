from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.assets import AssetAmount
from futures_bot.domain.ids import BotId, CandidateId, DecisionIntentId
from futures_bot.domain.instruments import InstrumentSymbol
from futures_bot.domain.time import ensure_aware_utc


class TradeSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class ProposedAction(StrEnum):
    OPEN_POSITION = "OPEN_POSITION"
    CLOSE_POSITION = "CLOSE_POSITION"
    REDUCE_POSITION = "REDUCE_POSITION"
    ADJUST_RISK = "ADJUST_RISK"


class DecisionSourceKind(StrEnum):
    RULE_BASED = "RULE_BASED"
    TECHNICAL_POLICY = "TECHNICAL_POLICY"
    STATISTICAL_MODEL = "STATISTICAL_MODEL"
    ML_MODEL = "ML_MODEL"
    NEURAL_MODEL = "NEURAL_MODEL"
    LLM = "LLM"
    HYBRID = "HYBRID"
    MANUAL_RESEARCH = "MANUAL_RESEARCH"
    CONTROL_BASELINE = "CONTROL_BASELINE"


class DecisionIntentStatus(StrEnum):
    PROPOSED = "PROPOSED"
    REJECTED_BY_UNIVERSE_POLICY = "REJECTED_BY_UNIVERSE_POLICY"
    REJECTED_BY_HARD_RISK_GATE = "REJECTED_BY_HARD_RISK_GATE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    CONVERTED_TO_EXECUTION_INTENT = "CONVERTED_TO_EXECUTION_INTENT"


class DecisionIntent(BaseModel):
    """A proposed decision from a bot/DecisionStack; not an order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_intent_id: DecisionIntentId
    bot_id: BotId
    instrument: InstrumentSymbol
    side: TradeSide
    proposed_action: ProposedAction
    source_kind: DecisionSourceKind
    source_id: str
    created_at: datetime
    valid_until: datetime | None = None
    proposed_margin: AssetAmount | None = None
    proposed_leverage: Decimal | None = None
    confidence: Decimal | None = None
    reason_tags: tuple[str, ...] = ()
    status: DecisionIntentStatus = DecisionIntentStatus.PROPOSED

    @field_validator("instrument", mode="before")
    @classmethod
    def _coerce_instrument(cls, value: object) -> InstrumentSymbol:
        return _coerce_instrument(value)

    @field_validator("source_id")
    @classmethod
    def _validate_source_id(cls, value: str) -> str:
        return _trimmed(value, "source_id")

    @field_validator("created_at", "valid_until")
    @classmethod
    def _validate_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_aware_utc(value)

    @field_validator("proposed_leverage", mode="before")
    @classmethod
    def _coerce_leverage(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return _coerce_decimal(value)

    @field_validator("proposed_leverage")
    @classmethod
    def _validate_leverage(cls, value: Decimal | None) -> Decimal | None:
        return _optional_positive_decimal(value, "proposed_leverage")

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

    @field_validator("reason_tags")
    @classmethod
    def _validate_reason_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_trimmed_tuple(value, "reason_tags")

    @model_validator(mode="after")
    def _validate_valid_until(self) -> Self:
        if self.valid_until is not None and self.valid_until <= self.created_at:
            raise ValueError("valid_until must be greater than created_at")
        return self


class NoTradeReasonKind(StrEnum):
    NO_VALID_EVIDENCE = "NO_VALID_EVIDENCE"
    UNIVERSE_POLICY_NOT_ELIGIBLE = "UNIVERSE_POLICY_NOT_ELIGIBLE"
    MODEL_CONFIDENCE_LOW = "MODEL_CONFIDENCE_LOW"
    MARKET_TOO_UNCERTAIN = "MARKET_TOO_UNCERTAIN"
    COST_CONTEXT_UNFAVORABLE = "COST_CONTEXT_UNFAVORABLE"
    BOT_POLICY_SUPPRESSED = "BOT_POLICY_SUPPRESSED"
    CONTROL_BASELINE_NO_TRADE = "CONTROL_BASELINE_NO_TRADE"
    MANUAL_RESEARCH_NO_TRADE = "MANUAL_RESEARCH_NO_TRADE"


class NoTradeDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_intent_id: DecisionIntentId
    bot_id: BotId
    instrument: InstrumentSymbol | None = None
    source_kind: DecisionSourceKind
    source_id: str
    created_at: datetime
    reasons: tuple[NoTradeReasonKind, ...]
    confidence: Decimal | None = None
    notes: str | None = None

    @field_validator("instrument", mode="before")
    @classmethod
    def _coerce_optional_instrument(cls, value: object) -> InstrumentSymbol | None:
        if value is None:
            return None
        return _coerce_instrument(value)

    @field_validator("source_id")
    @classmethod
    def _validate_source_id(cls, value: str) -> str:
        return _trimmed(value, "source_id")

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("reasons")
    @classmethod
    def _validate_reasons(
        cls,
        value: tuple[NoTradeReasonKind, ...],
    ) -> tuple[NoTradeReasonKind, ...]:
        if not value:
            raise ValueError("NoTradeDecision requires at least one reason")
        if len(set(value)) != len(value):
            raise ValueError("NoTradeDecision reasons must be unique")
        return value

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


class RejectedCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: CandidateId
    bot_id: BotId
    instrument: InstrumentSymbol
    rejected_by: str
    reason: str
    created_at: datetime

    @field_validator("instrument", mode="before")
    @classmethod
    def _coerce_instrument(cls, value: object) -> InstrumentSymbol:
        return _coerce_instrument(value)

    @field_validator("rejected_by", "reason")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _trimmed(value, "text")

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


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


def _optional_positive_decimal(value: Decimal | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value
