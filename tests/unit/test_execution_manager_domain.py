from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.execution_manager import (
    ExecutionAdmissionDecision,
    ExecutionAdmissionDecisionReason,
    ExecutionAdmissionRequest,
    ExecutionAdmissionRequestKind,
    ExecutionCoordinatorEvent,
    ExecutionCoordinatorEventKind,
    canonical_payload_hash,
)
from futures_bot.domain.ids import ExecutionAdmissionRequestId
from futures_bot.domain.order_lifecycle import (
    OrderIntent,
    OrderIntentKind,
    OrderSide,
    OrderType,
    PositionSide,
)
from futures_bot.domain.runtime_control import (
    OrderFlowPermission,
    OrderFlowPermissionReason,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _permission() -> OrderFlowPermission:
    return OrderFlowPermission(
        allow_new_entries=True,
        allow_entry_order_cancel=True,
        allow_exit_orders=True,
        allow_reduce_only_orders=True,
        allow_exit_order_cancel=True,
        allow_emergency_close=True,
        allow_reconciliation=False,
        guardian_required=False,
        manual_intervention_required=False,
        reason=OrderFlowPermissionReason.OK,
    )


def _entry() -> OrderIntent:
    return OrderIntent(
        intent_kind=OrderIntentKind.ENTRY,
        venue_id="venue-1",
        instrument_id="BTC-PERP",
        account_id="acct-1",
        side=OrderSide.BUY,
        position_side=PositionSide.LONG,
        order_type=OrderType.MARKET,
        quantity="1",
        reduce_only=False,
        post_only=False,
        close_position=False,
        permission_reason=OrderFlowPermissionReason.OK,
        created_at=NOW,
    )


def _request() -> ExecutionAdmissionRequest:
    return ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=_entry(),
        order_flow_permission=_permission(),
        requested_at=NOW,
        requested_by="unit-test",
    )


def test_execution_admission_request_requires_exactly_one_matching_intent() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        ExecutionAdmissionRequest(
            request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
            order_flow_permission=_permission(),
            requested_at=NOW,
            requested_by="unit-test",
        )
    with pytest.raises(ValidationError, match="CANCEL_INTENT request requires"):
        ExecutionAdmissionRequest(
            request_kind=ExecutionAdmissionRequestKind.CANCEL_INTENT,
            order_intent=_entry(),
            order_flow_permission=_permission(),
            requested_at=NOW,
            requested_by="unit-test",
        )


def test_execution_admission_request_deterministic_request_id() -> None:
    first = _request()
    second = _request()

    assert first.request_id == second.request_id


def test_execution_admission_request_source_provenance_passed_requires_checked() -> None:
    with pytest.raises(ValidationError, match="source_provenance_passed=True"):
        ExecutionAdmissionRequest(
            request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
            order_intent=_entry(),
            order_flow_permission=_permission(),
            source_provenance_passed=True,
            requested_at=NOW,
            requested_by="unit-test",
        )


def test_execution_admission_request_source_provenance_required_requires_checked() -> None:
    with pytest.raises(ValidationError, match="source_provenance_required=True"):
        ExecutionAdmissionRequest(
            request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
            order_intent=_entry(),
            order_flow_permission=_permission(),
            source_provenance_required=True,
            requested_at=NOW,
            requested_by="unit-test",
        )


def test_execution_admission_decision_accepted_reason_consistency() -> None:
    request = _request()
    assert request.request_id is not None

    accepted = ExecutionAdmissionDecision(
        request_id=request.request_id,
        request_kind=request.request_kind,
        accepted=True,
        reason=ExecutionAdmissionDecisionReason.ACCEPTED,
        decided_at=NOW,
    )
    assert accepted.decision_id is not None

    with pytest.raises(ValidationError, match="accepted decisions"):
        ExecutionAdmissionDecision(
            request_id=request.request_id,
            request_kind=request.request_kind,
            accepted=True,
            reason=ExecutionAdmissionDecisionReason.REJECTED_BY_PERMISSION,
            decided_at=NOW,
        )
    with pytest.raises(ValidationError, match="rejected decisions"):
        ExecutionAdmissionDecision(
            request_id=request.request_id,
            request_kind=request.request_kind,
            accepted=False,
            reason=ExecutionAdmissionDecisionReason.ACCEPTED,
            decided_at=NOW,
        )


def test_source_provenance_rejection_decision_preserves_reason_and_details() -> None:
    request = _request()
    assert request.request_id is not None
    decision = ExecutionAdmissionDecision(
        request_id=request.request_id,
        request_kind=request.request_kind,
        accepted=False,
        reason=ExecutionAdmissionDecisionReason.REJECTED_BY_SOURCE_PROVENANCE,
        source_provenance_checked=True,
        source_provenance_passed=False,
        source_provenance_reason="SOURCE_RECORD_NOT_ACCEPTED",
        source_provenance_details={"bad": True},
        decided_at=NOW,
    )

    assert decision.source_provenance_reason == "SOURCE_RECORD_NOT_ACCEPTED"
    assert decision.source_provenance_details == {"bad": True}

    with pytest.raises(ValidationError, match="source_provenance_checked=True"):
        ExecutionAdmissionDecision(
            request_id=request.request_id,
            request_kind=request.request_kind,
            accepted=False,
            reason=ExecutionAdmissionDecisionReason.REJECTED_BY_SOURCE_PROVENANCE,
            source_provenance_checked=False,
            source_provenance_passed=False,
            decided_at=NOW,
        )


def test_execution_coordinator_event_payload_hash_validation() -> None:
    request_id = ExecutionAdmissionRequestId("request-1")
    payload = {"status": "accepted"}
    event = ExecutionCoordinatorEvent(
        request_id=request_id,
        event_kind=ExecutionCoordinatorEventKind.ADMISSION_ACCEPTED,
        occurred_at=NOW,
        payload=payload,
        payload_hash=canonical_payload_hash(payload),
    )
    assert event.event_id is not None

    with pytest.raises(ValidationError, match="payload_hash does not match"):
        ExecutionCoordinatorEvent(
            request_id=request_id,
            event_kind=ExecutionCoordinatorEventKind.ADMISSION_ACCEPTED,
            occurred_at=NOW,
            payload=payload,
            payload_hash="0" * 64,
        )
