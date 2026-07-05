from __future__ import annotations

from futures_bot.domain.execution_manager import (
    ExecutionAdmissionDecision,
    ExecutionCoordinatorEvent,
)
from futures_bot.domain.execution_readiness import ExecutionReadinessProof
from futures_bot.domain.ids import (
    ClientOrderId,
    ExecutionAdmissionDecisionId,
    ExecutionCoordinatorEventId,
    ExecutionReadinessProofId,
)


class InMemoryExecutionAdmissionDecisionStore:
    """Deterministic admission decision store test double."""

    def __init__(self) -> None:
        self._decisions: dict[str, ExecutionAdmissionDecision] = {}

    def put(self, decision: ExecutionAdmissionDecision) -> None:
        if decision.decision_id is None:
            raise ValueError("decision_id is required")
        _put_idempotent(
            self._decisions,
            str(decision.decision_id),
            decision,
            "execution admission decision",
        )

    def get(
        self,
        decision_id: ExecutionAdmissionDecisionId,
    ) -> ExecutionAdmissionDecision | None:
        return self._decisions.get(str(decision_id))


class InMemoryExecutionCoordinatorEventStore:
    """Append-order-preserving coordinator event store test double."""

    def __init__(self) -> None:
        self._events_by_id: dict[str, ExecutionCoordinatorEvent] = {}
        self._event_ids: list[str] = []

    def append(self, event: ExecutionCoordinatorEvent) -> None:
        if event.event_id is None:
            raise ValueError("event_id is required")
        key = str(event.event_id)
        existing = self._events_by_id.get(key)
        if existing is not None:
            if existing != event:
                raise ValueError("execution coordinator event id collision")
            return
        self._events_by_id[key] = event
        self._event_ids.append(key)

    def list_events(self) -> tuple[ExecutionCoordinatorEvent, ...]:
        return tuple(self._events_by_id[event_id] for event_id in self._event_ids)

    def get(
        self,
        event_id: ExecutionCoordinatorEventId,
    ) -> ExecutionCoordinatorEvent | None:
        return self._events_by_id.get(str(event_id))


class InMemoryExecutionReadinessProofStore:
    """Deterministic readiness proof store test double."""

    def __init__(self) -> None:
        self._proofs_by_id: dict[str, ExecutionReadinessProof] = {}
        self._proof_ids: list[str] = []
        self._proof_id_by_client_id: dict[str, str] = {}

    def put(self, proof: ExecutionReadinessProof) -> None:
        if proof.proof_id is None:
            raise ValueError("proof_id is required")
        key = str(proof.proof_id)
        existing = self._proofs_by_id.get(key)
        if existing is not None:
            if existing != proof:
                raise ValueError("execution readiness proof id collision")
            return
        client_order_id = proof.replacement_client_order_id or proof.client_order_id
        if client_order_id is not None:
            client_key = str(client_order_id)
            existing_proof_id = self._proof_id_by_client_id.get(client_key)
            if existing_proof_id is not None and existing_proof_id != key:
                raise ValueError(
                    "client_order_id is already bound to a different readiness proof"
                )
            self._proof_id_by_client_id[client_key] = key
        self._proofs_by_id[key] = proof
        self._proof_ids.append(key)

    def get(
        self,
        proof_id: ExecutionReadinessProofId,
    ) -> ExecutionReadinessProof | None:
        return self._proofs_by_id.get(str(proof_id))

    def get_by_client_order_id(
        self,
        client_order_id: ClientOrderId,
    ) -> ExecutionReadinessProof | None:
        proof_id = self._proof_id_by_client_id.get(str(client_order_id))
        if proof_id is None:
            return None
        return self._proofs_by_id[proof_id]

    def list_proofs(self) -> tuple[ExecutionReadinessProof, ...]:
        return tuple(self._proofs_by_id[proof_id] for proof_id in self._proof_ids)


def _put_idempotent[T](
    store: dict[str, T],
    key: str,
    value: T,
    name: str,
) -> None:
    existing = store.get(key)
    if existing is not None:
        if existing != value:
            raise ValueError(f"{name} id collision")
        return
    store[key] = value
