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
    ClientOrderId,
    ExecutionCapabilityCheckId,
    ExecutionCapabilityDecisionId,
    OrderIntentId,
)
from futures_bot.domain.order_lifecycle import OrderIntent
from futures_bot.domain.time import ensure_aware_utc
from futures_bot.domain.venue_capabilities import VenueOrderValidationContext


class ExecutionCapabilityDecisionReason(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    REJECTED_BY_VENUE_CAPABILITY = "REJECTED_BY_VENUE_CAPABILITY"
    VALIDATION_CONTEXT_MISMATCH = "VALIDATION_CONTEXT_MISMATCH"


class ExecutionCapabilityCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: ExecutionCapabilityCheckId | None = None
    order_intent: OrderIntent
    venue_validation_context: VenueOrderValidationContext
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
        return None if value is None else _trimmed(value, "capability check text")

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.venue_validation_context.order_intent != self.order_intent:
            raise ValueError("venue_validation_context.order_intent must match order_intent")
        expected = deterministic_execution_capability_check_id(self)
        if self.check_id is not None and self.check_id != expected:
            raise ValueError("check_id is not deterministic")
        object.__setattr__(self, "check_id", expected)
        return self


class ExecutionCapabilityDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: ExecutionCapabilityDecisionId | None = None
    check_id: ExecutionCapabilityCheckId
    order_intent_id: OrderIntentId | None = None
    client_order_id: ClientOrderId | None = None
    executable: bool
    reason: ExecutionCapabilityDecisionReason
    venue_validation_reason: str | None = None
    venue_validation_details: Any = None
    decided_at: datetime

    @field_validator("decided_at")
    @classmethod
    def _validate_decided_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("venue_validation_details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        if value is not None:
            _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.executable and self.reason is not ExecutionCapabilityDecisionReason.EXECUTABLE:
            raise ValueError("executable=True requires reason EXECUTABLE")
        if not self.executable and self.reason is ExecutionCapabilityDecisionReason.EXECUTABLE:
            raise ValueError("executable=False requires reason != EXECUTABLE")
        expected = deterministic_execution_capability_decision_id(self)
        if self.decision_id is not None and self.decision_id != expected:
            raise ValueError("decision_id is not deterministic")
        object.__setattr__(self, "decision_id", expected)
        return self


def deterministic_execution_capability_check_id(
    check: ExecutionCapabilityCheck,
) -> ExecutionCapabilityCheckId:
    digest = _digest(_model_identity(check, exclude={"check_id"}))
    return ExecutionCapabilityCheckId(value=f"exec-capability-check:{digest}")


def deterministic_execution_capability_decision_id(
    decision: ExecutionCapabilityDecision,
) -> ExecutionCapabilityDecisionId:
    digest = _digest(_model_identity(decision, exclude={"decision_id"}))
    return ExecutionCapabilityDecisionId(value=f"exec-capability-decision:{digest}")


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
