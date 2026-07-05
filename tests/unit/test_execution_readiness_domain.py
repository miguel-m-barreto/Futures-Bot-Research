from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.execution_readiness import (
    ExecutionReadinessGate,
    ExecutionReadinessGateEvidence,
    ExecutionReadinessGateStatus,
    ExecutionReadinessProof,
    ExecutionReadinessProofReason,
)
from futures_bot.domain.ids import ClientOrderId, OrderIntentId

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _gate(
    status: ExecutionReadinessGateStatus = ExecutionReadinessGateStatus.PASSED,
    *,
    gate: ExecutionReadinessGate = ExecutionReadinessGate.RUNTIME_PERMISSION,
    required: bool = True,
    reason: str = "ok",
) -> ExecutionReadinessGateEvidence:
    return ExecutionReadinessGateEvidence(
        gate=gate,
        status=status,
        required=required,
        reason=reason,
        details={"checked": True},
    )


def _proof(
    *,
    gates: tuple[ExecutionReadinessGateEvidence, ...] | None = None,
    ready: bool = True,
    reason: ExecutionReadinessProofReason = ExecutionReadinessProofReason.READY,
) -> ExecutionReadinessProof:
    return ExecutionReadinessProof(
        order_intent_id=OrderIntentId("order-1"),
        client_order_id=ClientOrderId("client-1"),
        gates=gates or (_gate(),),
        ready=ready,
        reason=reason,
        created_at=NOW,
        details={"local_acceptance_only": True},
    )


def test_gate_evidence_details_must_be_json_compatible() -> None:
    with pytest.raises(ValidationError, match="JSON-compatible"):
        ExecutionReadinessGateEvidence(
            gate=ExecutionReadinessGate.RUNTIME_PERMISSION,
            status=ExecutionReadinessGateStatus.PASSED,
            required=True,
            reason="ok",
            details={"bad": object()},
        )


def test_required_skipped_gate_requires_reason() -> None:
    with pytest.raises(ValidationError, match="require a reason"):
        ExecutionReadinessGateEvidence(
            gate=ExecutionReadinessGate.VENUE_CAPABILITY,
            status=ExecutionReadinessGateStatus.SKIPPED,
            required=True,
            details={},
        )


def test_readiness_proof_id_is_deterministic() -> None:
    assert _proof().proof_id == _proof().proof_id


def test_ready_proof_requires_ready_reason() -> None:
    with pytest.raises(ValidationError, match="require READY"):
        _proof(reason=ExecutionReadinessProofReason.NOT_READY)


def test_ready_proof_rejects_failed_gate() -> None:
    with pytest.raises(ValidationError, match="failed or unknown"):
        _proof(gates=(_gate(ExecutionReadinessGateStatus.FAILED),))


def test_ready_proof_rejects_failed_source_provenance_gate() -> None:
    with pytest.raises(ValidationError, match="failed or unknown"):
        _proof(
            gates=(
                _gate(
                    ExecutionReadinessGateStatus.FAILED,
                    gate=ExecutionReadinessGate.SOURCE_PROVENANCE,
                    required=True,
                    reason="SOURCE_RECORD_NOT_ACCEPTED",
                ),
            )
        )


def test_ready_proof_rejects_unknown_gate() -> None:
    with pytest.raises(ValidationError, match="failed or unknown"):
        _proof(gates=(_gate(ExecutionReadinessGateStatus.UNKNOWN),))


def test_ready_proof_rejects_required_gate_not_passed() -> None:
    with pytest.raises(ValidationError, match="required gates to pass"):
        _proof(
            gates=(
                _gate(
                    ExecutionReadinessGateStatus.NOT_REQUIRED,
                    required=True,
                    reason="upstream rejected before gate",
                ),
            )
        )


def test_not_ready_proof_allows_failed_gate() -> None:
    proof = _proof(
        gates=(_gate(ExecutionReadinessGateStatus.FAILED),),
        ready=False,
        reason=ExecutionReadinessProofReason.FAILED_GATE,
    )
    assert proof.ready is False


def test_readiness_proof_requires_identity_field() -> None:
    with pytest.raises(ValidationError, match="requires an order or client identity"):
        ExecutionReadinessProof(
            gates=(_gate(),),
            ready=True,
            reason=ExecutionReadinessProofReason.READY,
            created_at=NOW,
            details={},
        )
