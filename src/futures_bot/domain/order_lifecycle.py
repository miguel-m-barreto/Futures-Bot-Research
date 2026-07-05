from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from math import isfinite
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.ids import (
    CancelOrderIntentId,
    ClientOrderId,
    DecisionStackRuntimeId,
    ExecutionOrderRecordId,
    ExecutionReadinessProofId,
    ExecutionReconciliationId,
    FillReportId,
    OrderIdempotencyKey,
    OrderIntentId,
    OrderLifecycleEventId,
    ReplaceOrderIntentId,
    VenueOrderId,
)
from futures_bot.domain.runtime_control import OrderFlowPermissionReason, RuntimeDataScopeKind
from futures_bot.domain.time import ensure_aware_utc


class OrderIntentKind(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    REDUCE_ONLY = "REDUCE_ONLY"
    PROTECTIVE_STOP = "PROTECTIVE_STOP"
    PROTECTIVE_TAKE_PROFIT = "PROTECTIVE_TAKE_PROFIT"
    EMERGENCY_CLOSE = "EMERGENCY_CLOSE"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class PositionSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    BOTH = "BOTH"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    STOP_LIMIT = "STOP_LIMIT"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    GTD = "GTD"


class CancelScope(StrEnum):
    SINGLE_ORDER = "SINGLE_ORDER"
    ALL_ENTRY_ORDERS_FOR_STACK = "ALL_ENTRY_ORDERS_FOR_STACK"
    ALL_ORDERS_FOR_INSTRUMENT = "ALL_ORDERS_FOR_INSTRUMENT"
    ALL_ORDERS_FOR_VENUE = "ALL_ORDERS_FOR_VENUE"
    ALL_ORDERS_FOR_ACCOUNT = "ALL_ORDERS_FOR_ACCOUNT"


class OrderLifecycleState(StrEnum):
    CREATED = "CREATED"
    ACCEPTED_BY_EXECUTION = "ACCEPTED_BY_EXECUTION"
    REJECTED_BY_PERMISSION = "REJECTED_BY_PERMISSION"
    REJECTED_BY_VALIDATION = "REJECTED_BY_VALIDATION"
    SUBMISSION_REQUESTED = "SUBMISSION_REQUESTED"
    SUBMITTED_TO_VENUE = "SUBMITTED_TO_VENUE"
    ACKNOWLEDGED_BY_VENUE = "ACKNOWLEDGED_BY_VENUE"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCEL_ACKNOWLEDGED = "CANCEL_ACKNOWLEDGED"
    CANCELED = "CANCELED"
    REPLACE_REQUESTED = "REPLACE_REQUESTED"
    REPLACED = "REPLACED"
    EXPIRED = "EXPIRED"
    VENUE_REJECTED = "VENUE_REJECTED"
    UNKNOWN_ON_VENUE = "UNKNOWN_ON_VENUE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    CLOSED = "CLOSED"


class OrderLifecycleEventKind(StrEnum):
    INTENT_CREATED = "INTENT_CREATED"
    ACCEPTED_BY_EXECUTION = "ACCEPTED_BY_EXECUTION"
    REJECTED_BY_PERMISSION = "REJECTED_BY_PERMISSION"
    REJECTED_BY_VALIDATION = "REJECTED_BY_VALIDATION"
    SUBMISSION_REQUESTED = "SUBMISSION_REQUESTED"
    SUBMITTED_TO_VENUE = "SUBMITTED_TO_VENUE"
    ACKNOWLEDGED_BY_VENUE = "ACKNOWLEDGED_BY_VENUE"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCEL_ACKNOWLEDGED = "CANCEL_ACKNOWLEDGED"
    CANCELED = "CANCELED"
    REPLACE_REQUESTED = "REPLACE_REQUESTED"
    REPLACED = "REPLACED"
    EXPIRED = "EXPIRED"
    VENUE_REJECTED = "VENUE_REJECTED"
    UNKNOWN_ON_VENUE = "UNKNOWN_ON_VENUE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    CLOSED = "CLOSED"


class ReconciliationReason(StrEnum):
    UNKNOWN_ON_VENUE = "UNKNOWN_ON_VENUE"
    MISSING_ACK = "MISSING_ACK"
    MISSING_CANCEL_ACK = "MISSING_CANCEL_ACK"
    UNKNOWN_FILL_STATE = "UNKNOWN_FILL_STATE"
    VENUE_ORDER_NOT_FOUND = "VENUE_ORDER_NOT_FOUND"
    LOCAL_REMOTE_STATE_MISMATCH = "LOCAL_REMOTE_STATE_MISMATCH"
    RUNTIME_RESTART_WITH_OPEN_ORDERS = "RUNTIME_RESTART_WITH_OPEN_ORDERS"
    DATA_GAP_WITH_OPEN_EXPOSURE = "DATA_GAP_WITH_OPEN_EXPOSURE"


class OrderIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_id: OrderIntentId | None = None
    idempotency_key: OrderIdempotencyKey | None = None
    client_order_id: ClientOrderId | None = None
    intent_kind: OrderIntentKind
    stack_runtime_id: DecisionStackRuntimeId | None = None
    decision_output_id: str | None = None
    venue_id: str
    instrument_id: str
    account_id: str | None = None
    side: OrderSide
    position_side: PositionSide
    order_type: OrderType
    time_in_force: TimeInForce | None = None
    quantity: Decimal | None = None
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    reduce_only: bool
    post_only: bool
    close_position: bool
    expires_at: datetime | None = None
    permission_reason: OrderFlowPermissionReason
    created_at: datetime
    rationale_hash: str | None = None

    @field_validator("decision_output_id", "venue_id", "instrument_id", "account_id")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "text field")

    @field_validator("quantity", "limit_price", "stop_price", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("quantity", "limit_price", "stop_price")
    @classmethod
    def _validate_positive_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise ValueError("decimal fields must be > 0")
        return value

    @field_validator("created_at", "expires_at")
    @classmethod
    def _validate_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_aware_utc(value)

    @field_validator("rationale_hash")
    @classmethod
    def _validate_rationale_hash(cls, value: str | None) -> str | None:
        return None if value is None else _sha256_hex(value, "rationale_hash")

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        self._validate_quantity_and_prices()
        self._validate_safety_class()
        self._validate_time_in_force()
        self._validate_deterministic_ids()
        return self

    def _validate_quantity_and_prices(self) -> None:
        if self.quantity is None and not self.close_position:
            raise ValueError("quantity is required unless close_position=True")
        if self.order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT} and self.limit_price is None:
            raise ValueError("LIMIT and STOP_LIMIT orders require limit_price")
        if self.order_type in {
            OrderType.STOP_MARKET,
            OrderType.STOP_LIMIT,
            OrderType.TAKE_PROFIT_MARKET,
            OrderType.TAKE_PROFIT_LIMIT,
        } and self.stop_price is None:
            raise ValueError("stop/take-profit orders require stop_price")
        if self.order_type is OrderType.TAKE_PROFIT_LIMIT and self.limit_price is None:
            raise ValueError("TAKE_PROFIT_LIMIT requires limit_price")

    def _validate_safety_class(self) -> None:
        if self.intent_kind is OrderIntentKind.ENTRY:
            if self.reduce_only:
                raise ValueError("ENTRY must not be reduce_only")
            if self.close_position:
                raise ValueError("ENTRY must not be close_position")
        if self.intent_kind is OrderIntentKind.EXIT and not (
            self.reduce_only or self.close_position
        ):
            raise ValueError("EXIT must be reduce_only or close_position")
        if self.intent_kind in {
            OrderIntentKind.REDUCE_ONLY,
            OrderIntentKind.PROTECTIVE_STOP,
            OrderIntentKind.PROTECTIVE_TAKE_PROFIT,
        } and not self.reduce_only:
            raise ValueError("reduce/protective intents must be reduce_only")
        if self.intent_kind is OrderIntentKind.EMERGENCY_CLOSE and not (
            self.reduce_only or self.close_position
        ):
            raise ValueError("EMERGENCY_CLOSE must be reduce_only or close_position")

    def _validate_time_in_force(self) -> None:
        if self.order_type is OrderType.MARKET and self.post_only:
            raise ValueError("post_only cannot be used with MARKET")
        if self.post_only and self.time_in_force in {TimeInForce.IOC, TimeInForce.FOK}:
            raise ValueError("IOC/FOK cannot be used with post_only")
        if self.time_in_force is TimeInForce.GTD and self.expires_at is None:
            raise ValueError("GTD requires expires_at")

    def _validate_deterministic_ids(self) -> None:
        expected = deterministic_order_intent_ids(self)
        if self.intent_id is not None and self.intent_id != expected[0]:
            raise ValueError("intent_id is not deterministic")
        if self.idempotency_key is not None and self.idempotency_key != expected[1]:
            raise ValueError("idempotency_key is not deterministic")
        if self.client_order_id is not None and self.client_order_id != expected[2]:
            raise ValueError("client_order_id is not deterministic")
        object.__setattr__(self, "intent_id", expected[0])
        object.__setattr__(self, "idempotency_key", expected[1])
        object.__setattr__(self, "client_order_id", expected[2])


class CancelOrderIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cancel_intent_id: CancelOrderIntentId | None = None
    idempotency_key: OrderIdempotencyKey | None = None
    target_order_intent_id: OrderIntentId | None = None
    target_client_order_id: ClientOrderId | None = None
    target_venue_order_id: VenueOrderId | None = None
    venue_id: str
    instrument_id: str
    account_id: str | None = None
    cancel_scope: CancelScope
    cancel_reason: str
    created_at: datetime

    @field_validator("venue_id", "instrument_id", "account_id", "cancel_reason")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "cancel text")

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        has_target = any(
            (
                self.target_order_intent_id,
                self.target_client_order_id,
                self.target_venue_order_id,
            )
        )
        if self.cancel_scope is CancelScope.SINGLE_ORDER and not has_target:
            raise ValueError("single-order cancel requires a target identifier")
        expected_id, expected_key = deterministic_cancel_intent_ids(self)
        if self.cancel_intent_id is not None and self.cancel_intent_id != expected_id:
            raise ValueError("cancel_intent_id is not deterministic")
        if self.idempotency_key is not None and self.idempotency_key != expected_key:
            raise ValueError("idempotency_key is not deterministic")
        object.__setattr__(self, "cancel_intent_id", expected_id)
        object.__setattr__(self, "idempotency_key", expected_key)
        return self


class ReplaceOrderIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    replace_intent_id: ReplaceOrderIntentId | None = None
    idempotency_key: OrderIdempotencyKey | None = None
    target_order_intent_id: OrderIntentId | None = None
    target_client_order_id: ClientOrderId | None = None
    target_venue_order_id: VenueOrderId | None = None
    target_intent_kind: OrderIntentKind
    replacement_order: OrderIntent
    replace_reason: str
    created_at: datetime

    @field_validator("replace_reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _trimmed(value, "replace_reason")

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if not any(
            (
                self.target_order_intent_id,
                self.target_client_order_id,
                self.target_venue_order_id,
            )
        ):
            raise ValueError("replace target is required")
        target_is_entry = self.target_intent_kind is OrderIntentKind.ENTRY
        replacement_is_entry = self.replacement_order.intent_kind is OrderIntentKind.ENTRY
        if target_is_entry and not replacement_is_entry:
            raise ValueError("ENTRY target requires ENTRY replacement")
        if not target_is_entry and replacement_is_entry:
            raise ValueError("non-entry target must not become ENTRY")
        expected_id, expected_key = deterministic_replace_intent_ids(self)
        if self.replace_intent_id is not None and self.replace_intent_id != expected_id:
            raise ValueError("replace_intent_id is not deterministic")
        if self.idempotency_key is not None and self.idempotency_key != expected_key:
            raise ValueError("idempotency_key is not deterministic")
        object.__setattr__(self, "replace_intent_id", expected_id)
        object.__setattr__(self, "idempotency_key", expected_key)
        return self


class ExecutionOrderRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: ExecutionOrderRecordId
    order_intent: OrderIntent
    lifecycle_state: OrderLifecycleState
    client_order_id: ClientOrderId
    venue_order_id: VenueOrderId | None = None
    cumulative_filled_quantity: Decimal
    remaining_quantity: Decimal | None = None
    average_fill_price: Decimal | None = None
    last_lifecycle_event_id: OrderLifecycleEventId | None = None
    readiness_proof_id: ExecutionReadinessProofId | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator(
        "cumulative_filled_quantity",
        "remaining_quantity",
        "average_fill_price",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _validate_time(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be >= created_at")
        if self.cumulative_filled_quantity < 0:
            raise ValueError("cumulative_filled_quantity must be >= 0")
        quantity = self.order_intent.quantity
        if quantity is not None and self.cumulative_filled_quantity > quantity:
            raise ValueError("filled quantity cannot exceed order quantity")
        if self.remaining_quantity is not None and self.remaining_quantity < 0:
            raise ValueError("remaining_quantity must be >= 0")
        if (
            quantity is not None
            and self.remaining_quantity is not None
            and self.cumulative_filled_quantity + self.remaining_quantity != quantity
        ):
            raise ValueError("filled + remaining must equal order quantity")
        if self.average_fill_price is not None and self.average_fill_price <= 0:
            raise ValueError("average_fill_price must be > 0")
        if self.client_order_id != self.order_intent.client_order_id:
            raise ValueError("client_order_id must equal order_intent.client_order_id")
        if (
            self.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
            and self.readiness_proof_id is None
        ):
            raise ValueError("ACCEPTED_BY_EXECUTION records require readiness_proof_id")
        return self


class OrderLifecycleEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: OrderLifecycleEventId | None = None
    record_id: ExecutionOrderRecordId | None = None
    order_intent_id: OrderIntentId | None = None
    client_order_id: ClientOrderId
    event_kind: OrderLifecycleEventKind
    previous_state: OrderLifecycleState | None = None
    next_state: OrderLifecycleState
    occurred_at: datetime
    payload: Any
    payload_hash: str

    @field_validator("occurred_at")
    @classmethod
    def _validate_time(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: Any) -> Any:
        _canonical_json_bytes(value)
        return value

    @field_validator("payload_hash")
    @classmethod
    def _validate_hash(cls, value: str) -> str:
        return _sha256_hex(value, "payload_hash")

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.payload_hash != canonical_payload_hash(self.payload):
            raise ValueError("payload_hash does not match payload")
        validate_order_lifecycle_transition(self.previous_state, self.next_state)
        expected = deterministic_lifecycle_event_id(self)
        if self.event_id is not None and self.event_id != expected:
            raise ValueError("event_id is not deterministic")
        object.__setattr__(self, "event_id", expected)
        return self


class FillReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fill_report_id: FillReportId
    record_id: ExecutionOrderRecordId
    client_order_id: ClientOrderId
    venue_order_id: VenueOrderId | None = None
    venue_fill_id: str | None = None
    fill_quantity: Decimal
    fill_price: Decimal
    fee_quantity: Decimal | None = None
    fee_asset: str | None = None
    liquidity_role: str | None = None
    occurred_at: datetime

    @field_validator("fill_quantity", "fill_price", "fee_quantity", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: object) -> Decimal | None:
        return None if value is None else _coerce_decimal(value)

    @field_validator("venue_fill_id", "fee_asset", "liquidity_role")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "fill text")

    @field_validator("occurred_at")
    @classmethod
    def _validate_time(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.fill_quantity <= 0:
            raise ValueError("fill_quantity must be > 0")
        if self.fill_price <= 0:
            raise ValueError("fill_price must be > 0")
        if self.fee_quantity is not None and self.fee_quantity < 0:
            raise ValueError("fee_quantity must be >= 0")
        return self


class ExecutionReconciliationMarker(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reconciliation_id: ExecutionReconciliationId
    scope_kind: RuntimeDataScopeKind
    scope_id: str | None = None
    reason: ReconciliationReason
    required: bool
    created_at: datetime
    related_order_record_ids: tuple[ExecutionOrderRecordId, ...] = ()
    related_client_order_ids: tuple[ClientOrderId, ...] = ()

    @field_validator("scope_id")
    @classmethod
    def _validate_scope(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "scope_id")

    @field_validator("created_at")
    @classmethod
    def _validate_time(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


def validate_order_lifecycle_transition(
    previous_state: OrderLifecycleState | None,
    next_state: OrderLifecycleState,
) -> None:
    if previous_state is None:
        if next_state is not OrderLifecycleState.CREATED:
            raise ValueError("initial lifecycle event must create the order")
        return
    if previous_state is OrderLifecycleState.CLOSED:
        raise ValueError("CLOSED cannot transition to another state")
    allowed = _ALLOWED_TRANSITIONS.get(previous_state, frozenset())
    if next_state not in allowed:
        raise ValueError(f"invalid order lifecycle transition: {previous_state}->{next_state}")


def deterministic_order_intent_ids(
    intent: OrderIntent,
) -> tuple[OrderIntentId, OrderIdempotencyKey, ClientOrderId]:
    digest = _digest(_order_intent_identity(intent))
    return (
        OrderIntentId(value=f"order-intent:{digest}"),
        OrderIdempotencyKey(value=f"order-idem:{digest}"),
        ClientOrderId(value=f"coid:{digest}"),
    )


def deterministic_cancel_intent_ids(
    intent: CancelOrderIntent,
) -> tuple[CancelOrderIntentId, OrderIdempotencyKey]:
    digest = _digest(_model_identity(intent, exclude={"cancel_intent_id", "idempotency_key"}))
    return (
        CancelOrderIntentId(value=f"cancel-intent:{digest}"),
        OrderIdempotencyKey(value=f"cancel-idem:{digest}"),
    )


def deterministic_replace_intent_ids(
    intent: ReplaceOrderIntent,
) -> tuple[ReplaceOrderIntentId, OrderIdempotencyKey]:
    digest = _digest(_model_identity(intent, exclude={"replace_intent_id", "idempotency_key"}))
    return (
        ReplaceOrderIntentId(value=f"replace-intent:{digest}"),
        OrderIdempotencyKey(value=f"replace-idem:{digest}"),
    )


def deterministic_lifecycle_event_id(event: OrderLifecycleEvent) -> OrderLifecycleEventId:
    digest = _digest(_model_identity(event, exclude={"event_id"}))
    return OrderLifecycleEventId(value=f"order-event:{digest}")


def canonical_payload_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _order_intent_identity(intent: OrderIntent) -> dict[str, Any]:
    return _model_identity(
        intent,
        exclude={"intent_id", "idempotency_key", "client_order_id"},
    )


def _model_identity(model: BaseModel, *, exclude: set[str]) -> dict[str, Any]:
    dumped = model.model_dump()
    for key in exclude:
        dumped.pop(key, None)
    return _canonical_value(dumped)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_value(value: Any) -> Any:
    result: Any
    if isinstance(value, Decimal):
        result = format(value, "f")
    elif isinstance(value, datetime):
        result = ensure_aware_utc(value).isoformat()
    elif isinstance(value, StrEnum):
        result = value.value
    elif isinstance(value, BaseModel):
        result = _canonical_value(value.model_dump())
    elif isinstance(value, Mapping):
        result = {str(key): _canonical_value(item) for key, item in value.items()}
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        result = [_canonical_value(item) for item in value]
    else:
        result = value
    return result


def _canonical_json_bytes(payload: Any) -> bytes:
    payload = _canonical_value(payload)
    _validate_json_compatible(payload, path="payload")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _validate_json_compatible(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} float must be finite")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            _validate_json_compatible(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _validate_json_compatible(item, path=f"{path}[{index}]")
        return
    raise ValueError(f"{path} must be JSON-compatible")


def _coerce_decimal(value: object) -> Decimal:
    if isinstance(value, bool | float):
        raise ValueError("decimal value must be Decimal, int, or string")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        if value != value.strip():
            raise ValueError("decimal string must be trimmed")
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid decimal string") from exc
    else:
        raise ValueError("decimal value must be Decimal, int, or string")
    if not result.is_finite():
        raise ValueError("decimal value must be finite")
    return result


def _trimmed(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty and trimmed")
    return value


def _sha256_hex(value: str, name: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase sha256 hex")
    return value


_ACTIVE_VENUE_STATES = frozenset(
    {
        OrderLifecycleState.SUBMISSION_REQUESTED,
        OrderLifecycleState.SUBMITTED_TO_VENUE,
        OrderLifecycleState.ACKNOWLEDGED_BY_VENUE,
        OrderLifecycleState.PARTIALLY_FILLED,
        OrderLifecycleState.CANCEL_REQUESTED,
        OrderLifecycleState.REPLACE_REQUESTED,
    }
)

_ALLOWED_TRANSITIONS: dict[OrderLifecycleState, frozenset[OrderLifecycleState]] = {
    OrderLifecycleState.CREATED: frozenset(
        {
            OrderLifecycleState.ACCEPTED_BY_EXECUTION,
            OrderLifecycleState.REJECTED_BY_PERMISSION,
            OrderLifecycleState.REJECTED_BY_VALIDATION,
        }
    ),
    OrderLifecycleState.ACCEPTED_BY_EXECUTION: frozenset(
        {
            OrderLifecycleState.SUBMISSION_REQUESTED,
            OrderLifecycleState.CANCEL_REQUESTED,
            OrderLifecycleState.REPLACE_REQUESTED,
        }
    ),
    OrderLifecycleState.SUBMISSION_REQUESTED: frozenset(
        {OrderLifecycleState.SUBMITTED_TO_VENUE, OrderLifecycleState.UNKNOWN_ON_VENUE}
    ),
    OrderLifecycleState.SUBMITTED_TO_VENUE: frozenset(
        {
            OrderLifecycleState.ACKNOWLEDGED_BY_VENUE,
            OrderLifecycleState.UNKNOWN_ON_VENUE,
            OrderLifecycleState.VENUE_REJECTED,
        }
    ),
    OrderLifecycleState.ACKNOWLEDGED_BY_VENUE: frozenset(
        {
            OrderLifecycleState.PARTIALLY_FILLED,
            OrderLifecycleState.FILLED,
            OrderLifecycleState.CANCEL_REQUESTED,
            OrderLifecycleState.REPLACE_REQUESTED,
            OrderLifecycleState.EXPIRED,
            OrderLifecycleState.UNKNOWN_ON_VENUE,
            OrderLifecycleState.VENUE_REJECTED,
        }
    ),
    OrderLifecycleState.PARTIALLY_FILLED: frozenset(
        {
            OrderLifecycleState.PARTIALLY_FILLED,
            OrderLifecycleState.FILLED,
            OrderLifecycleState.CANCEL_REQUESTED,
            OrderLifecycleState.REPLACE_REQUESTED,
            OrderLifecycleState.UNKNOWN_ON_VENUE,
        }
    ),
    OrderLifecycleState.CANCEL_REQUESTED: frozenset(
        {OrderLifecycleState.CANCEL_ACKNOWLEDGED, OrderLifecycleState.UNKNOWN_ON_VENUE}
    ),
    OrderLifecycleState.CANCEL_ACKNOWLEDGED: frozenset({OrderLifecycleState.CANCELED}),
    OrderLifecycleState.REPLACE_REQUESTED: frozenset(
        {OrderLifecycleState.REPLACED, OrderLifecycleState.UNKNOWN_ON_VENUE}
    ),
    OrderLifecycleState.UNKNOWN_ON_VENUE: frozenset(
        {OrderLifecycleState.RECONCILIATION_REQUIRED}
    ),
    OrderLifecycleState.RECONCILIATION_REQUIRED: frozenset({OrderLifecycleState.CLOSED}),
    OrderLifecycleState.FILLED: frozenset({OrderLifecycleState.CLOSED}),
    OrderLifecycleState.CANCELED: frozenset({OrderLifecycleState.CLOSED}),
    OrderLifecycleState.EXPIRED: frozenset({OrderLifecycleState.CLOSED}),
    OrderLifecycleState.VENUE_REJECTED: frozenset({OrderLifecycleState.CLOSED}),
    OrderLifecycleState.REJECTED_BY_PERMISSION: frozenset({OrderLifecycleState.CLOSED}),
    OrderLifecycleState.REJECTED_BY_VALIDATION: frozenset({OrderLifecycleState.CLOSED}),
    OrderLifecycleState.REPLACED: frozenset({OrderLifecycleState.CLOSED}),
}

for _state in _ACTIVE_VENUE_STATES:
    _ALLOWED_TRANSITIONS[_state] = _ALLOWED_TRANSITIONS.get(_state, frozenset()) | frozenset(
        {OrderLifecycleState.UNKNOWN_ON_VENUE}
    )
