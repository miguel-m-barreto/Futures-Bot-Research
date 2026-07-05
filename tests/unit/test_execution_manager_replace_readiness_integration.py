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
from futures_bot.domain.order_lifecycle import (
    OrderIntent,
    OrderLifecycleState,
    ReplaceOrderIntent,
)
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
        policy_id=VenueCapabilityFreshnessPolicyId("policy-replace-readiness"),
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


def _admit_original(
    coordinator: DeterministicExecutionManagerCoordinator,
) -> OrderIntent:
    original = order()
    coordinator.admit(
        ExecutionAdmissionRequest(
            request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
            order_intent=original,
            order_flow_permission=permission(),
            requested_at=NOW,
            requested_by="replace-readiness-setup",
        )
    )
    return original


def _replace_request(  # noqa: PLR0913
    original: OrderIntent,
    replacement: OrderIntent,
    *,
    require_validation: bool = False,
    require_freshness: bool = False,
    ctx: object | None = None,
    freshness: VenueCapabilityFreshnessCheck | None = None,
    source_provenance_checked: bool = False,
    source_provenance_passed: bool = False,
) -> ExecutionAdmissionRequest:
    replace_intent = ReplaceOrderIntent(
        target_client_order_id=original.client_order_id,
        target_intent_kind=original.intent_kind,
        replacement_order=replacement,
        replace_reason="replace-readiness",
        created_at=NOW,
    )
    return ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.REPLACE_INTENT,
        replace_intent=replace_intent,
        order_flow_permission=permission(),
        venue_validation_context=ctx,
        freshness_check=freshness,
        require_venue_capability_validation=require_validation,
        require_fresh_capability_snapshot=require_freshness,
        source_provenance_checked=source_provenance_checked,
        source_provenance_passed=source_provenance_passed,
        source_provenance_reason=(
            "SOURCE_RECORD_NOT_ACCEPTED"
            if source_provenance_checked and not source_provenance_passed
            else None
        ),
        source_provenance_details=(
            {"bad": True}
            if source_provenance_checked and not source_provenance_passed
            else None
        ),
        requested_at=NOW,
        requested_by="replace-readiness-test",
    )


def _gate_statuses(
    proof_id: object,
    store: InMemoryExecutionReadinessProofStore,
) -> dict[str, str]:
    proof = store.get(proof_id)
    assert proof is not None
    return {gate.gate.value: gate.status.value for gate in proof.gates}


def test_accepted_replacement_record_includes_readiness_proof() -> None:
    coordinator, records, readiness = _coordinator()
    original = _admit_original(coordinator)
    replacement = order(quantity="2")

    decision = coordinator.admit(_replace_request(original, replacement))

    replacement_record = records.get_by_client_order_id(replacement.client_order_id)
    assert decision.accepted
    assert decision.readiness_proof_id is not None
    assert replacement_record is not None
    assert replacement_record.readiness_proof_id == decision.readiness_proof_id
    statuses = _gate_statuses(decision.readiness_proof_id, readiness)
    assert statuses[ExecutionReadinessGate.RUNTIME_PERMISSION.value] == (
        ExecutionReadinessGateStatus.PASSED.value
    )
    assert statuses[ExecutionReadinessGate.ORDER_SCOPE.value] == (
        ExecutionReadinessGateStatus.PASSED.value
    )
    assert statuses[ExecutionReadinessGate.REPLACE_TARGET.value] == (
        ExecutionReadinessGateStatus.PASSED.value
    )


def test_replace_stale_freshness_rejects_without_replacement_proof_or_record() -> None:
    coordinator, records, readiness = _coordinator()
    original = _admit_original(coordinator)
    replacement = order(quantity="2")
    stale = venue(captured_at=NOW - timedelta(milliseconds=2))

    decision = coordinator.admit(
        _replace_request(
            original,
            replacement,
            require_validation=True,
            require_freshness=True,
            ctx=context(replacement, venue_snapshot=stale),
            freshness=_freshness(venue_snapshot=stale, policy=_policy(max_age_ms=1)),
        )
    )

    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_CAPABILITY_FRESHNESS
    assert records.get_by_client_order_id(replacement.client_order_id) is None
    assert readiness.get_by_client_order_id(replacement.client_order_id) is None


def test_replace_checked_failed_source_provenance_rejects_without_mutation_or_proof() -> None:
    coordinator, records, readiness = _coordinator()
    original = _admit_original(coordinator)
    replacement = order(quantity="2")

    decision = coordinator.admit(
        _replace_request(
            original,
            replacement,
            source_provenance_checked=True,
            source_provenance_passed=False,
        )
    )

    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_SOURCE_PROVENANCE
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
    assert records.get_by_client_order_id(replacement.client_order_id) is None
    assert readiness.get_by_client_order_id(replacement.client_order_id) is None


def test_replace_venue_capability_rejects_without_replacement_proof_or_record() -> None:
    coordinator, records, readiness = _coordinator()
    original = _admit_original(coordinator)
    replacement = order(quantity="2")
    disabled = venue(trading_status=VenueTradingStatus.DISABLED)

    decision = coordinator.admit(
        _replace_request(
            original,
            replacement,
            require_validation=True,
            ctx=context(replacement, venue_snapshot=disabled),
        )
    )

    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY
    assert records.get_by_client_order_id(replacement.client_order_id) is None
    assert readiness.get_by_client_order_id(replacement.client_order_id) is None


def test_replace_scope_mismatch_does_not_create_replacement_proof() -> None:
    coordinator, records, readiness = _coordinator()
    original = _admit_original(coordinator)
    replacement = order(instrument_id="ETH-PERP")

    decision = coordinator.admit(_replace_request(original, replacement))

    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VALIDATION
    assert records.get_by_client_order_id(replacement.client_order_id) is None
    assert readiness.get_by_client_order_id(replacement.client_order_id) is None
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
