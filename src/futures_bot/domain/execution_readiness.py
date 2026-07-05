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
    ExecutionAdmissionRequestId,
    ExecutionReadinessProofId,
    OrderIntentId,
    OrderLifecycleEventId,
    ReplaceOrderIntentId,
)
from futures_bot.domain.time import ensure_aware_utc


class ExecutionReadinessGate(StrEnum):
    RUNTIME_PERMISSION = "RUNTIME_PERMISSION"
    VENUE_CAPABILITY = "VENUE_CAPABILITY"
    CAPABILITY_FRESHNESS = "CAPABILITY_FRESHNESS"
    SOURCE_PROVENANCE = "SOURCE_PROVENANCE"
    ASSET_SEMANTICS = "ASSET_SEMANTICS"
    ORDER_SCOPE = "ORDER_SCOPE"
    REPLACE_TARGET = "REPLACE_TARGET"
    IDEMPOTENCY = "IDEMPOTENCY"


class ExecutionReadinessGateStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_REQUIRED = "NOT_REQUIRED"
    SKIPPED = "SKIPPED"
    UNKNOWN = "UNKNOWN"


class ExecutionReadinessProofReason(StrEnum):
    READY = "READY"
    NOT_READY = "NOT_READY"
    INCOMPLETE_PROOF = "INCOMPLETE_PROOF"
    FAILED_GATE = "FAILED_GATE"
    ACCEPTANCE_WITHOUT_REQUIRED_GATE = "ACCEPTANCE_WITHOUT_REQUIRED_GATE"


class ExecutionReadinessGateEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gate: ExecutionReadinessGate
    status: ExecutionReadinessGateStatus
    required: bool
    reason: str | None = None
    details: Any = None

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value, "readiness gate reason")

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if (
            self.required
            and self.status
            in {
                ExecutionReadinessGateStatus.NOT_REQUIRED,
                ExecutionReadinessGateStatus.SKIPPED,
            }
            and self.reason is None
        ):
            raise ValueError(
                "required NOT_REQUIRED/SKIPPED readiness gates require a reason"
            )
        return self


class ExecutionReadinessProof(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proof_id: ExecutionReadinessProofId | None = None
    order_intent_id: OrderIntentId | None = None
    replace_intent_id: ReplaceOrderIntentId | None = None
    client_order_id: ClientOrderId | None = None
    replacement_client_order_id: ClientOrderId | None = None
    request_id: ExecutionAdmissionRequestId | None = None
    lifecycle_event_ids: tuple[OrderLifecycleEventId, ...] = ()
    gates: tuple[ExecutionReadinessGateEvidence, ...]
    ready: bool
    reason: ExecutionReadinessProofReason
    created_at: datetime
    details: Any = None

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("details")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.ready and self.reason is not ExecutionReadinessProofReason.READY:
            raise ValueError("ready readiness proofs require READY reason")
        if not self.ready and self.reason is ExecutionReadinessProofReason.READY:
            raise ValueError("not-ready readiness proofs require non-READY reason")
        if self.ready and not self.gates:
            raise ValueError("ready readiness proofs require gate evidence")
        if not any((self.order_intent_id, self.replace_intent_id, self.client_order_id)):
            raise ValueError("readiness proof requires an order or client identity")
        gate_order = tuple(gate for gate in ExecutionReadinessGate)
        gates = tuple(sorted(self.gates, key=lambda evidence: gate_order.index(evidence.gate)))
        if len({evidence.gate for evidence in gates}) != len(gates):
            raise ValueError("readiness proof gates must be unique")
        object.__setattr__(self, "gates", gates)
        if self.ready:
            for evidence in gates:
                if evidence.status in {
                    ExecutionReadinessGateStatus.FAILED,
                    ExecutionReadinessGateStatus.UNKNOWN,
                }:
                    raise ValueError("ready readiness proofs reject failed or unknown gates")
                if evidence.required and evidence.status is not ExecutionReadinessGateStatus.PASSED:
                    raise ValueError("ready readiness proofs require required gates to pass")
        expected = deterministic_execution_readiness_proof_id(self)
        if self.proof_id is not None and self.proof_id != expected:
            raise ValueError("proof_id is not deterministic")
        object.__setattr__(self, "proof_id", expected)
        return self


def deterministic_execution_readiness_proof_id(
    proof: ExecutionReadinessProof,
) -> ExecutionReadinessProofId:
    digest = _digest(_model_identity(proof, exclude={"proof_id"}))
    return ExecutionReadinessProofId(value=f"exec-readiness-proof:{digest}")


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
