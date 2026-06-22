from __future__ import annotations

from datetime import UTC, datetime

from futures_bot.domain.execution_manager import (
    ExecutionAdmissionDecisionReason,
    ExecutionAdmissionRequest,
    ExecutionAdmissionRequestKind,
)
from futures_bot.domain.ids import ClientOrderId
from futures_bot.domain.order_lifecycle import (
    CancelOrderIntent,
    CancelScope,
    OrderIntent,
    OrderIntentKind,
    OrderLifecycleState,
    OrderSide,
    OrderType,
    PositionSide,
    ReplaceOrderIntent,
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
    allow_entry_order_cancel: bool = True,
    allow_exit_order_cancel: bool = True,
    allow_exit_orders: bool = True,
    allow_reduce_only_orders: bool = True,
    allow_emergency_close: bool = True,
) -> OrderFlowPermission:
    return OrderFlowPermission(
        allow_new_entries=True,
        allow_entry_order_cancel=allow_entry_order_cancel,
        allow_exit_orders=allow_exit_orders,
        allow_reduce_only_orders=allow_reduce_only_orders,
        allow_exit_order_cancel=allow_exit_order_cancel,
        allow_emergency_close=allow_emergency_close,
        allow_reconciliation=False,
        guardian_required=False,
        manual_intervention_required=False,
        reason=OrderFlowPermissionReason.OK,
    )


def _order(  # noqa: PLR0913
    kind: OrderIntentKind = OrderIntentKind.ENTRY,
    *,
    venue_id: str = "venue-1",
    instrument_id: str = "BTC-PERP",
    account_id: str | None = "acct-1",
    side: OrderSide | None = None,
    position_side: PositionSide = PositionSide.LONG,
    order_type: OrderType = OrderType.MARKET,
    stop_price: str | None = None,
) -> OrderIntent:
    return OrderIntent(
        intent_kind=kind,
        venue_id=venue_id,
        instrument_id=instrument_id,
        account_id=account_id,
        side=side or (OrderSide.BUY if kind is OrderIntentKind.ENTRY else OrderSide.SELL),
        position_side=position_side,
        order_type=order_type,
        quantity="1",
        stop_price=stop_price,
        reduce_only=kind is not OrderIntentKind.ENTRY,
        post_only=False,
        close_position=False,
        permission_reason=OrderFlowPermissionReason.OK,
        created_at=NOW,
    )


def _protective(  # noqa: PLR0913
    instrument_id: str = "ETH-PERP",
    *,
    venue_id: str = "venue-1",
    account_id: str | None = "acct-1",
    side: OrderSide = OrderSide.SELL,
    position_side: PositionSide = PositionSide.LONG,
    stop_price: str = "95",
) -> OrderIntent:
    return _order(
        OrderIntentKind.PROTECTIVE_STOP,
        venue_id=venue_id,
        instrument_id=instrument_id,
        account_id=account_id,
        side=side,
        position_side=position_side,
        order_type=OrderType.STOP_MARKET,
        stop_price=stop_price,
    )


def _coordinator() -> tuple[
    DeterministicExecutionManagerCoordinator,
    InMemoryExecutionOrderRecordStore,
    InMemoryExecutionReconciliationStore,
]:
    records = InMemoryExecutionOrderRecordStore()
    reconciliation = InMemoryExecutionReconciliationStore()
    coordinator = DeterministicExecutionManagerCoordinator(
        intent_journal=InMemoryOrderIntentJournal(),
        lifecycle_event_store=InMemoryOrderLifecycleEventStore(),
        order_record_store=records,
        reconciliation_store=reconciliation,
    )
    return coordinator, records, reconciliation


def _order_request(order: OrderIntent) -> ExecutionAdmissionRequest:
    return ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order,
        order_flow_permission=_permission(),
        requested_at=NOW,
        requested_by="unit-test",
    )


def _cancel_request(
    cancel: CancelOrderIntent,
    permission: OrderFlowPermission,
) -> ExecutionAdmissionRequest:
    return ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.CANCEL_INTENT,
        cancel_intent=cancel,
        order_flow_permission=permission,
        requested_at=NOW,
        requested_by="unit-test",
    )


def _replace_request(
    replace: ReplaceOrderIntent,
    permission: OrderFlowPermission,
) -> ExecutionAdmissionRequest:
    return ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.REPLACE_INTENT,
        replace_intent=replace,
        order_flow_permission=permission,
        requested_at=NOW,
        requested_by="unit-test",
    )


def _cancel(target: ClientOrderId) -> CancelOrderIntent:
    return CancelOrderIntent(
        target_client_order_id=target,
        venue_id="venue-1",
        instrument_id="BTC-PERP",
        account_id="acct-1",
        cancel_scope=CancelScope.SINGLE_ORDER,
        cancel_reason="cancel requested",
        created_at=NOW,
    )


