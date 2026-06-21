from __future__ import annotations

from datetime import UTC, datetime

from futures_bot.domain.order_lifecycle import (
    CancelOrderIntent,
    CancelScope,
    OrderIntent,
    OrderIntentKind,
    OrderSide,
    OrderType,
    PositionSide,
    ReplaceOrderIntent,
)
from futures_bot.domain.runtime_control import (
    OrderFlowPermission,
    OrderFlowPermissionReason,
)
from futures_bot.order_lifecycle.policies import (
    OrderIntentPermissionDecisionReason,
    evaluate_cancel_intent_permission,
    evaluate_order_intent_permission,
    evaluate_replace_intent_permission,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _permission(  # noqa: PLR0913
    *,
    allow_new_entries: bool = True,
    allow_entry_order_cancel: bool = True,
    allow_exit_orders: bool = True,
    allow_reduce_only_orders: bool = True,
    allow_exit_order_cancel: bool = True,
    allow_emergency_close: bool = True,
    allow_reconciliation: bool = False,
    guardian_required: bool = False,
    manual_intervention_required: bool = False,
) -> OrderFlowPermission:
    return OrderFlowPermission(
        allow_new_entries=allow_new_entries,
        allow_entry_order_cancel=allow_entry_order_cancel,
        allow_exit_orders=allow_exit_orders,
        allow_reduce_only_orders=allow_reduce_only_orders,
        allow_exit_order_cancel=allow_exit_order_cancel,
        allow_emergency_close=allow_emergency_close,
        allow_reconciliation=allow_reconciliation,
        guardian_required=guardian_required,
        manual_intervention_required=manual_intervention_required,
        reason=OrderFlowPermissionReason.OK,
    )


def _intent(  # noqa: PLR0913
    kind: OrderIntentKind,
    *,
    order_type: OrderType = OrderType.MARKET,
    reduce_only: bool = False,
    close_position: bool = False,
    stop_price: str | None = None,
    limit_price: str | None = None,
) -> OrderIntent:
    return OrderIntent(
        intent_kind=kind,
        venue_id="venue-1",
        instrument_id="BTC-PERP",
        account_id="acct-1",
        side=OrderSide.SELL if kind is not OrderIntentKind.ENTRY else OrderSide.BUY,
        position_side=PositionSide.LONG,
        order_type=order_type,
        quantity=None if close_position else "1",
        limit_price=limit_price,
        stop_price=stop_price,
        reduce_only=reduce_only,
        post_only=False,
        close_position=close_position,
        permission_reason=OrderFlowPermissionReason.OK,
        created_at=NOW,
    )


def _entry() -> OrderIntent:
    return _intent(OrderIntentKind.ENTRY)


def _exit() -> OrderIntent:
    return _intent(OrderIntentKind.EXIT, reduce_only=True)


def _reduce() -> OrderIntent:
    return _intent(OrderIntentKind.REDUCE_ONLY, reduce_only=True)


def _protective_stop() -> OrderIntent:
    return _intent(
        OrderIntentKind.PROTECTIVE_STOP,
        order_type=OrderType.STOP_MARKET,
        reduce_only=True,
        stop_price="95",
    )


def _emergency_close() -> OrderIntent:
    return _intent(OrderIntentKind.EMERGENCY_CLOSE, close_position=True)


def _cancel() -> CancelOrderIntent:
    return CancelOrderIntent(
        target_client_order_id=_entry().client_order_id,
        venue_id="venue-1",
        instrument_id="BTC-PERP",
        account_id="acct-1",
        cancel_scope=CancelScope.SINGLE_ORDER,
        cancel_reason="cancel requested",
        created_at=NOW,
    )


def _replace(
    replacement_order: OrderIntent,
    *,
    target_intent_kind: OrderIntentKind | None = None,
) -> ReplaceOrderIntent:
    return ReplaceOrderIntent(
        target_client_order_id=_entry().client_order_id,
        target_intent_kind=target_intent_kind or replacement_order.intent_kind,
        replacement_order=replacement_order,
        replace_reason="replace requested",
        created_at=NOW,
    )


def test_entry_allowed_only_when_allow_new_entries_true() -> None:
    allowed = evaluate_order_intent_permission(_entry(), _permission())
    blocked = evaluate_order_intent_permission(
        _entry(),
        _permission(allow_new_entries=False),
    )

    assert allowed.allowed
    assert blocked.reason is OrderIntentPermissionDecisionReason.ENTRY_BLOCKED


def test_entry_blocked_when_runtime_permission_blocks_entries() -> None:
    decision = evaluate_order_intent_permission(
        _entry(),
        _permission(allow_new_entries=False),
    )
    assert not decision.allowed


def test_exit_allowed_when_entries_blocked_but_exit_orders_allowed() -> None:
    decision = evaluate_order_intent_permission(
        _exit(),
        _permission(allow_new_entries=False, allow_exit_orders=True),
    )
    assert decision.allowed


def test_reduce_only_allowed_when_allow_reduce_only_orders_true() -> None:
    decision = evaluate_order_intent_permission(
        _reduce(),
        _permission(allow_reduce_only_orders=True),
    )
    assert decision.allowed


def test_emergency_close_allowed_only_when_allow_emergency_close_true() -> None:
    allowed = evaluate_order_intent_permission(
        _emergency_close(),
        _permission(allow_emergency_close=True),
    )
    blocked = evaluate_order_intent_permission(
        _emergency_close(),
        _permission(allow_emergency_close=False),
    )

    assert allowed.allowed
    assert blocked.reason is OrderIntentPermissionDecisionReason.EMERGENCY_CLOSE_BLOCKED


def test_protective_stop_allowed_via_exit_or_reduce_permission() -> None:
    via_exit = evaluate_order_intent_permission(
        _protective_stop(),
        _permission(allow_exit_orders=True, allow_reduce_only_orders=False),
    )
    via_reduce = evaluate_order_intent_permission(
        _protective_stop(),
        _permission(allow_exit_orders=False, allow_reduce_only_orders=True),
    )

    assert via_exit.allowed
    assert via_reduce.allowed


def test_entry_cancel_uses_allow_entry_order_cancel() -> None:
    decision = evaluate_cancel_intent_permission(
        _cancel(),
        target_is_entry_flow=True,
        order_flow_permission=_permission(allow_entry_order_cancel=False),
    )
    assert not decision.allowed
    assert decision.reason is OrderIntentPermissionDecisionReason.CANCEL_BLOCKED


def test_exit_protective_cancel_uses_allow_exit_order_cancel() -> None:
    decision = evaluate_cancel_intent_permission(
        _cancel(),
        target_is_entry_flow=False,
        order_flow_permission=_permission(allow_exit_order_cancel=False),
    )
    assert not decision.allowed
    assert decision.reason is OrderIntentPermissionDecisionReason.CANCEL_BLOCKED


def test_replace_policy_rejects_non_entry_target_replaced_by_entry() -> None:
    replacement = _entry()
    replace = ReplaceOrderIntent.model_construct(
        target_client_order_id=_entry().client_order_id,
        target_intent_kind=OrderIntentKind.PROTECTIVE_STOP,
        replacement_order=replacement,
        replace_reason="unsafe replace",
        created_at=NOW,
    )

    decision = evaluate_replace_intent_permission(
        replace,
        target_is_entry_flow=False,
        order_flow_permission=_permission(
            allow_new_entries=False,
            allow_exit_orders=True,
            allow_reduce_only_orders=True,
            guardian_required=True,
        ),
    )

    assert not decision.allowed
    assert decision.reason is OrderIntentPermissionDecisionReason.REPLACE_BLOCKED


def test_replace_policy_rejects_target_flow_kind_mismatch_entry_target_marked_non_entry() -> None:
    decision = evaluate_replace_intent_permission(
        _replace(_entry(), target_intent_kind=OrderIntentKind.ENTRY),
        target_is_entry_flow=False,
        order_flow_permission=_permission(),
    )
    assert not decision.allowed
    assert decision.reason is OrderIntentPermissionDecisionReason.REPLACE_BLOCKED


def test_replace_policy_rejects_target_flow_kind_mismatch_non_entry_target_marked_entry() -> None:
    decision = evaluate_replace_intent_permission(
        _replace(_protective_stop(), target_intent_kind=OrderIntentKind.PROTECTIVE_STOP),
        target_is_entry_flow=True,
        order_flow_permission=_permission(),
    )
    assert not decision.allowed
    assert decision.reason is OrderIntentPermissionDecisionReason.REPLACE_BLOCKED


def test_replace_entry_target_allowed_when_entries_allowed() -> None:
    decision = evaluate_replace_intent_permission(
        _replace(_entry(), target_intent_kind=OrderIntentKind.ENTRY),
        target_is_entry_flow=True,
        order_flow_permission=_permission(allow_new_entries=True),
    )
    assert decision.allowed


def test_replace_entry_blocked_when_entries_blocked() -> None:
    decision = evaluate_replace_intent_permission(
        _replace(_entry(), target_intent_kind=OrderIntentKind.ENTRY),
        target_is_entry_flow=True,
        order_flow_permission=_permission(allow_new_entries=False),
    )
    assert not decision.allowed
    assert decision.reason is OrderIntentPermissionDecisionReason.REPLACE_BLOCKED


def test_replace_entry_target_blocked_when_guardian_required() -> None:
    decision = evaluate_replace_intent_permission(
        _replace(_entry(), target_intent_kind=OrderIntentKind.ENTRY),
        target_is_entry_flow=True,
        order_flow_permission=_permission(allow_new_entries=True, guardian_required=True),
    )
    assert not decision.allowed
    assert decision.reason is OrderIntentPermissionDecisionReason.REPLACE_BLOCKED


def test_replace_exit_requires_exit_permission_even_if_reduce_permission_true() -> None:
    decision = evaluate_replace_intent_permission(
        _replace(_exit(), target_intent_kind=OrderIntentKind.PROTECTIVE_STOP),
        target_is_entry_flow=False,
        order_flow_permission=_permission(
            allow_exit_orders=False,
            allow_reduce_only_orders=True,
        ),
    )
    assert not decision.allowed
    assert decision.reason is OrderIntentPermissionDecisionReason.REPLACE_BLOCKED


def test_replace_reduce_only_requires_reduce_permission_even_if_exit_permission_true() -> None:
    decision = evaluate_replace_intent_permission(
        _replace(_reduce(), target_intent_kind=OrderIntentKind.PROTECTIVE_STOP),
        target_is_entry_flow=False,
        order_flow_permission=_permission(
            allow_exit_orders=True,
            allow_reduce_only_orders=False,
        ),
    )
    assert not decision.allowed
    assert decision.reason is OrderIntentPermissionDecisionReason.REPLACE_BLOCKED


def test_replace_emergency_close_requires_emergency_close_permission() -> None:
    decision = evaluate_replace_intent_permission(
        _replace(_emergency_close(), target_intent_kind=OrderIntentKind.PROTECTIVE_STOP),
        target_is_entry_flow=False,
        order_flow_permission=_permission(
            allow_exit_orders=True,
            allow_reduce_only_orders=True,
            allow_emergency_close=False,
        ),
    )
    assert not decision.allowed
    assert decision.reason is OrderIntentPermissionDecisionReason.REPLACE_BLOCKED


def test_replace_emergency_close_allowed_when_emergency_close_permission_true() -> None:
    decision = evaluate_replace_intent_permission(
        _replace(_emergency_close(), target_intent_kind=OrderIntentKind.PROTECTIVE_STOP),
        target_is_entry_flow=False,
        order_flow_permission=_permission(allow_emergency_close=True),
    )
    assert decision.allowed


def test_replace_protective_stop_allowed_when_exit_permission_true() -> None:
    decision = evaluate_replace_intent_permission(
        _replace(_protective_stop(), target_intent_kind=OrderIntentKind.PROTECTIVE_STOP),
        target_is_entry_flow=False,
        order_flow_permission=_permission(
            allow_exit_orders=True,
            allow_reduce_only_orders=False,
        ),
    )
    assert decision.allowed


def test_replace_protective_stop_allowed_when_reduce_permission_true() -> None:
    decision = evaluate_replace_intent_permission(
        _replace(_protective_stop(), target_intent_kind=OrderIntentKind.PROTECTIVE_STOP),
        target_is_entry_flow=False,
        order_flow_permission=_permission(
            allow_exit_orders=False,
            allow_reduce_only_orders=True,
        ),
    )
    assert decision.allowed


def test_replace_protective_stop_blocked_when_exit_and_reduce_permissions_false() -> None:
    decision = evaluate_replace_intent_permission(
        _replace(_protective_stop(), target_intent_kind=OrderIntentKind.PROTECTIVE_STOP),
        target_is_entry_flow=False,
        order_flow_permission=_permission(
            allow_exit_orders=False,
            allow_reduce_only_orders=False,
        ),
    )
    assert not decision.allowed
    assert decision.reason is OrderIntentPermissionDecisionReason.REPLACE_BLOCKED


def test_replace_protective_target_allowed_when_exit_or_reduce_allowed() -> None:
    decision = evaluate_replace_intent_permission(
        _replace(_protective_stop(), target_intent_kind=OrderIntentKind.PROTECTIVE_STOP),
        target_is_entry_flow=False,
        order_flow_permission=_permission(
            allow_new_entries=False,
            allow_exit_orders=False,
            allow_reduce_only_orders=True,
        ),
    )
    assert decision.allowed


def test_guardian_required_blocks_entry_but_allows_reduce_protection_by_permission() -> None:
    permission = _permission(
        allow_new_entries=True,
        guardian_required=True,
        allow_reduce_only_orders=True,
    )
    entry = evaluate_order_intent_permission(_entry(), permission)
    reduce = evaluate_order_intent_permission(_reduce(), permission)
    protective = evaluate_order_intent_permission(_protective_stop(), permission)

    assert not entry.allowed
    assert reduce.allowed
    assert protective.allowed
    assert reduce.requires_guardian


def test_manual_intervention_required_blocks_normal_entry_replace() -> None:
    permission = _permission(manual_intervention_required=True)

    entry = evaluate_order_intent_permission(_entry(), permission)
    replace = evaluate_replace_intent_permission(
        _replace(_exit(), target_intent_kind=OrderIntentKind.EXIT),
        target_is_entry_flow=False,
        order_flow_permission=permission,
    )

    assert entry.reason is OrderIntentPermissionDecisionReason.MANUAL_INTERVENTION_REQUIRED
    assert replace.reason is OrderIntentPermissionDecisionReason.MANUAL_INTERVENTION_REQUIRED
