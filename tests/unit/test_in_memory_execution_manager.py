from __future__ import annotations

from datetime import UTC, datetime

import pytest

from futures_bot.domain.execution_manager import (
    ExecutionAdmissionDecision,
    ExecutionAdmissionDecisionReason,
    ExecutionAdmissionRequestKind,
    ExecutionCoordinatorEvent,
    ExecutionCoordinatorEventKind,
    canonical_payload_hash,
)
from futures_bot.domain.ids import (
    ExecutionAdmissionDecisionId,
    ExecutionAdmissionRequestId,
    ExecutionCoordinatorEventId,
)
from futures_bot.execution_manager.in_memory import (
    InMemoryExecutionAdmissionDecisionStore,
    InMemoryExecutionCoordinatorEventStore,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
REQUEST_ID = ExecutionAdmissionRequestId("request-1")


def _decision() -> ExecutionAdmissionDecision:
    return ExecutionAdmissionDecision(
        request_id=REQUEST_ID,
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        accepted=True,
        reason=ExecutionAdmissionDecisionReason.ACCEPTED,
        decided_at=NOW,
    )


def _event(payload: dict[str, str]) -> ExecutionCoordinatorEvent:
    return ExecutionCoordinatorEvent(
        request_id=REQUEST_ID,
        event_kind=ExecutionCoordinatorEventKind.ADMISSION_REQUESTED,
        occurred_at=NOW,
        payload=payload,
        payload_hash=canonical_payload_hash(payload),
    )


def test_admission_decision_store_idempotent_same_decision() -> None:
    store = InMemoryExecutionAdmissionDecisionStore()
    decision = _decision()

    store.put(decision)
    store.put(decision)

    assert decision.decision_id is not None
    assert store.get(decision.decision_id) == decision


def test_admission_decision_store_rejects_same_id_different_payload() -> None:
    store = InMemoryExecutionAdmissionDecisionStore()
    decision = _decision()
    changed = decision.model_copy(update={"accepted": False})

    store.put(decision)
    with pytest.raises(ValueError, match="execution admission decision"):
        store.put(changed)


def test_coordinator_event_store_append_order_deterministic() -> None:
    store = InMemoryExecutionCoordinatorEventStore()
    first = _event({"n": "1"})
    second = _event({"n": "2"})

    store.append(first)
    store.append(second)

    assert store.list_events() == (first, second)


def test_coordinator_event_store_rejects_conflicting_id() -> None:
    store = InMemoryExecutionCoordinatorEventStore()
    event = _event({"n": "1"})
    changed = event.model_copy(update={"payload": {"n": "changed"}})

    store.append(event)
    with pytest.raises(ValueError, match="event id collision"):
        store.append(changed)

    assert event.event_id is not None
    assert store.get(event.event_id) == event


def test_execution_manager_store_get_missing_returns_none() -> None:
    assert (
        InMemoryExecutionAdmissionDecisionStore().get(
            ExecutionAdmissionDecisionId("missing-decision")
        )
        is None
    )
    assert (
        InMemoryExecutionCoordinatorEventStore().get(
            ExecutionCoordinatorEventId("missing-event")
        )
        is None
    )
