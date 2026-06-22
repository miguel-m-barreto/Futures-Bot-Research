from __future__ import annotations

from futures_bot.domain.execution_manager import (
    ExecutionAdmissionDecision,
    ExecutionCoordinatorEvent,
)
from futures_bot.domain.ids import (
    ExecutionAdmissionDecisionId,
    ExecutionCoordinatorEventId,
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
