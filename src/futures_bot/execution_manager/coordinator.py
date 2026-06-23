from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from futures_bot.domain.execution_capability_gate import ExecutionCapabilityCheck
from futures_bot.domain.execution_manager import (
    ExecutionAdmissionDecision,
    ExecutionAdmissionDecisionReason,
    ExecutionAdmissionRequest,
    ExecutionAdmissionRequestKind,
)
from futures_bot.domain.ids import (
    ClientOrderId,
    ExecutionOrderRecordId,
    ExecutionReconciliationId,
    OrderLifecycleEventId,
)
from futures_bot.domain.order_lifecycle import (
    CancelOrderIntent,
    ExecutionOrderRecord,
    ExecutionReconciliationMarker,
    OrderIntent,
    OrderIntentKind,
    OrderLifecycleEvent,
    OrderLifecycleEventKind,
    OrderLifecycleState,
    ReconciliationReason,
    ReplaceOrderIntent,
    canonical_payload_hash,
)
from futures_bot.domain.runtime_control import RuntimeDataScopeKind
from futures_bot.execution_manager.capability_gate import DeterministicExecutionCapabilityGate
from futures_bot.order_lifecycle.policies import (
    evaluate_cancel_intent_permission,
    evaluate_order_intent_permission,
    evaluate_replace_intent_permission,
)
from futures_bot.ports.execution_manager import (
    ExecutionAdmissionDecisionStorePort,
    ExecutionCoordinatorEventStorePort,
)
from futures_bot.ports.order_lifecycle import (
    ExecutionOrderRecordStorePort,
    ExecutionReconciliationStorePort,
    OrderIntentJournalPort,
    OrderLifecycleEventStorePort,
)

_ACTIVE_TARGET_STATES = frozenset(
    {
        OrderLifecycleState.ACCEPTED_BY_EXECUTION,
        OrderLifecycleState.SUBMISSION_REQUESTED,
        OrderLifecycleState.SUBMITTED_TO_VENUE,
        OrderLifecycleState.ACKNOWLEDGED_BY_VENUE,
        OrderLifecycleState.PARTIALLY_FILLED,
    }
)


