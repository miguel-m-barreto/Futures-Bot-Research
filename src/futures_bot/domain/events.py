from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from futures_bot.domain.ids import BotId, CohortId, EventId, ExperimentId
from futures_bot.domain.time import ensure_aware_utc


class EventType(StrEnum):
    BOT_CREATED = "BOT_CREATED"
    BUCKET_CREATED = "BUCKET_CREATED"
    DECISION_INTENT_CREATED = "DECISION_INTENT_CREATED"
    NO_TRADE_DECISION_CREATED = "NO_TRADE_DECISION_CREATED"
    RISK_GATE_APPROVED = "RISK_GATE_APPROVED"
    RISK_GATE_REJECTED = "RISK_GATE_REJECTED"
    PAPER_POSITION_OPENED = "PAPER_POSITION_OPENED"
    PAPER_POSITION_CLOSED = "PAPER_POSITION_CLOSED"
    LEDGER_MUTATION_APPLIED = "LEDGER_MUTATION_APPLIED"
    COUNTERFACTUAL_EVALUATED = "COUNTERFACTUAL_EVALUATED"


class EventEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: EventId
    event_type: EventType
    occurred_at: datetime
    bot_id: BotId | None = None
    experiment_id: ExperimentId | None = None
    cohort_id: CohortId | None = None
    local_sequence: int | None = None
    schema_version: str
    payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("schema_version must be a non-empty trimmed string")
        return value

    @field_validator("local_sequence")
    @classmethod
    def _validate_local_sequence(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("local_sequence must be >= 0")
        return value
