from __future__ import annotations

from typing import Protocol

from futures_bot.domain.ids import (
    ClientOrderId,
    ExecutionOrderRecordId,
    ExecutionReconciliationId,
    FillReportId,
    OrderIntentId,
    OrderLifecycleEventId,
)
from futures_bot.domain.order_lifecycle import (
    CancelOrderIntent,
    ExecutionOrderRecord,
    ExecutionReconciliationMarker,
    FillReport,
    OrderIntent,
    OrderLifecycleEvent,
    OrderLifecycleState,
    ReplaceOrderIntent,
)
from futures_bot.domain.runtime_control import OrderFlowPermission
from futures_bot.order_lifecycle.policies import OrderIntentPermissionDecision


class OrderIntentJournalPort(Protocol):
    """Pure journal interface for order intents proposed to execution."""

    def append_order_intent(self, intent: OrderIntent) -> None:
        """Append an order intent idempotently."""
        ...

    def append_cancel_intent(self, intent: CancelOrderIntent) -> None:
        """Append a cancel intent idempotently."""
        ...

    def append_replace_intent(self, intent: ReplaceOrderIntent) -> None:
        """Append a replace intent idempotently."""
        ...

    def get_order_intent(self, intent_id: OrderIntentId) -> OrderIntent | None:
        """Return an order intent by ID, or None."""
        ...


class OrderLifecycleEventStorePort(Protocol):
    """Pure append-only lifecycle event store interface."""

    def append(self, event: OrderLifecycleEvent) -> None:
        """Append a lifecycle event idempotently."""
        ...

    def list_events(self) -> tuple[OrderLifecycleEvent, ...]:
        """Return events in append order."""
        ...

    def get(self, event_id: OrderLifecycleEventId) -> OrderLifecycleEvent | None:
        """Return one lifecycle event by ID, or None."""
        ...


class ExecutionOrderRecordStorePort(Protocol):
    """Pure execution-owned order record store interface."""

    def upsert(self, record: ExecutionOrderRecord) -> None:
        """Insert or replace a record for the same record ID."""
        ...

    def get(self, record_id: ExecutionOrderRecordId) -> ExecutionOrderRecord | None:
        """Return an execution order record by ID, or None."""
        ...

    def get_by_client_order_id(
        self,
        client_order_id: ClientOrderId,
    ) -> ExecutionOrderRecord | None:
        """Return an execution order record by client order ID, or None."""
        ...


class FillReportStorePort(Protocol):
    """Pure fill report store interface."""

    def put(self, fill_report: FillReport) -> None:
        """Store a fill report idempotently."""
        ...

    def get(self, fill_report_id: FillReportId) -> FillReport | None:
        """Return a fill report by ID, or None."""
        ...


class ExecutionReconciliationStorePort(Protocol):
    """Pure reconciliation marker store interface."""

    def put(self, marker: ExecutionReconciliationMarker) -> None:
        """Store a reconciliation marker idempotently."""
        ...

    def get(
        self,
        reconciliation_id: ExecutionReconciliationId,
    ) -> ExecutionReconciliationMarker | None:
        """Return a reconciliation marker by ID, or None."""
        ...


class OrderIntentPermissionEvaluatorPort(Protocol):
    """Pure permission evaluator interface."""

    def evaluate_order_intent_permission(
        self,
        order_intent: OrderIntent,
        order_flow_permission: OrderFlowPermission,
    ) -> OrderIntentPermissionDecision:
        """Evaluate whether an order intent may proceed."""
        ...

    def evaluate_cancel_intent_permission(
        self,
        cancel_intent: CancelOrderIntent,
        *,
        target_is_entry_flow: bool,
        order_flow_permission: OrderFlowPermission,
    ) -> OrderIntentPermissionDecision:
        """Evaluate whether a cancel intent may proceed."""
        ...

    def evaluate_replace_intent_permission(
        self,
        replace_intent: ReplaceOrderIntent,
        *,
        target_is_entry_flow: bool,
        order_flow_permission: OrderFlowPermission,
    ) -> OrderIntentPermissionDecision:
        """Evaluate whether a replace intent may proceed."""
        ...


class OrderLifecycleTransitionValidatorPort(Protocol):
    """Pure lifecycle transition validator interface."""

    def validate_order_lifecycle_transition(
        self,
        previous_state: OrderLifecycleState | None,
        next_state: OrderLifecycleState,
    ) -> None:
        """Raise if the lifecycle transition is not allowed."""
        ...
