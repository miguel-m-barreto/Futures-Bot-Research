from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from futures_bot.domain.order_lifecycle import (
    CancelOrderIntent,
    OrderIntent,
    OrderIntentKind,
    ReplaceOrderIntent,
)
from futures_bot.domain.runtime_control import OrderFlowPermission


class OrderIntentPermissionDecisionReason(StrEnum):
    OK = "OK"
    ENTRY_BLOCKED = "ENTRY_BLOCKED"
    EXIT_BLOCKED = "EXIT_BLOCKED"
    REDUCE_ONLY_BLOCKED = "REDUCE_ONLY_BLOCKED"
    CANCEL_BLOCKED = "CANCEL_BLOCKED"
    EMERGENCY_CLOSE_BLOCKED = "EMERGENCY_CLOSE_BLOCKED"
    REPLACE_BLOCKED = "REPLACE_BLOCKED"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class OrderIntentPermissionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    reason: OrderIntentPermissionDecisionReason
    requires_guardian: bool
    requires_reconciliation: bool

    @model_validator(mode="after")
    def _validate_reason(self) -> Self:
        if self.allowed and self.reason is not OrderIntentPermissionDecisionReason.OK:
            raise ValueError("allowed decisions must use OK reason")
        if not self.allowed and self.reason is OrderIntentPermissionDecisionReason.OK:
            raise ValueError("blocked decisions must not use OK reason")
        return self


def evaluate_order_intent_permission(
    order_intent: OrderIntent,
    order_flow_permission: OrderFlowPermission,
) -> OrderIntentPermissionDecision:
    """Gate order intents without merging entry and protection permissions."""

    kind = order_intent.intent_kind
    if _manual_intervention_blocks(kind, order_flow_permission):
        return _blocked(
            OrderIntentPermissionDecisionReason.MANUAL_INTERVENTION_REQUIRED,
            order_flow_permission,
        )
    allowed, reason = _order_intent_allowed_and_reason(kind, order_flow_permission)
    return _allow_if(allowed, reason, order_flow_permission)


def _order_intent_allowed_and_reason(
    kind: OrderIntentKind,
    permission: OrderFlowPermission,
) -> tuple[bool, OrderIntentPermissionDecisionReason]:
    if kind is OrderIntentKind.ENTRY:
        return (
            permission.allow_new_entries and not permission.guardian_required,
            OrderIntentPermissionDecisionReason.ENTRY_BLOCKED,
        )
    if kind is OrderIntentKind.EXIT:
        return (
            permission.allow_exit_orders,
            OrderIntentPermissionDecisionReason.EXIT_BLOCKED,
        )
    if kind is OrderIntentKind.REDUCE_ONLY:
        return (
            permission.allow_reduce_only_orders,
            OrderIntentPermissionDecisionReason.REDUCE_ONLY_BLOCKED,
        )
    if kind in {
        OrderIntentKind.PROTECTIVE_STOP,
        OrderIntentKind.PROTECTIVE_TAKE_PROFIT,
    }:
        return (
            permission.allow_exit_orders or permission.allow_reduce_only_orders,
            OrderIntentPermissionDecisionReason.EXIT_BLOCKED,
        )
    return (
        permission.allow_emergency_close,
        OrderIntentPermissionDecisionReason.EMERGENCY_CLOSE_BLOCKED,
    )


def evaluate_cancel_intent_permission(
    cancel_intent: CancelOrderIntent,
    *,
    target_is_entry_flow: bool,
    order_flow_permission: OrderFlowPermission,
) -> OrderIntentPermissionDecision:
    """Gate cancel intents independently from new-entry permission."""

    _ = cancel_intent
    if order_flow_permission.manual_intervention_required:
        return _blocked(
            OrderIntentPermissionDecisionReason.MANUAL_INTERVENTION_REQUIRED,
            order_flow_permission,
        )
    allowed = (
        order_flow_permission.allow_entry_order_cancel
        if target_is_entry_flow
        else order_flow_permission.allow_exit_order_cancel
    )
    return _allow_if(
        allowed,
        OrderIntentPermissionDecisionReason.CANCEL_BLOCKED,
        order_flow_permission,
    )


def evaluate_replace_intent_permission(
    replace_intent: ReplaceOrderIntent,
    *,
    target_is_entry_flow: bool,
    order_flow_permission: OrderFlowPermission,
) -> OrderIntentPermissionDecision:
    """Gate replace intents by the target flow's safety class."""

    target_kind_is_entry = replace_intent.target_intent_kind is OrderIntentKind.ENTRY
    replacement_kind = replace_intent.replacement_order.intent_kind
    replacement_kind_is_entry = replacement_kind is OrderIntentKind.ENTRY
    if (
        target_is_entry_flow != target_kind_is_entry
        or target_is_entry_flow != replacement_kind_is_entry
    ):
        return _blocked(
            OrderIntentPermissionDecisionReason.REPLACE_BLOCKED,
            order_flow_permission,
        )
    if _manual_intervention_blocks(replacement_kind, order_flow_permission):
        return _blocked(
            OrderIntentPermissionDecisionReason.MANUAL_INTERVENTION_REQUIRED,
            order_flow_permission,
        )
    if target_is_entry_flow:
        if order_flow_permission.guardian_required:
            return _blocked(
                OrderIntentPermissionDecisionReason.REPLACE_BLOCKED,
                order_flow_permission,
            )
        return _allow_if(
            order_flow_permission.allow_new_entries,
            OrderIntentPermissionDecisionReason.REPLACE_BLOCKED,
            order_flow_permission,
        )
    allowed, _ = _order_intent_allowed_and_reason(replacement_kind, order_flow_permission)
    return _allow_if(
        allowed,
        OrderIntentPermissionDecisionReason.REPLACE_BLOCKED,
        order_flow_permission,
    )


def _manual_intervention_blocks(
    intent_kind: OrderIntentKind,
    permission: OrderFlowPermission,
) -> bool:
    return (
        permission.manual_intervention_required
        and intent_kind is not OrderIntentKind.EMERGENCY_CLOSE
    )


def _allow_if(
    allowed: bool,
    blocked_reason: OrderIntentPermissionDecisionReason,
    permission: OrderFlowPermission,
) -> OrderIntentPermissionDecision:
    if allowed:
        return OrderIntentPermissionDecision(
            allowed=True,
            reason=OrderIntentPermissionDecisionReason.OK,
            requires_guardian=permission.guardian_required,
            requires_reconciliation=permission.allow_reconciliation,
        )
    return _blocked(blocked_reason, permission)


def _blocked(
    reason: OrderIntentPermissionDecisionReason,
    permission: OrderFlowPermission,
) -> OrderIntentPermissionDecision:
    return OrderIntentPermissionDecision(
        allowed=False,
        reason=reason,
        requires_guardian=permission.guardian_required,
        requires_reconciliation=permission.allow_reconciliation,
    )
