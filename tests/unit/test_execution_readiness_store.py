from __future__ import annotations

from datetime import UTC, datetime

import pytest

from futures_bot.domain.execution_readiness import (
    ExecutionReadinessGate,
    ExecutionReadinessGateEvidence,
    ExecutionReadinessGateStatus,
    ExecutionReadinessProof,
    ExecutionReadinessProofReason,
)
from futures_bot.domain.ids import ClientOrderId, ExecutionReadinessProofId, OrderIntentId
from futures_bot.execution_manager.in_memory import InMemoryExecutionReadinessProofStore

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _proof(client_order_id: str = "client-1") -> ExecutionReadinessProof:
    return ExecutionReadinessProof(
        order_intent_id=OrderIntentId(f"order-{client_order_id}"),
        client_order_id=ClientOrderId(client_order_id),
        gates=(
            ExecutionReadinessGateEvidence(
                gate=ExecutionReadinessGate.RUNTIME_PERMISSION,
                status=ExecutionReadinessGateStatus.PASSED,
                required=True,
                reason="OK",
                details={},
            ),
        ),
        ready=True,
        reason=ExecutionReadinessProofReason.READY,
        created_at=NOW,
        details={"client_order_id": client_order_id},
    )


def test_readiness_proof_store_put_get_and_get_by_client_order_id() -> None:
    store = InMemoryExecutionReadinessProofStore()
    proof = _proof()
    assert proof.proof_id is not None

    store.put(proof)

    assert store.get(proof.proof_id) == proof
    assert store.get_by_client_order_id(ClientOrderId("client-1")) == proof


def test_readiness_proof_store_same_payload_is_idempotent() -> None:
    store = InMemoryExecutionReadinessProofStore()
    proof = _proof()

    store.put(proof)
    store.put(proof)

    assert store.list_proofs() == (proof,)


def test_readiness_proof_store_same_id_different_payload_rejects() -> None:
    store = InMemoryExecutionReadinessProofStore()
    proof = _proof()
    changed = proof.model_copy(update={"details": {"changed": True}})

    store.put(proof)

    with pytest.raises(ValueError, match="readiness proof id collision"):
        store.put(changed)


def test_readiness_proof_store_list_order_is_deterministic() -> None:
    store = InMemoryExecutionReadinessProofStore()
    first = _proof("client-1")
    second = _proof("client-2")

    store.put(first)
    store.put(second)

    assert store.list_proofs() == (first, second)
    assert store.get(ExecutionReadinessProofId("missing")) is None
