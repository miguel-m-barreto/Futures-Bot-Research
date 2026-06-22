from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from math import isfinite
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.ids import (
    CancelOrderIntentId,
    ClientOrderId,
    ExecutionAdmissionDecisionId,
    ExecutionAdmissionRequestId,
    ExecutionCoordinatorEventId,
    ExecutionOrderRecordId,
    ExecutionReconciliationId,
    OrderIntentId,
    OrderLifecycleEventId,
    ReplaceOrderIntentId,
)
from futures_bot.domain.order_lifecycle import (
    CancelOrderIntent,
    OrderIntent,
    ReplaceOrderIntent,
)
from futures_bot.domain.runtime_control import OrderFlowPermission
from futures_bot.domain.time import ensure_aware_utc


class ExecutionAdmissionRequestKind(StrEnum):
    ORDER_INTENT = "ORDER_INTENT"
    CANCEL_INTENT = "CANCEL_INTENT"
    REPLACE_INTENT = "REPLACE_INTENT"


class ExecutionAdmissionDecisionReason(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED_BY_PERMISSION = "REJECTED_BY_PERMISSION"
    REJECTED_BY_VALIDATION = "REJECTED_BY_VALIDATION"
    TARGET_ORDER_NOT_FOUND = "TARGET_ORDER_NOT_FOUND"
    TARGET_ORDER_NOT_ACTIVE = "TARGET_ORDER_NOT_ACTIVE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    DUPLICATE_IDEMPOTENCY_KEY = "DUPLICATE_IDEMPOTENCY_KEY"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"


class ExecutionCoordinatorEventKind(StrEnum):
    ADMISSION_REQUESTED = "ADMISSION_REQUESTED"
    ADMISSION_ACCEPTED = "ADMISSION_ACCEPTED"
    ADMISSION_REJECTED = "ADMISSION_REJECTED"
    ORDER_RECORD_CREATED = "ORDER_RECORD_CREATED"
    ORDER_RECORD_UPDATED = "ORDER_RECORD_UPDATED"
    LIFECYCLE_EVENT_APPENDED = "LIFECYCLE_EVENT_APPENDED"
    RECONCILIATION_MARKED = "RECONCILIATION_MARKED"
    IDEMPOTENT_REPLAY_DETECTED = "IDEMPOTENT_REPLAY_DETECTED"


class ExecutionAdmissionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: ExecutionAdmissionRequestId | None = None
    request_kind: ExecutionAdmissionRequestKind
    order_intent: OrderIntent | None = None
    cancel_intent: CancelOrderIntent | None = None
    replace_intent: ReplaceOrderIntent | None = None
    order_flow_permission: OrderFlowPermission
    requested_at: datetime
    requested_by: str
    correlation_id: str | None = None

    @field_validator("requested_at")
    @classmethod
    def _validate_requested_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("requested_by", "correlation_id")
    @classmethod
    def _validate_text(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "execution request text")

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        present = tuple(
            intent
            for intent in (self.order_intent, self.cancel_intent, self.replace_intent)
            if intent is not None
        )
        if len(present) != 1:
            raise ValueError("exactly one execution intent must be present")
        if self.request_kind is ExecutionAdmissionRequestKind.ORDER_INTENT:
            if self.order_intent is None:
                raise ValueError("ORDER_INTENT request requires order_intent")
        elif self.request_kind is ExecutionAdmissionRequestKind.CANCEL_INTENT:
            if self.cancel_intent is None:
                raise ValueError("CANCEL_INTENT request requires cancel_intent")
        elif self.replace_intent is None:
            raise ValueError("REPLACE_INTENT request requires replace_intent")
        expected = deterministic_execution_admission_request_id(self)
        if self.request_id is not None and self.request_id != expected:
            raise ValueError("request_id is not deterministic")
        object.__setattr__(self, "request_id", expected)
        return self


class ExecutionAdmissionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: ExecutionAdmissionDecisionId | None = None
    request_id: ExecutionAdmissionRequestId
    request_kind: ExecutionAdmissionRequestKind
    accepted: bool
    reason: ExecutionAdmissionDecisionReason
    order_intent_id: OrderIntentId | None = None
    cancel_intent_id: CancelOrderIntentId | None = None
    replace_intent_id: ReplaceOrderIntentId | None = None
    client_order_id: ClientOrderId | None = None
    record_id: ExecutionOrderRecordId | None = None
    lifecycle_event_ids: tuple[OrderLifecycleEventId, ...] = ()
    reconciliation_marker_ids: tuple[ExecutionReconciliationId, ...] = ()
    decided_at: datetime

    @field_validator("decided_at")
    @classmethod
    def _validate_decided_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        accepted_reasons = {
            ExecutionAdmissionDecisionReason.ACCEPTED,
            ExecutionAdmissionDecisionReason.IDEMPOTENT_REPLAY,
        }
        if self.accepted and self.reason not in accepted_reasons:
            raise ValueError("accepted decisions require ACCEPTED or IDEMPOTENT_REPLAY")
        if not self.accepted and self.reason in accepted_reasons:
            raise ValueError("rejected decisions require a non-accepted reason")
        expected = deterministic_execution_admission_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


class ExecutionCoordinatorEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: ExecutionCoordinatorEventId | None = None
    request_id: ExecutionAdmissionRequestId
    decision_id: ExecutionAdmissionDecisionId | None = None
    event_kind: ExecutionCoordinatorEventKind
    occurred_at: datetime
    payload: Any
    payload_hash: str

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: datetime) -> datetime:
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
        expected = deterministic_execution_coordinator_event_id(self)
        if self.event_id is not None and self.event_id != expected:
            raise ValueError("event_id is not deterministic")
        object.__setattr__(self, "event_id", expected)
        return self


def deterministic_execution_admission_request_id(
    request: ExecutionAdmissionRequest,
) -> ExecutionAdmissionRequestId:
    digest = _digest(_model_identity(request, exclude={"request_id"}))
    return ExecutionAdmissionRequestId(value=f"exec-admission-request:{digest}")


def deterministic_execution_admission_decision_id(
    decision: ExecutionAdmissionDecision,
) -> ExecutionAdmissionDecisionId:
    digest = _digest(_model_identity(decision, exclude={"decision_id"}))
    return ExecutionAdmissionDecisionId(value=f"exec-admission-decision:{digest}")


def deterministic_execution_coordinator_event_id(
    event: ExecutionCoordinatorEvent,
) -> ExecutionCoordinatorEventId:
    digest = _digest(_model_identity(event, exclude={"event_id"}))
    return ExecutionCoordinatorEventId(value=f"exec-coordinator-event:{digest}")


def canonical_payload_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _model_identity(model: BaseModel, *, exclude: set[str]) -> dict[str, Any]:
    dumped = model.model_dump()
    for key in exclude:
        dumped.pop(key, None)
    return _canonical_value(dumped)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_value(value: Any) -> Any:
    result: Any
    if isinstance(value, datetime):
        result = ensure_aware_utc(value).isoformat()
    elif isinstance(value, Decimal):
        result = format(value, "f")
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


def _trimmed(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty and trimmed")
    return value


def _sha256_hex(value: str, name: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase sha256 hex")
    return value