def _replace(target: OrderIntent, replacement: OrderIntent) -> ReplaceOrderIntent:
    assert target.client_order_id is not None
    return ReplaceOrderIntent(
        target_client_order_id=target.client_order_id,
        target_intent_kind=target.intent_kind,
        replacement_order=replacement,
        replace_reason="replace requested",
        created_at=NOW,
    )


def test_allowed_cancel_updates_active_record_to_cancel_requested() -> None:
    coordinator, records, _ = _coordinator()
    order = _order()
    assert order.client_order_id is not None
    coordinator.admit(_order_request(order))

    decision = coordinator.admit(_cancel_request(_cancel(order.client_order_id), _permission()))

    record = records.get_by_client_order_id(order.client_order_id)
    assert decision.accepted
    assert record is not None
    assert record.lifecycle_state is OrderLifecycleState.CANCEL_REQUESTED


def test_blocked_cancel_does_not_update_record() -> None:
    coordinator, records, _ = _coordinator()
    order = _order()
    assert order.client_order_id is not None
    coordinator.admit(_order_request(order))

    decision = coordinator.admit(
        _cancel_request(_cancel(order.client_order_id), _permission(allow_entry_order_cancel=False))
    )

    record = records.get_by_client_order_id(order.client_order_id)
    assert not decision.accepted
    assert record is not None
    assert record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


def test_cancel_unknown_target_creates_reconciliation_marker() -> None:
    coordinator, _, reconciliation = _coordinator()
    cancel = _cancel(ClientOrderId("missing-client"))

    decision = coordinator.admit(_cancel_request(cancel, _permission()))

    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.RECONCILIATION_REQUIRED
    assert decision.reconciliation_marker_ids
    assert reconciliation.get(decision.reconciliation_marker_ids[0]) is not None


def test_cancel_terminal_filled_record_rejected() -> None:
    coordinator, records, _ = _coordinator()
    order = _order()
    assert order.client_order_id is not None
    coordinator.admit(_order_request(order))
    record = records.get_by_client_order_id(order.client_order_id)
    assert record is not None
    records.upsert(record.model_copy(update={"lifecycle_state": OrderLifecycleState.FILLED}))

    decision = coordinator.admit(_cancel_request(_cancel(order.client_order_id), _permission()))

    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.TARGET_ORDER_NOT_ACTIVE


def test_entry_cancel_uses_allow_entry_order_cancel() -> None:
    coordinator, _, _ = _coordinator()
    order = _order()
    assert order.client_order_id is not None
    coordinator.admit(_order_request(order))

    decision = coordinator.admit(
        _cancel_request(_cancel(order.client_order_id), _permission(allow_entry_order_cancel=False))
    )

    assert not decision.accepted


def test_exit_cancel_uses_allow_exit_order_cancel() -> None:
    coordinator, _, _ = _coordinator()
    order = _order(OrderIntentKind.EXIT)
    assert order.client_order_id is not None
    coordinator.admit(_order_request(order))

    decision = coordinator.admit(
        _cancel_request(_cancel(order.client_order_id), _permission(allow_exit_order_cancel=False))
    )

    assert not decision.accepted


def test_allowed_protective_replace_marks_target_and_creates_replacement_record() -> None:
    coordinator, records, _ = _coordinator()
    target = _protective("ETH-PERP")
    replacement = _protective("ETH-PERP", stop_price="94")
    assert target.client_order_id is not None
    assert replacement.client_order_id is not None
    coordinator.admit(_order_request(target))

    decision = coordinator.admit(_replace_request(_replace(target, replacement), _permission()))

    target_record = records.get_by_client_order_id(target.client_order_id)
    replacement_record = records.get_by_client_order_id(replacement.client_order_id)
    assert decision.accepted
    assert target_record is not None
    assert target_record.lifecycle_state is OrderLifecycleState.REPLACE_REQUESTED
    assert replacement_record is not None
    assert replacement_record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


def test_blocked_replace_does_not_update_target_or_create_replacement() -> None:
    coordinator, records, _ = _coordinator()
    target = _protective("ETH-PERP")
    replacement = _protective("ETH-PERP", stop_price="94")
    assert target.client_order_id is not None
    assert replacement.client_order_id is not None
    coordinator.admit(_order_request(target))

    decision = coordinator.admit(
        _replace_request(
            _replace(target, replacement),
            _permission(allow_exit_orders=False, allow_reduce_only_orders=False),
        )
    )

    target_record = records.get_by_client_order_id(target.client_order_id)
    assert not decision.accepted
    assert target_record is not None
    assert target_record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
    assert records.get_by_client_order_id(replacement.client_order_id) is None


