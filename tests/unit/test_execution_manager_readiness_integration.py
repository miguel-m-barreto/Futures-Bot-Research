from __future__ import annotations

from datetime import timedelta

from capability_freshness_fixtures import (
    NOW,
    context,
    order,
    permission,
    rules,
    venue,
)

from futures_bot.domain.execution_manager import (
    ExecutionAdmissionDecisionReason,
    ExecutionAdmissionRequest,
    ExecutionAdmissionRequestKind,
)
from futures_bot.domain.execution_readiness import (
    ExecutionReadinessGate,
    ExecutionReadinessGateStatus,
)
from futures_bot.domain.ids import VenueCapabilityFreshnessPolicyId
from futures_bot.domain.order_lifecycle import OrderLifecycleState
from futures_bot.domain.venue_capabilities import VenueTradingStatus
from futures_bot.domain.venue_capability_freshness import (
    CapabilitySourceHealth,
    VenueCapabilityFreshnessCheck,
    VenueCapabilityFreshnessPolicy,
)
from futures_bot.execution_manager.coordinator import DeterministicExecutionManagerCoordinator
from futures_bot.execution_manager.in_memory import InMemoryExecutionReadinessProofStore
from futures_bot.order_lifecycle.in_memory import (
    InMemoryExecutionOrderRecordStore,
    InMemoryExecutionReconciliationStore,
    InMemoryOrderIntentJournal,
    InMemoryOrderLifecycleEventStore,
)


def _policy(max_age_ms: int = 60_000) -> VenueCapabilityFreshnessPolicy:
    return VenueCapabilityFreshnessPolicy(
        policy_id=VenueCapabilityFreshnessPolicyId("policy-readiness"),
        max_venue_snapshot_age_ms=max_age_ms,
        max_instrument_rules_age_ms=max_age_ms,
    )


def _freshness(**overrides: object) -> VenueCapabilityFreshnessCheck:
    values: dict[str, object] = {
        "venue_id": "venue-1",
        "instrument_id": "BTC-PERP",
        "venue_snapshot": venue(),
        "instrument_rules": rules(),
        "policy": _policy(),
        "source_health": CapabilitySourceHealth.HEALTHY,
        "checked_at": NOW,
    }
    values.update(overrides)
    return VenueCapabilityFreshnessCheck(**values)


def _coordinator() -> tuple[
    DeterministicExecutionManagerCoordinator,
    InMemoryExecutionOrderRecordStore,
    InMemoryExecutionReadinessProofStore,
]:
    records = InMemoryExecutionOrderRecordStore()
    readiness = InMemoryExecutionReadinessProofStore()
    coordinator = DeterministicExecutionManagerCoordinator(
        intent_journal=InMemoryOrderIntentJournal(),
        lifecycle_event_store=InMemoryOrderLifecycleEventStore(),
        order_record_store=records,
        reconciliation_store=InMemoryExecutionReconciliationStore(),
        readiness_proof_store=readiness,
    )
    return coordinator, records, readiness


def _coordinator_with_lifecycle() -> tuple[
    DeterministicExecutionManagerCoordinator,
    InMemoryExecutionOrderRecordStore,
    InMemoryExecutionReadinessProofStore,
    InMemoryOrderLifecycleEventStore,
]:
    records = InMemoryExecutionOrderRecordStore()
    readiness = InMemoryExecutionReadinessProofStore()
    lifecycle = InMemoryOrderLifecycleEventStore()
    coordinator = DeterministicExecutionManagerCoordinator(
        intent_journal=InMemoryOrderIntentJournal(),
        lifecycle_event_store=lifecycle,
        order_record_store=records,
        reconciliation_store=InMemoryExecutionReconciliationStore(),
        readiness_proof_store=readiness,
    )
    return coordinator, records, readiness, lifecycle


def _request(
    *,
    require_validation: bool = False,
    require_freshness: bool = False,
    ctx: object | None = None,
    freshness: VenueCapabilityFreshnessCheck | None = None,
    allow_new_entries: bool = True,
) -> ExecutionAdmissionRequest:
    order_intent = order()
    return ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order_intent,
        order_flow_permission=permission(allow_new_entries=allow_new_entries),
        venue_validation_context=ctx,
        freshness_check=freshness,
        require_venue_capability_validation=require_validation,
        require_fresh_capability_snapshot=require_freshness,
        requested_at=NOW,
        requested_by="readiness-test",
    )


def _gate_statuses(
    proof_id: object,
    store: InMemoryExecutionReadinessProofStore,
) -> dict[str, str]:
    proof = store.get(proof_id)
    assert proof is not None
    return {gate.gate.value: gate.status.value for gate in proof.gates}


def test_accepted_order_without_venue_requirement_has_readiness_proof() -> None:
    coordinator, records, readiness = _coordinator()
    request = _request()
    assert request.order_intent is not None

    decision = coordinator.admit(request)

    record = records.get_by_client_order_id(request.order_intent.client_order_id)
    assert decision.accepted
    assert decision.readiness_proof_id is not None
    assert decision.readiness_ready is True
    assert record is not None
    assert record.readiness_proof_id == decision.readiness_proof_id
    statuses = _gate_statuses(decision.readiness_proof_id, readiness)
    assert statuses[ExecutionReadinessGate.RUNTIME_PERMISSION.value] == (
        ExecutionReadinessGateStatus.PASSED.value
    )
    assert statuses[ExecutionReadinessGate.VENUE_CAPABILITY.value] == (
        ExecutionReadinessGateStatus.NOT_REQUIRED.value
    )