class DeterministicExecutionManagerCoordinator:
    """Local deterministic execution admission coordinator."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        intent_journal: OrderIntentJournalPort,
        lifecycle_event_store: OrderLifecycleEventStorePort,
        order_record_store: ExecutionOrderRecordStorePort,
        reconciliation_store: ExecutionReconciliationStorePort,
        admission_decision_store: ExecutionAdmissionDecisionStorePort | None = None,
        coordinator_event_store: ExecutionCoordinatorEventStorePort | None = None,
        capability_gate: DeterministicExecutionCapabilityGate | None = None,
    ) -> None:
        self._intent_journal = intent_journal
        self._lifecycle_events = lifecycle_event_store
        self._records = order_record_store
        self._reconciliation = reconciliation_store
        self._decisions = admission_decision_store
        self._coordinator_events = coordinator_event_store
        self._capability_gate = capability_gate or DeterministicExecutionCapabilityGate()

    def admit(
        self,
        request: ExecutionAdmissionRequest,
    ) -> ExecutionAdmissionDecision:
        if request.request_kind is ExecutionAdmissionRequestKind.ORDER_INTENT:
            if request.order_intent is None:
                raise ValueError("ORDER_INTENT request requires order_intent")
            decision = self._admit_order_intent(request, request.order_intent)
        elif request.request_kind is ExecutionAdmissionRequestKind.CANCEL_INTENT:
            if request.cancel_intent is None:
                raise ValueError("CANCEL_INTENT request requires cancel_intent")
            decision = self._admit_cancel_intent(request, request.cancel_intent)
        else:
            if request.replace_intent is None:
                raise ValueError("REPLACE_INTENT request requires replace_intent")
            decision = self._admit_replace_intent(request, request.replace_intent)
        self._store_decision(decision)
        return decision

    def _admit_order_intent(  # noqa: PLR0911
        self,
        request: ExecutionAdmissionRequest,
        order_intent: OrderIntent,
    ) -> ExecutionAdmissionDecision:
        if order_intent.client_order_id is None or order_intent.intent_id is None:
            raise ValueError("order intent deterministic IDs are required")
        existing = self._records.get_by_client_order_id(order_intent.client_order_id)
        if existing is not None:
            if existing.order_intent == order_intent:
                return self._decision(
                    request=request,
                    accepted=True,
                    reason=ExecutionAdmissionDecisionReason.IDEMPOTENT_REPLAY,
                    order_intent_id=order_intent.intent_id,
                    client_order_id=order_intent.client_order_id,
                    record_id=existing.record_id,
                    lifecycle_event_ids=(),
                )
            return self._decision(
                request=request,
                accepted=False,
                reason=ExecutionAdmissionDecisionReason.DUPLICATE_IDEMPOTENCY_KEY,
                order_intent_id=order_intent.intent_id,
                client_order_id=order_intent.client_order_id,
            )

        created_event = self._append_lifecycle_event(
            request=request,
            order_intent=order_intent,
            event_kind=OrderLifecycleEventKind.INTENT_CREATED,
            previous_state=None,
            next_state=OrderLifecycleState.CREATED,
            record_id=None,
            payload={"request_id": str(request.request_id), "stage": "intent_created"},
        )
        permission = evaluate_order_intent_permission(
            order_intent,
            request.order_flow_permission,
        )
        if not permission.allowed:
            rejected_event = self._append_lifecycle_event(
                request=request,
                order_intent=order_intent,
                event_kind=OrderLifecycleEventKind.REJECTED_BY_PERMISSION,
                previous_state=OrderLifecycleState.CREATED,
                next_state=OrderLifecycleState.REJECTED_BY_PERMISSION,
                record_id=None,
                payload={"permission_reason": permission.reason.value},
            )
            return self._decision(
                request=request,
                accepted=False,
                reason=ExecutionAdmissionDecisionReason.REJECTED_BY_PERMISSION,
                order_intent_id=order_intent.intent_id,
                client_order_id=order_intent.client_order_id,
                lifecycle_event_ids=(created_event.event_id, rejected_event.event_id),
            )

        accepted_venue_reason: str | None = None
        accepted_venue_details: Any = None

        if request.require_venue_capability_validation:
            ctx = request.venue_validation_context
            if ctx is None:
                return self._decision(
                    request=request,
                    accepted=False,
                    reason=ExecutionAdmissionDecisionReason.VENUE_CAPABILITY_CONTEXT_REQUIRED,
                    order_intent_id=order_intent.intent_id,
                    client_order_id=order_intent.client_order_id,
                    lifecycle_event_ids=(created_event.event_id,),
                )
            if ctx.order_intent != order_intent:
                rejected_event = self._append_lifecycle_event(
                    request=request,
                    order_intent=order_intent,
                    event_kind=OrderLifecycleEventKind.REJECTED_BY_VALIDATION,
                    previous_state=OrderLifecycleState.CREATED,
                    next_state=OrderLifecycleState.REJECTED_BY_VALIDATION,
                    record_id=None,
                    payload={
                        "request_id": str(request.request_id),
                        "validation_reason": "venue_capability_context_mismatch",
                    },
                )
                return self._decision(
                    request=request,
                    accepted=False,
                    reason=ExecutionAdmissionDecisionReason.VENUE_CAPABILITY_CONTEXT_MISMATCH,
                    order_intent_id=order_intent.intent_id,
                    client_order_id=order_intent.client_order_id,
                    lifecycle_event_ids=(created_event.event_id, rejected_event.event_id),
                    venue_validation_reason="VALIDATION_CONTEXT_MISMATCH",
                    venue_validation_details={"message": "order_intent mismatch with context"},
                )
            check = ExecutionCapabilityCheck(
                order_intent=order_intent,
                venue_validation_context=ctx,
                requested_at=request.requested_at,
                requested_by=request.requested_by,
                correlation_id=request.correlation_id,
            )
            gate_decision = self._capability_gate.check(check)
            if not gate_decision.executable:
                rejected_event = self._append_lifecycle_event(
                    request=request,
                    order_intent=order_intent,
                    event_kind=OrderLifecycleEventKind.REJECTED_BY_VALIDATION,
                    previous_state=OrderLifecycleState.CREATED,
                    next_state=OrderLifecycleState.REJECTED_BY_VALIDATION,
                    record_id=None,
                    payload={
                        "request_id": str(request.request_id),
                        "order_intent_id": str(order_intent.intent_id),
                        "client_order_id": str(order_intent.client_order_id),
                        "venue_validation_reason": gate_decision.venue_validation_reason,
                        "venue_validation_details": gate_decision.venue_validation_details,
                        "stage": "rejected_by_venue_capability",
                    },
                )
                return self._decision(
                    request=request,
                    accepted=False,
                    reason=ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY,
                    order_intent_id=order_intent.intent_id,
                    client_order_id=order_intent.client_order_id,
                    lifecycle_event_ids=(created_event.event_id, rejected_event.event_id),
                    venue_validation_reason=gate_decision.venue_validation_reason,
                    venue_validation_details=gate_decision.venue_validation_details,
                )
            accepted_venue_reason = gate_decision.venue_validation_reason
            accepted_venue_details = gate_decision.venue_validation_details

        self._intent_journal.append_order_intent(order_intent)
        record_id = deterministic_execution_order_record_id(order_intent)
        accepted_event = self._append_lifecycle_event(
            request=request,
            order_intent=order_intent,
            event_kind=OrderLifecycleEventKind.ACCEPTED_BY_EXECUTION,
            previous_state=OrderLifecycleState.CREATED,
            next_state=OrderLifecycleState.ACCEPTED_BY_EXECUTION,
            record_id=record_id,
            payload={"request_id": str(request.request_id), "stage": "accepted"},
        )
        record = self._new_record(
            record_id=record_id,
            order_intent=order_intent,
            state=OrderLifecycleState.ACCEPTED_BY_EXECUTION,
            event_id=accepted_event.event_id,
            at=request.requested_at,
        )
        self._records.upsert(record)
        return self._decision(
            request=request,
            accepted=True,
            reason=ExecutionAdmissionDecisionReason.ACCEPTED,
            order_intent_id=order_intent.intent_id,
            client_order_id=order_intent.client_order_id,
            record_id=record_id,
            lifecycle_event_ids=(created_event.event_id, accepted_event.event_id),
            venue_validation_reason=accepted_venue_reason,
            venue_validation_details=accepted_venue_details,
        )

    def _admit_cancel_intent(
        self,
        request: ExecutionAdmissionRequest,
        cancel_intent: CancelOrderIntent,
    ) -> ExecutionAdmissionDecision:
        target = self._resolve_cancel_target(cancel_intent)
        permission = evaluate_cancel_intent_permission(
            cancel_intent,
            target_is_entry_flow=_is_entry_record(target),
            order_flow_permission=request.order_flow_permission,
        )
        if not permission.allowed:
            event = self._append_rejection_for_target(
                request=request,
                target=target,
                kind=OrderLifecycleEventKind.REJECTED_BY_PERMISSION,
                payload={"permission_reason": permission.reason.value},
            )
            return self._decision(
                request=request,
                accepted=False,
                reason=ExecutionAdmissionDecisionReason.REJECTED_BY_PERMISSION,
                cancel_intent_id=cancel_intent.cancel_intent_id,
                lifecycle_event_ids=_event_ids(event),
            )
        if target is None:
            marker = self._mark_reconciliation(
                request=request,
                reason=ReconciliationReason.VENUE_ORDER_NOT_FOUND,
                scope_id=_cancel_target_scope(cancel_intent),
            )
            return self._decision(
                request=request,
                accepted=False,
                reason=ExecutionAdmissionDecisionReason.RECONCILIATION_REQUIRED,
                cancel_intent_id=cancel_intent.cancel_intent_id,
                reconciliation_marker_ids=(marker.reconciliation_id,),
            )
        if target.lifecycle_state not in _ACTIVE_TARGET_STATES:
            return self._decision(
                request=request,
                accepted=False,
                reason=ExecutionAdmissionDecisionReason.TARGET_ORDER_NOT_ACTIVE,
                cancel_intent_id=cancel_intent.cancel_intent_id,
                client_order_id=target.client_order_id,
                record_id=target.record_id,
            )
        self._intent_journal.append_cancel_intent(cancel_intent)
        event = self._append_lifecycle_event(
            request=request,
            order_intent=target.order_intent,
            event_kind=OrderLifecycleEventKind.CANCEL_REQUESTED,
            previous_state=target.lifecycle_state,
            next_state=OrderLifecycleState.CANCEL_REQUESTED,
            record_id=target.record_id,
            payload={"cancel_intent_id": str(cancel_intent.cancel_intent_id)},
        )
        self._records.upsert(
            target.model_copy(
                update={
                    "lifecycle_state": OrderLifecycleState.CANCEL_REQUESTED,
                    "last_lifecycle_event_id": event.event_id,
                    "updated_at": request.requested_at,
                }
            )
        )
        return self._decision(
            request=request,
            accepted=True,
            reason=ExecutionAdmissionDecisionReason.ACCEPTED,
            cancel_intent_id=cancel_intent.cancel_intent_id,
            client_order_id=target.client_order_id,
            record_id=target.record_id,
            lifecycle_event_ids=(event.event_id,),
        )

    def _admit_replace_intent(  # noqa: PLR0911
        self,
        request: ExecutionAdmissionRequest,
        replace_intent: ReplaceOrderIntent,
    ) -> ExecutionAdmissionDecision:
        target = self._resolve_replace_target(replace_intent)
        permission = evaluate_replace_intent_permission(
            replace_intent,
            target_is_entry_flow=_is_entry_record(target),
            order_flow_permission=request.order_flow_permission,
        )
        if not permission.allowed:
            event = self._append_rejection_for_target(
                request=request,
                target=target,
                kind=OrderLifecycleEventKind.REJECTED_BY_PERMISSION,
                payload={"permission_reason": permission.reason.value},
            )
            return self._decision(
                request=request,
                accepted=False,
                reason=ExecutionAdmissionDecisionReason.REJECTED_BY_PERMISSION,
                replace_intent_id=replace_intent.replace_intent_id,
                lifecycle_event_ids=_event_ids(event),
            )
        if target is None:
            marker = self._mark_reconciliation(
                request=request,
                reason=ReconciliationReason.VENUE_ORDER_NOT_FOUND,
                scope_id=_replace_target_scope(replace_intent),
            )
            return self._decision(
                request=request,
                accepted=False,
                reason=ExecutionAdmissionDecisionReason.RECONCILIATION_REQUIRED,
                replace_intent_id=replace_intent.replace_intent_id,
                reconciliation_marker_ids=(marker.reconciliation_id,),
            )
        if target.lifecycle_state not in _ACTIVE_TARGET_STATES:
            return self._decision(
                request=request,
                accepted=False,
                reason=ExecutionAdmissionDecisionReason.TARGET_ORDER_NOT_ACTIVE,
                replace_intent_id=replace_intent.replace_intent_id,
                client_order_id=target.client_order_id,
                record_id=target.record_id,
            )
        replacement = replace_intent.replacement_order
        if replacement.client_order_id is None or replacement.intent_id is None:
            raise ValueError("replacement order deterministic IDs are required")
        if not replacement_scope_matches_target(target, replacement):
            event = self._append_lifecycle_event(
                request=request,
                order_intent=target.order_intent,
                event_kind=OrderLifecycleEventKind.REJECTED_BY_VALIDATION,
                previous_state=OrderLifecycleState.CREATED,
                next_state=OrderLifecycleState.REJECTED_BY_VALIDATION,
                record_id=None,
                payload={
                    "replace_intent_id": str(replace_intent.replace_intent_id),
                    "validation_reason": "replacement_scope_mismatch",
                },
            )
            return self._decision(
                request=request,
                accepted=False,
                reason=ExecutionAdmissionDecisionReason.REJECTED_BY_VALIDATION,
                replace_intent_id=replace_intent.replace_intent_id,
                client_order_id=target.client_order_id,
                record_id=target.record_id,
                lifecycle_event_ids=(event.event_id,),
            )
        existing_replacement = self._records.get_by_client_order_id(
            replacement.client_order_id
        )
        if existing_replacement is not None and existing_replacement.order_intent != replacement:
            return self._decision(
                request=request,
                accepted=False,
                reason=ExecutionAdmissionDecisionReason.DUPLICATE_IDEMPOTENCY_KEY,
                replace_intent_id=replace_intent.replace_intent_id,
                client_order_id=replacement.client_order_id,
            )

        accepted_venue_reason: str | None = None
        accepted_venue_details: Any = None

        if request.require_venue_capability_validation:
            ctx = request.venue_validation_context
            if ctx is None:
                return self._decision(
                    request=request,
                    accepted=False,
                    reason=ExecutionAdmissionDecisionReason.VENUE_CAPABILITY_CONTEXT_REQUIRED,
                    replace_intent_id=replace_intent.replace_intent_id,
                    client_order_id=target.client_order_id,
                    record_id=target.record_id,
                )
            if ctx.order_intent != replacement:
                event = self._append_lifecycle_event(
                    request=request,
                    order_intent=target.order_intent,
                    event_kind=OrderLifecycleEventKind.REJECTED_BY_VALIDATION,
                    previous_state=OrderLifecycleState.CREATED,
                    next_state=OrderLifecycleState.REJECTED_BY_VALIDATION,
                    record_id=None,
                    payload={
                        "replace_intent_id": str(replace_intent.replace_intent_id),
                        "validation_reason": "venue_capability_context_mismatch",
                    },
                )
                return self._decision(
                    request=request,
                    accepted=False,
                    reason=ExecutionAdmissionDecisionReason.VENUE_CAPABILITY_CONTEXT_MISMATCH,
                    replace_intent_id=replace_intent.replace_intent_id,
                    client_order_id=target.client_order_id,
                    record_id=target.record_id,
                    lifecycle_event_ids=(event.event_id,),
                    venue_validation_reason="VALIDATION_CONTEXT_MISMATCH",
                    venue_validation_details={"message": "order_intent mismatch with context"},
                )
            check = ExecutionCapabilityCheck(
                order_intent=replacement,
                venue_validation_context=ctx,
                requested_at=request.requested_at,
                requested_by=request.requested_by,
                correlation_id=request.correlation_id,
            )
            gate_decision = self._capability_gate.check(check)
            if not gate_decision.executable:
                rejected_event = self._append_lifecycle_event(
                    request=request,
                    order_intent=target.order_intent,
                    event_kind=OrderLifecycleEventKind.REJECTED_BY_VALIDATION,
                    previous_state=OrderLifecycleState.CREATED,
                    next_state=OrderLifecycleState.REJECTED_BY_VALIDATION,
                    record_id=None,
                    payload={
                        "replace_intent_id": str(replace_intent.replace_intent_id),
                        "order_intent_id": str(replacement.intent_id),
                        "client_order_id": str(replacement.client_order_id),
                        "venue_validation_reason": gate_decision.venue_validation_reason,
                        "venue_validation_details": gate_decision.venue_validation_details,
                        "stage": "rejected_by_venue_capability",
                    },
                )
                return self._decision(
                    request=request,
                    accepted=False,
                    reason=ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY,
                    replace_intent_id=replace_intent.replace_intent_id,
                    client_order_id=target.client_order_id,
                    record_id=target.record_id,
                    lifecycle_event_ids=(rejected_event.event_id,),
                    venue_validation_reason=gate_decision.venue_validation_reason,
                    venue_validation_details=gate_decision.venue_validation_details,
                )
            accepted_venue_reason = gate_decision.venue_validation_reason
            accepted_venue_details = gate_decision.venue_validation_details

        self._intent_journal.append_replace_intent(replace_intent)
        target_event = self._append_lifecycle_event(
            request=request,
            order_intent=target.order_intent,
            event_kind=OrderLifecycleEventKind.REPLACE_REQUESTED,
            previous_state=target.lifecycle_state,
            next_state=OrderLifecycleState.REPLACE_REQUESTED,
            record_id=target.record_id,
            payload={"replace_intent_id": str(replace_intent.replace_intent_id)},
        )
        self._records.upsert(
            target.model_copy(
                update={
                    "lifecycle_state": OrderLifecycleState.REPLACE_REQUESTED,
                    "last_lifecycle_event_id": target_event.event_id,
                    "updated_at": request.requested_at,
                }
            )
        )
        self._intent_journal.append_order_intent(replacement)
        replacement_record_id = deterministic_execution_order_record_id(replacement)
        replacement_event = self._append_lifecycle_event(
            request=request,
            order_intent=replacement,
            event_kind=OrderLifecycleEventKind.ACCEPTED_BY_EXECUTION,
            previous_state=OrderLifecycleState.CREATED,
            next_state=OrderLifecycleState.ACCEPTED_BY_EXECUTION,
            record_id=replacement_record_id,
            payload={"replace_intent_id": str(replace_intent.replace_intent_id)},
        )
        self._records.upsert(
            self._new_record(
                record_id=replacement_record_id,
                order_intent=replacement,
                state=OrderLifecycleState.ACCEPTED_BY_EXECUTION,
                event_id=replacement_event.event_id,
                at=request.requested_at,
            )
        )
        return self._decision(
            request=request,
            accepted=True,
            reason=ExecutionAdmissionDecisionReason.ACCEPTED,
            replace_intent_id=replace_intent.replace_intent_id,
            client_order_id=replacement.client_order_id,
            record_id=replacement_record_id,
            lifecycle_event_ids=(target_event.event_id, replacement_event.event_id),
            venue_validation_reason=accepted_venue_reason,
            venue_validation_details=accepted_venue_details,
        )

    def _append_lifecycle_event(  # noqa: PLR0913
        self,
        *,
        request: ExecutionAdmissionRequest,
        order_intent: OrderIntent,
        event_kind: OrderLifecycleEventKind,
        previous_state: OrderLifecycleState | None,
        next_state: OrderLifecycleState,
        record_id: ExecutionOrderRecordId | None,
        payload: dict[str, Any],
    ) -> OrderLifecycleEvent:
        if order_intent.client_order_id is None:
            raise ValueError("order intent client_order_id is required")
        event = OrderLifecycleEvent(
            record_id=record_id,
            order_intent_id=order_intent.intent_id,
            client_order_id=order_intent.client_order_id,
            event_kind=event_kind,
            previous_state=previous_state,
            next_state=next_state,
            occurred_at=request.requested_at,
            payload=payload,
            payload_hash=canonical_payload_hash(payload),
        )
        self._lifecycle_events.append(event)
        return event

    def _append_rejection_for_target(
        self,
        *,
        request: ExecutionAdmissionRequest,
        target: ExecutionOrderRecord | None,
        kind: OrderLifecycleEventKind,
        payload: dict[str, Any],
    ) -> OrderLifecycleEvent | None:
        if target is None:
            return None
        return self._append_lifecycle_event(
            request=request,
            order_intent=target.order_intent,
            event_kind=kind,
            previous_state=OrderLifecycleState.CREATED,
            next_state=OrderLifecycleState.REJECTED_BY_PERMISSION,
            record_id=None,
            payload=payload,
        )

    def _mark_reconciliation(
        self,
        *,
        request: ExecutionAdmissionRequest,
        reason: ReconciliationReason,
        scope_id: str | None,
    ) -> ExecutionReconciliationMarker:
        marker = ExecutionReconciliationMarker(
            reconciliation_id=deterministic_reconciliation_id(
                request_id=str(request.request_id),
                reason=reason.value,
                scope_id=scope_id,
            ),
            scope_kind=RuntimeDataScopeKind.INSTRUMENT,
            scope_id=scope_id,
            reason=reason,
            required=True,
            created_at=request.requested_at,
        )
        self._reconciliation.put(marker)
        return marker

    def _resolve_cancel_target(
        self,
        cancel_intent: CancelOrderIntent,
    ) -> ExecutionOrderRecord | None:
        if cancel_intent.target_client_order_id is not None:
            return self._records.get_by_client_order_id(cancel_intent.target_client_order_id)
        if cancel_intent.target_order_intent_id is not None:
            intent = self._intent_journal.get_order_intent(
                cancel_intent.target_order_intent_id
            )
            if intent is not None and intent.client_order_id is not None:
                return self._records.get_by_client_order_id(intent.client_order_id)
        return None

    def _resolve_replace_target(
        self,
        replace_intent: ReplaceOrderIntent,
    ) -> ExecutionOrderRecord | None:
        if replace_intent.target_client_order_id is not None:
            return self._records.get_by_client_order_id(replace_intent.target_client_order_id)
        if replace_intent.target_order_intent_id is not None:
            intent = self._intent_journal.get_order_intent(
                replace_intent.target_order_intent_id
            )
            if intent is not None and intent.client_order_id is not None:
                return self._records.get_by_client_order_id(intent.client_order_id)
        return None

    def _new_record(
        self,
        *,
        record_id: ExecutionOrderRecordId,
        order_intent: OrderIntent,
        state: OrderLifecycleState,
        event_id: OrderLifecycleEventId | None,
        at: datetime,
    ) -> ExecutionOrderRecord:
        if order_intent.client_order_id is None:
            raise ValueError("order intent client_order_id is required")
        remaining_quantity = order_intent.quantity if order_intent.quantity is not None else None
        return ExecutionOrderRecord(
            record_id=record_id,
            order_intent=order_intent,
            lifecycle_state=state,
            client_order_id=order_intent.client_order_id,
            cumulative_filled_quantity=Decimal("0"),
            remaining_quantity=remaining_quantity,
            last_lifecycle_event_id=event_id,
            created_at=at,
            updated_at=at,
        )

    def _decision(  # noqa: PLR0913
        self,
        *,
        request: ExecutionAdmissionRequest,
        accepted: bool,
        reason: ExecutionAdmissionDecisionReason,
        order_intent_id: Any = None,
        cancel_intent_id: Any = None,
        replace_intent_id: Any = None,
        client_order_id: ClientOrderId | None = None,
        record_id: ExecutionOrderRecordId | None = None,
        lifecycle_event_ids: tuple[OrderLifecycleEventId | None, ...] = (),
        reconciliation_marker_ids: tuple[ExecutionReconciliationId, ...] = (),
        venue_validation_reason: str | None = None,
        venue_validation_details: Any = None,
    ) -> ExecutionAdmissionDecision:
        if request.request_id is None:
            raise ValueError("request_id is required")
        return ExecutionAdmissionDecision(
            request_id=request.request_id,
            request_kind=request.request_kind,
            accepted=accepted,
            reason=reason,
            order_intent_id=order_intent_id,
            cancel_intent_id=cancel_intent_id,
            replace_intent_id=replace_intent_id,
            client_order_id=client_order_id,
            record_id=record_id,
            lifecycle_event_ids=tuple(
                event_id for event_id in lifecycle_event_ids if event_id is not None
            ),
            reconciliation_marker_ids=reconciliation_marker_ids,
            venue_validation_reason=venue_validation_reason,
            venue_validation_details=venue_validation_details,
            decided_at=request.requested_at,
        )

    def _store_decision(self, decision: ExecutionAdmissionDecision) -> None:
        if self._decisions is not None:
            self._decisions.put(decision)


def deterministic_execution_order_record_id(
    order_intent: OrderIntent,
) -> ExecutionOrderRecordId:
    return ExecutionOrderRecordId(
        value=f"execution-record:{_digest(str(order_intent.intent_id))}"
    )


def deterministic_reconciliation_id(
    *,
    request_id: str,
    reason: str,
    scope_id: str | None,
) -> ExecutionReconciliationId:
    return ExecutionReconciliationId(
        value=f"exec-reconciliation:{_digest(json.dumps([request_id, reason, scope_id]))}"
    )


def _is_entry_record(record: ExecutionOrderRecord | None) -> bool:
    return record is not None and record.order_intent.intent_kind is OrderIntentKind.ENTRY


def replacement_scope_matches_target(
    target: ExecutionOrderRecord,
    replacement: OrderIntent,
) -> bool:
    target_intent = target.order_intent
    return (
        replacement.venue_id == target_intent.venue_id
        and replacement.instrument_id == target_intent.instrument_id
        and replacement.account_id == target_intent.account_id
        and replacement.position_side == target_intent.position_side
        and replacement.side == target_intent.side
    )


def _cancel_target_scope(cancel_intent: CancelOrderIntent) -> str | None:
    if cancel_intent.target_client_order_id is not None:
        return str(cancel_intent.target_client_order_id)
    if cancel_intent.target_venue_order_id is not None:
        return str(cancel_intent.target_venue_order_id)
    if cancel_intent.target_order_intent_id is not None:
        return str(cancel_intent.target_order_intent_id)
    return cancel_intent.instrument_id


def _replace_target_scope(replace_intent: ReplaceOrderIntent) -> str | None:
    if replace_intent.target_client_order_id is not None:
        return str(replace_intent.target_client_order_id)
    if replace_intent.target_venue_order_id is not None:
        return str(replace_intent.target_venue_order_id)
    if replace_intent.target_order_intent_id is not None:
        return str(replace_intent.target_order_intent_id)
    return None


def _event_ids(event: OrderLifecycleEvent | None) -> tuple[OrderLifecycleEventId | None, ...]:
    return () if event is None else (event.event_id,)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
