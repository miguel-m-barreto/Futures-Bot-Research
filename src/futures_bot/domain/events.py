from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from futures_bot.domain.assets import AssetAmount
from futures_bot.domain.execution import OrderSide, OrderType
from futures_bot.domain.ids import (
    BotId,
    CohortId,
    DecisionIntentId,
    EventId,
    ExchangeOrderId,
    ExecutionIntentId,
    ExperimentId,
    FillId,
    InstrumentId,
    OrderIntentId,
    RunId,
)
from futures_bot.domain.time import ensure_aware_utc
from futures_bot.domain.wal_offsets import WalOffset


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
    EXECUTION_INTENT_CREATED = "EXECUTION_INTENT_CREATED"
    ORDER_SUBMIT_ATTEMPTED = "ORDER_SUBMIT_ATTEMPTED"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_FILL_RECEIVED = "ORDER_FILL_RECEIVED"
    ORDER_CANCEL_REQUESTED = "ORDER_CANCEL_REQUESTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    WAL_REPLAY_STARTED = "WAL_REPLAY_STARTED"
    WAL_REPLAY_COMPLETED = "WAL_REPLAY_COMPLETED"
    RECOVERY_ADOPT_STARTED = "RECOVERY_ADOPT_STARTED"
    RECOVERY_ADOPT_COMPLETED = "RECOVERY_ADOPT_COMPLETED"
    RECOVERY_ADOPT_FAILED = "RECOVERY_ADOPT_FAILED"


class ExecutionIntentCreatedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_intent_id: ExecutionIntentId
    decision_intent_id: DecisionIntentId
    order_intent_id: OrderIntentId


class OrderSubmitAttemptedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_intent_id: ExecutionIntentId
    order_intent_id: OrderIntentId
    client_order_id: str
    instrument_id: InstrumentId
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    reduce_only: bool
    attempted_at: datetime

    @field_validator("client_order_id")
    @classmethod
    def _validate_client_order_id(cls, value: str) -> str:
        return _trimmed(value, "client_order_id")

    @field_validator("quantity", mode="before")
    @classmethod
    def _coerce_quantity(cls, value: object) -> Decimal:
        return _coerce_decimal(value)

    @field_validator("quantity")
    @classmethod
    def _validate_quantity(cls, value: Decimal) -> Decimal:
        return _positive_decimal(value, "quantity")

    @field_validator("limit_price", mode="before")
    @classmethod
    def _coerce_limit_price(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return _coerce_decimal(value)

    @field_validator("attempted_at")
    @classmethod
    def _validate_attempted_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_order_type_price(self) -> OrderSubmitAttemptedPayload:
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("MARKET order must not have limit_price")
        if self.order_type is OrderType.LIMIT:
            if self.limit_price is None:
                raise ValueError("LIMIT order requires limit_price")
            _positive_decimal(self.limit_price, "limit_price")
        return self


class OrderAcceptedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_intent_id: OrderIntentId
    exchange_order_id: ExchangeOrderId
    accepted_at: datetime

    @field_validator("accepted_at")
    @classmethod
    def _validate_accepted_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


class OrderRejectedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_intent_id: OrderIntentId
    rejected_at: datetime
    reason: str

    @field_validator("rejected_at")
    @classmethod
    def _validate_rejected_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _trimmed(value, "reason")


class OrderFillReceivedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_intent_id: OrderIntentId
    exchange_order_id: ExchangeOrderId
    fill_id: FillId
    filled_quantity: Decimal
    fill_price: Decimal
    fee: AssetAmount | None = None
    received_at: datetime

    @field_validator("filled_quantity", "fill_price", mode="before")
    @classmethod
    def _coerce_decimal_field(cls, value: object) -> Decimal:
        return _coerce_decimal(value)

    @field_validator("filled_quantity")
    @classmethod
    def _validate_filled_quantity(cls, value: Decimal) -> Decimal:
        return _positive_decimal(value, "filled_quantity")

    @field_validator("fill_price")
    @classmethod
    def _validate_fill_price(cls, value: Decimal) -> Decimal:
        return _positive_decimal(value, "fill_price")

    @field_validator("received_at")
    @classmethod
    def _validate_received_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


class OrderCancelRequestedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_intent_id: OrderIntentId
    requested_at: datetime
    reason: str | None = None

    @field_validator("requested_at")
    @classmethod
    def _validate_requested_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


class OrderCancelledPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_intent_id: OrderIntentId
    cancelled_at: datetime
    reason: str | None = None

    @field_validator("cancelled_at")
    @classmethod
    def _validate_cancelled_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


class OrderExpiredPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_intent_id: OrderIntentId
    expired_at: datetime
    reason: str | None = None

    @field_validator("expired_at")
    @classmethod
    def _validate_expired_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


class WalReplayStartedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    started_at: datetime
    from_offset: WalOffset

    @field_validator("started_at")
    @classmethod
    def _validate_started_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


class WalReplayCompletedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    completed_at: datetime
    last_replayed_offset: WalOffset | None
    records_replayed: int

    @field_validator("completed_at")
    @classmethod
    def _validate_completed_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("records_replayed")
    @classmethod
    def _validate_records_replayed(cls, value: int) -> int:
        if value < 0:
            raise ValueError("records_replayed must be >= 0")
        return value


class RecoveryAdoptStartedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    adopting_run_id: RunId
    predecessor_run_id: RunId
    started_at: datetime
    reason: str

    @field_validator("started_at")
    @classmethod
    def _validate_started_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _trimmed(value, "reason")

    @model_validator(mode="after")
    def _validate_distinct_runs(self) -> RecoveryAdoptStartedPayload:
        _ensure_distinct_runs(self.adopting_run_id, self.predecessor_run_id)
        return self


class RecoveryAdoptCompletedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    adopting_run_id: RunId
    predecessor_run_id: RunId
    completed_at: datetime
    adopted_positions_count: int
    adopted_open_orders_count: int

    @field_validator("completed_at")
    @classmethod
    def _validate_completed_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("adopted_positions_count", "adopted_open_orders_count")
    @classmethod
    def _validate_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("adoption counts must be >= 0")
        return value

    @model_validator(mode="after")
    def _validate_distinct_runs(self) -> RecoveryAdoptCompletedPayload:
        _ensure_distinct_runs(self.adopting_run_id, self.predecessor_run_id)
        return self


class RecoveryAdoptFailedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    adopting_run_id: RunId
    predecessor_run_id: RunId
    failed_at: datetime
    reason: str

    @field_validator("failed_at")
    @classmethod
    def _validate_failed_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _trimmed(value, "reason")

    @model_validator(mode="after")
    def _validate_distinct_runs(self) -> RecoveryAdoptFailedPayload:
        _ensure_distinct_runs(self.adopting_run_id, self.predecessor_run_id)
        return self


EVENT_PAYLOAD_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.EXECUTION_INTENT_CREATED: ExecutionIntentCreatedPayload,
    EventType.ORDER_SUBMIT_ATTEMPTED: OrderSubmitAttemptedPayload,
    EventType.ORDER_ACCEPTED: OrderAcceptedPayload,
    EventType.ORDER_REJECTED: OrderRejectedPayload,
    EventType.ORDER_FILL_RECEIVED: OrderFillReceivedPayload,
    EventType.ORDER_CANCEL_REQUESTED: OrderCancelRequestedPayload,
    EventType.ORDER_CANCELLED: OrderCancelledPayload,
    EventType.ORDER_EXPIRED: OrderExpiredPayload,
    EventType.WAL_REPLAY_STARTED: WalReplayStartedPayload,
    EventType.WAL_REPLAY_COMPLETED: WalReplayCompletedPayload,
    EventType.RECOVERY_ADOPT_STARTED: RecoveryAdoptStartedPayload,
    EventType.RECOVERY_ADOPT_COMPLETED: RecoveryAdoptCompletedPayload,
    EventType.RECOVERY_ADOPT_FAILED: RecoveryAdoptFailedPayload,
}


def validate_event_payload(
    event_type: EventType,
    payload: Mapping[str, object] | BaseModel | None,
) -> dict[str, object]:
    payload_model = EVENT_PAYLOAD_MODELS.get(event_type)
    if payload_model is None:
        if payload is None:
            return {}
        if isinstance(payload, BaseModel):
            return cast("dict[str, object]", payload.model_dump(mode="json"))
        return dict(payload)

    if payload is None:
        raise ValueError(f"{event_type} requires payload")

    typed_payload = (
        payload
        if isinstance(payload, payload_model)
        else payload_model.model_validate(payload)
    )
    return cast("dict[str, object]", typed_payload.model_dump(mode="json"))


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

    @model_validator(mode="before")
    @classmethod
    def _validate_payload_for_event_type(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        event_type_value = data.get("event_type")
        if event_type_value is None:
            return data

        event_type = (
            event_type_value
            if isinstance(event_type_value, EventType)
            else EventType(str(event_type_value))
        )
        payload = cast("Mapping[str, object] | BaseModel | None", data.get("payload"))
        updated = dict(data)
        updated["payload"] = validate_event_payload(event_type, payload)
        return updated

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


def _trimmed(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value


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


def _positive_decimal(value: Decimal, field_name: str) -> Decimal:
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _ensure_distinct_runs(adopting_run_id: RunId, predecessor_run_id: RunId) -> None:
    if adopting_run_id == predecessor_run_id:
        raise ValueError("adopting_run_id must differ from predecessor_run_id")