def test_accepted_order_with_capability_validation_proves_capability_passed() -> None:
    coordinator, _records, readiness = _coordinator()
    order_intent = order()
    request = ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order_intent,
        order_flow_permission=permission(),
        venue_validation_context=context(order_intent),
        require_venue_capability_validation=True,
        requested_at=NOW,
        requested_by="readiness-test",
    )

    decision = coordinator.admit(request)

    statuses = _gate_statuses(decision.readiness_proof_id, readiness)
    assert statuses[ExecutionReadinessGate.VENUE_CAPABILITY.value] == (
        ExecutionReadinessGateStatus.PASSED.value
    )


def test_accepted_order_with_freshness_required_proves_freshness_passed() -> None:
    coordinator, _records, readiness = _coordinator()
    order_intent = order()
    request = ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order_intent,
        order_flow_permission=permission(),
        venue_validation_context=context(order_intent),
        freshness_check=_freshness(),
        require_venue_capability_validation=True,
        require_fresh_capability_snapshot=True,
        requested_at=NOW,
        requested_by="readiness-test",
    )

    decision = coordinator.admit(request)

    statuses = _gate_statuses(decision.readiness_proof_id, readiness)
    assert statuses[ExecutionReadinessGate.CAPABILITY_FRESHNESS.value] == (
        ExecutionReadinessGateStatus.PASSED.value
    )


def test_accepted_order_preserves_required_source_provenance_readiness() -> None:
    coordinator, _records, readiness = _coordinator()
    order_intent = order()
    request = ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order_intent,
        order_flow_permission=permission(),
        source_provenance_required=True,
        source_provenance_checked=True,
        source_provenance_passed=True,
        source_provenance_reason="official_source_resolution_passed",
        source_provenance_details={"source_record_id": "source-record-1"},
        requested_at=NOW,
        requested_by="readiness-test",
    )

    decision = coordinator.admit(request)

    statuses = _gate_statuses(decision.readiness_proof_id, readiness)
    assert statuses[ExecutionReadinessGate.SOURCE_PROVENANCE.value] == (
        ExecutionReadinessGateStatus.PASSED.value
    )


def test_checked_failed_source_provenance_rejects_without_record_or_ready_proof() -> None:
    coordinator, records, readiness, lifecycle = _coordinator_with_lifecycle()
    order_intent = order()
    request = ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order_intent,
        order_flow_permission=permission(),
        source_provenance_checked=True,
        source_provenance_passed=False,
        source_provenance_reason="SOURCE_RECORD_NOT_ACCEPTED",
        source_provenance_details={"bad": True},
        requested_at=NOW,
        requested_by="readiness-test",
    )

    decision = coordinator.admit(request)

    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_SOURCE_PROVENANCE
    assert decision.source_provenance_checked is True
    assert decision.source_provenance_passed is False
    assert decision.source_provenance_reason == "SOURCE_RECORD_NOT_ACCEPTED"
    assert decision.source_provenance_details == {"bad": True}
    assert records.get_by_client_order_id(order_intent.client_order_id) is None
    assert readiness.list_proofs() == ()
    rejection_events = [
        event
        for event in lifecycle.list_events()
        if event.payload.get("stage") == "rejected_by_source_provenance"
    ]
    assert len(rejection_events) == 1


def test_runtime_rejection_creates_no_active_record_and_no_ready_proof() -> None:
    coordinator, records, readiness = _coordinator()
    request = _request(allow_new_entries=False)
    assert request.order_intent is not None

    decision = coordinator.admit(request)

    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_PERMISSION
    assert records.get_by_client_order_id(request.order_intent.client_order_id) is None
    assert readiness.list_proofs() == ()


def test_freshness_rejection_creates_no_active_record_and_no_ready_proof() -> None:
    coordinator, records, readiness = _coordinator()
    order_intent = order()
    stale = venue(captured_at=NOW - timedelta(milliseconds=2))
    request = ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order_intent,
        order_flow_permission=permission(),
        venue_validation_context=context(order_intent, venue_snapshot=stale),
        freshness_check=_freshness(venue_snapshot=stale, policy=_policy(max_age_ms=1)),
        require_venue_capability_validation=True,
        require_fresh_capability_snapshot=True,
        requested_at=NOW,
        requested_by="readiness-test",
    )

    decision = coordinator.admit(request)

    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_CAPABILITY_FRESHNESS
    assert records.get_by_client_order_id(order_intent.client_order_id) is None
    assert readiness.list_proofs() == ()


def test_venue_capability_rejection_creates_no_active_record_and_no_ready_proof() -> None:
    coordinator, records, readiness = _coordinator()
    order_intent = order()
    disabled = venue(trading_status=VenueTradingStatus.DISABLED)
    request = ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order_intent,
        order_flow_permission=permission(),
        venue_validation_context=context(order_intent, venue_snapshot=disabled),
        require_venue_capability_validation=True,
        requested_at=NOW,
        requested_by="readiness-test",
    )

    decision = coordinator.admit(request)

    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY
    assert records.get_by_client_order_id(order_intent.client_order_id) is None
    assert readiness.list_proofs() == ()


def test_accepted_record_is_still_local_only() -> None:
    coordinator, records, _readiness = _coordinator()
    request = _request()
    assert request.order_intent is not None

    coordinator.admit(request)

    record = records.get_by_client_order_id(request.order_intent.client_order_id)
    assert record is not None
    assert record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
