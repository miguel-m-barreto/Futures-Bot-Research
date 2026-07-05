from __future__ import annotations

from typing import Protocol

from futures_bot.domain.execution_readiness import ExecutionReadinessProof
from futures_bot.domain.ids import ClientOrderId, ExecutionReadinessProofId


class ExecutionReadinessProofStorePort(Protocol):
    """Pure store interface for local execution readiness proofs."""

    def put(self, proof: ExecutionReadinessProof) -> None:
        """Store a readiness proof idempotently."""
        ...

    def get(
        self,
        proof_id: ExecutionReadinessProofId,
    ) -> ExecutionReadinessProof | None:
        """Return a readiness proof by ID, or None."""
        ...

    def get_by_client_order_id(
        self,
        client_order_id: ClientOrderId,
    ) -> ExecutionReadinessProof | None:
        """Return the readiness proof linked to a client order ID, or None."""
        ...

    def list_proofs(self) -> tuple[ExecutionReadinessProof, ...]:
        """Return readiness proofs in deterministic insertion order."""
        ...
