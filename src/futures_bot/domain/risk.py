from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.assets import AssetAmount
from futures_bot.domain.ids import DecisionIntentId


class RiskBehaviorSourceKind(StrEnum):
    FIXED_POLICY = "FIXED_POLICY"
    STATISTICAL_MODEL = "STATISTICAL_MODEL"
    ML_MODEL = "ML_MODEL"
    NEURAL_MODEL = "NEURAL_MODEL"
    RL_POLICY = "RL_POLICY"
    LLM_ASSISTED = "LLM_ASSISTED"
    HYBRID = "HYBRID"
    MANUAL_RESEARCH = "MANUAL_RESEARCH"


class RiskBehaviorProposal(BaseModel):
    """Strategic, possibly learned/adaptive risk behavior proposal.

    This may propose risk behavior. It is not the HardRiskGate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_intent_id: DecisionIntentId
    source_kind: RiskBehaviorSourceKind
    source_id: str
    proposed_margin: AssetAmount | None = None
    proposed_leverage: Decimal | None = None
    confidence: Decimal | None = None
    notes: str | None = None

    @field_validator("source_id")
    @classmethod
    def _validate_source_id(cls, value: str) -> str:
        return _trimmed(value, "source_id")

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

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _optional_trimmed(value, "notes")


class HardRiskGateRejectReason(StrEnum):
    INVALID_DECISION_INTENT = "INVALID_DECISION_INTENT"
    UNSAFE_INSTRUMENT = "UNSAFE_INSTRUMENT"
    INSTRUMENT_NOT_TRADABLE = "INSTRUMENT_NOT_TRADABLE"
    INSUFFICIENT_CAPITAL = "INSUFFICIENT_CAPITAL"
    INVALID_MARGIN = "INVALID_MARGIN"
    INVALID_LEVERAGE = "INVALID_LEVERAGE"
    EXCHANGE_CONSTRAINT_VIOLATION = "EXCHANGE_CONSTRAINT_VIOLATION"
    ACCOUNTING_INVARIANT_VIOLATION = "ACCOUNTING_INVARIANT_VIOLATION"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    EXECUTION_NOT_PLAUSIBLE = "EXECUTION_NOT_PLAUSIBLE"
    OPERATIONAL_MODE_FORBIDS_EXECUTION = "OPERATIONAL_MODE_FORBIDS_EXECUTION"


class HardRiskGateOutcome(StrEnum):
    APPROVED = "APPROVED"
    APPROVED_WITH_REDUCED_MARGIN = "APPROVED_WITH_REDUCED_MARGIN"
    APPROVED_WITH_REDUCED_LEVERAGE = "APPROVED_WITH_REDUCED_LEVERAGE"
    REJECTED = "REJECTED"


class HardRiskGateDecision(BaseModel):
    """Hard validity decision; validates reality, not alpha or strategy quality."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_intent_id: DecisionIntentId
    outcome: HardRiskGateOutcome
    reject_reasons: tuple[HardRiskGateRejectReason, ...] = ()
    approved_margin: AssetAmount | None = None
    approved_leverage: Decimal | None = None
    notes: str | None = None

    @field_validator("approved_leverage", mode="before")
    @classmethod
    def _coerce_leverage(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return _coerce_decimal(value)

    @field_validator("approved_leverage")
    @classmethod
    def _validate_leverage(cls, value: Decimal | None) -> Decimal | None:
        return _optional_positive_decimal(value, "approved_leverage")

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _optional_trimmed(value, "notes")

    @model_validator(mode="after")
    def _validate_outcome(self) -> Self:
        if len(set(self.reject_reasons)) != len(self.reject_reasons):
            raise ValueError("duplicate hard risk reject reasons are not allowed")
        if self.outcome is HardRiskGateOutcome.REJECTED and not self.reject_reasons:
            raise ValueError("rejected HardRiskGateDecision requires reject reasons")
        if self.outcome is not HardRiskGateOutcome.REJECTED and self.reject_reasons:
            raise ValueError("approved HardRiskGateDecision must not have reject reasons")
        return self


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


def _optional_positive_decimal(value: Decimal | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value