def test_replace_unknown_target_creates_reconciliation_marker() -> None:
    coordinator, _, reconciliation = _coordinator()
    target = _protective("ETH-PERP")
    replacement = _protective("ETH-PERP", stop_price="94")

    decision = coordinator.admit(
        _replace_request(_replace(target, replacement), _permission())
    )

    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.RECONCILIATION_REQUIRED
    assert decision.reconciliation_marker_ids
    assert reconciliation.get(decision.reconciliation_marker_ids[0]) is not None


def test_replace_terminal_filled_record_rejected() -> None:
    coordinator, records, _ = _coordinator()
    target = _protective("ETH-PERP")
    replacement = _protective("ETH-PERP", stop_price="94")
    assert target.client_order_id is not None
    coordinator.admit(_order_request(target))
    record = records.get_by_client_order_id(target.client_order_id)
    assert record is not None
    records.upsert(record.model_copy(update={"lifecycle_state": OrderLifecycleState.FILLED}))

    decision = coordinator.admit(
        _replace_request(_replace(target, replacement), _permission())
    )

    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.TARGET_ORDER_NOT_ACTIVE


def test_replace_cannot_bypass_review_108_permission_classes() -> None:
    coordinator, records, _ = _coordinator()
    target = _protective("ETH-PERP")
    emergency = _order(OrderIntentKind.EMERGENCY_CLOSE, instrument_id="ETH-PERP")
    assert target.client_order_id is not None
    assert emergency.client_order_id is not None
    coordinator.admit(_order_request(target))

    decision = coordinator.admit(
        _replace_request(
            _replace(target, emergency),
            _permission(
                allow_exit_orders=True,
                allow_reduce_only_orders=True,
                allow_emergency_close=False,
            ),
        )
    )

    target_record = records.get_by_client_order_id(target.client_order_id)
    assert not decision.accepted
    assert target_record is not None
    assert target_record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
    assert records.get_by_client_order_id(emergency.client_order_id) is None


def _assert_rejected_scope_mismatch_preserves_target(
    target: OrderIntent,
    replacement: OrderIntent,
) -> None:
    coordinator, records, _ = _coordinator()
    assert target.client_order_id is not None
    assert replacement.client_order_id is not None
    coordinator.admit(_order_request(target))

    decision = coordinator.admit(
        _replace_request(_replace(target, replacement), _permission())
    )

    target_record = records.get_by_client_order_id(target.client_order_id)
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VALIDATION
    assert target_record is not None
    assert target_record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
    assert records.get_by_client_order_id(replacement.client_order_id) is None


def test_replace_rejects_different_instrument() -> None:
    _assert_rejected_scope_mismatch_preserves_target(
        _protective("ETH-PERP"),
        _protective("SOL-PERP"),
    )


def test_replace_rejects_different_venue() -> None:
    _assert_rejected_scope_mismatch_preserves_target(
        _protective("ETH-PERP", venue_id="venue-1"),
        _protective("ETH-PERP", venue_id="venue-2"),
    )


def test_replace_rejects_different_account() -> None:
    _assert_rejected_scope_mismatch_preserves_target(
        _protective("ETH-PERP", account_id="acct-1"),
        _protective("ETH-PERP", account_id="acct-2"),
    )


def test_replace_rejects_different_position_side() -> None:
    _assert_rejected_scope_mismatch_preserves_target(
        _protective("ETH-PERP", position_side=PositionSide.LONG),
        _protective("ETH-PERP", position_side=PositionSide.SHORT),
    )


def test_replace_rejects_different_side() -> None:
    _assert_rejected_scope_mismatch_preserves_target(
        _protective("ETH-PERP", side=OrderSide.SELL),
        _protective("ETH-PERP", side=OrderSide.BUY),
    )


def test_replace_scope_mismatch_does_not_update_target_or_create_replacement_record() -> None:
    _assert_rejected_scope_mismatch_preserves_target(
        _protective("ETH-PERP"),
        _protective("SOL-PERP"),
    )


def test_replace_same_scope_still_allowed() -> None:
    coordinator, records, _ = _coordinator()
    target = _protective("ETH-PERP")
    replacement = _protective("ETH-PERP", stop_price="94")
    assert target.client_order_id is not None
    assert replacement.client_order_id is not None
    coordinator.admit(_order_request(target))

    decision = coordinator.admit(
        _replace_request(_replace(target, replacement), _permission())
    )

    target_record = records.get_by_client_order_id(target.client_order_id)
    replacement_record = records.get_by_client_order_id(replacement.client_order_id)
    assert decision.accepted
    assert target_record is not None
    assert target_record.lifecycle_state is OrderLifecycleState.REPLACE_REQUESTED
    assert replacement_record is not None
    assert replacement_record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
