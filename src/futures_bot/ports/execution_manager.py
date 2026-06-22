from __future__ import annotations

from typing import Protocol

from futures_bot.domain.execution_manager import (
    ExecutionAdmissionDecision,
    ExecutionAdmissionRequest,
    ExecutionCoordinatorEvent,
)
from futures_bot.domain.ids import (
    ExecutionAdmissionDecisionId,
    ExecutionCoordinatorEventId,
)


class ExecutionManagerCoordinatorPort(Protocol):
    """Pure interface for local execution-manager admission."""

    def admit(
        self,
        request: ExecutionAdmissionRequest,
    ) -> ExecutionAdmissionDecision:
        """Accept or reject a local execution admission request."""
        ...


class ExecutionAdmissionDecisionStorePort(Protocol):
    """Pure store interface for execution admission decisions."""

    def put(self, decision: ExecutionAdmissionDecision) -> None:
        """Store an admission decision idempotently."""
        ...

    def get(
        self,
        decision_id: ExecutionAdmissionDecisionId,
    ) -> ExecutionAdmissionDecision | None:
        """Return an admission decision by ID, or None."""
        ...


class ExecutionCoordinatorEventStorePort(Protocol):
    """Pure append-order coordinator event store interface."""

    def append(self, event: ExecutionCoordinatorEvent) -> None:
        """Append a coordinator event idempotently."""
        ...

    def list_events(self) -> tuple[ExecutionCoordinatorEvent, ...]:
        """Return coordinator events in append order."""
        ...

    def get(
        self,
        event_id: ExecutionCoordinatorEventId,
    ) -> ExecutionCoordinatorEvent | None:
        """Return a coordinator event by ID, or None."""
        ...
