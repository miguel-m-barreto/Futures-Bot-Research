from __future__ import annotations

from datetime import UTC, datetime

from futures_bot.domain.execution_manager import (
    ExecutionAdmissionDecisionReason,
    ExecutionAdmissionRequest,
    ExecutionAdmissionRequestKind,
)
from futures_bot.domain.order_lifecycle import (
    OrderIntent,
    OrderIntentKind,
    OrderLifecycleState,
    OrderSide,
    OrderType,
    PositionSide,
)
from futures_bot.domain.runtime_control import (
    OrderFlowPermission,
    OrderFlowPermissionReason,
)
from futures_bot.execution_manager.coordinator import (
    DeterministicExecutionManagerCoordinator,
)
from futures_bot.order_lifecycle.in_memory import (
    InMemoryExecutionOrderRecordStore,
    InMemoryExecutionReconciliationStore,
    InMemoryOrderIntentJournal,
    InMemoryOrderLifecycleEventStore,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _permission(
    *,
    allow_new_entries: bool = True,
    allow_reduce_only_orders: bool = True,
    guardian_required: bool = False,
) -> OrderFlowPermission:
    return OrderFlowPermission(
        allow_new_entries=allow_new_entries,
        allow_entry_order_cancel=True,
        allow_exit_orders=True,
        allow_reduce_only_orders=allow_reduce_only_orders,
        allow_exit_order_cancel=True,
        allow_emergency_close=True,
        allow_reconciliation=False,
        guardian_required=guardian_required,
        manual_intervention_required=False,
        reason=OrderFlowPermissionReason.OK,
    )


def _intent(
    kind: OrderIntentKind = OrderIntentKind.ENTRY,
    *,
    instrument_id: str = "BTC-PERP",
) -> OrderIntent:
    return OrderIntent(
        intent_kind=kind,
        venue_id="venue-1",
        instrument_id=instrument_id,
        account_id="acct-1",
        side=OrderSide.BUY if kind is OrderIntentKind.ENTRY else OrderSide.SELL,
        position_side=PositionSide.LONG,
        order_type=OrderType.MARKET,
        quantity="1",
        reduce_only=kind is not OrderIntentKind.ENTRY,
        post_only=False,
        close_position=False,
        permission_reason=OrderFlowPermissionReason.OK,
        created_at=NOW,
    )


def _request(
    intent: OrderIntent,
    permission: OrderFlowPermission,
) -> ExecutionAdmissionRequest:
    return ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=intent,
        order_flow_permission=permission,
        requested_at=NOW,
        requested_by="unit-test",
    )


def _coordinator() -> tuple[
    DeterministicExecutionManagerCoordinator,
    InMemoryExecutionOrderRecordStore,
    InMemoryOrderLifecycleEventStore,
]:
    records = InMemoryExecutionOrderRecordStore()
    lifecycle = InMemoryOrderLifecycleEventStore()
    coordinator = DeterministicExecutionManagerCoordinator(
        intent_journal=InMemoryOrderIntentJournal(),
        lifecycle_event_store=lifecycle,
        order_record_store=records,
        reconciliation_store=InMemoryExecutionReconciliationStore(),
    )
    return coordinator, records, lifecycle


def test_allowed_order_intent_creates_journal_record_and_lifecycle_event() -> None:
    coordinator, records, lifecycle = _coordinator()
    intent = _intent()
    assert intent.client_order_id is not None

    decision = coordinator.admit(_request(intent, _permission()))

    record = records.get_by_client_order_id(intent.client_order_id)
    assert decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.ACCEPTED
    assert record is not None
    assert record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
    assert len(lifecycle.list_events()) == 2


def test_blocked_entry_creates_rejection_event_and_no_active_record() -> None:
    coordinator, records, lifecycle = _coordinator()
    intent = _intent()
    assert intent.client_order_id is not None

    decision = coordinator.admit(_request(intent, _permission(allow_new_entries=False)))

    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_PERMISSION
    assert records.get_by_client_order_id(intent.client_order_id) is None
    assert lifecycle.list_events()[-1].next_state is OrderLifecycleState.REJECTED_BY_PERMISSION


def test_guardian_mode_blocks_entry_but_allows_reduce_only() -> None:
    coordinator, records, _ = _coordinator()
    entry = _intent(OrderIntentKind.ENTRY)
    reduce = _intent(OrderIntentKind.REDUCE_ONLY, instrument_id="ETH-PERP")
    assert entry.client_order_id is not None
    assert reduce.client_order_id is not None

    entry_decision = coordinator.admit(
        _request(entry, _permission(guardian_required=True))
    )
    reduce_decision = coordinator.admit(
        _request(reduce, _permission(guardian_required=True))
    )

    assert not entry_decision.accepted
    assert reduce_decision.accepted
    assert records.get_by_client_order_id(entry.client_order_id) is None
    assert records.get_by_client_order_id(reduce.client_order_id) is not None


def test_idempotent_replay_of_same_allowed_order_does_not_duplicate_record_events() -> None:
    coordinator, records, lifecycle = _coordinator()
    intent = _intent()
    assert intent.client_order_id is not None

    first = coordinator.admit(_request(intent, _permission()))
    second = coordinator.admit(_request(intent, _permission()))

    assert first.accepted
    assert second.accepted
    assert second.reason is ExecutionAdmissionDecisionReason.IDEMPOTENT_REPLAY
    assert records.get_by_client_order_id(intent.client_order_id) is not None
    assert len(lifecycle.list_events()) == 2


def test_same_client_order_id_idempotency_conflict_is_rejected() -> None:
    coordinator, _, _ = _coordinator()
    intent = _intent()
    changed = intent.model_copy(update={"instrument_id": "ETH-PERP"})

    coordinator.admit(_request(intent, _permission()))
    malformed_request = _request(intent, _permission()).model_copy(
        update={"order_intent": changed}
    )
    decision = coordinator.admit(malformed_request)

    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.DUPLICATE_IDEMPOTENCY_KEY


def test_accepted_order_does_not_transition_to_submitted_to_venue() -> None:
    coordinator, records, lifecycle = _coordinator()
    intent = _intent()
    assert intent.client_order_id is not None

    coordinator.admit(_request(intent, _permission()))

    record = records.get_by_client_order_id(intent.client_order_id)
    assert record is not None
    assert record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
    assert all(
        event.next_state is not OrderLifecycleState.SUBMITTED_TO_VENUE
        for event in lifecycle.list_events()
    )
