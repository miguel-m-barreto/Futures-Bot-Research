from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from tests.unit.capability_freshness_fixtures import (
    NOW,
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
from futures_bot.domain.ids import VenueCapabilityFreshnessPolicyId
from futures_bot.domain.order_lifecycle import OrderIntent, OrderType
from futures_bot.domain.venue_capabilities import (
    PriceFilter,
    VenueCapabilitySnapshot,
    VenueInstrumentRuleSnapshot,
    VenueOrderValidationReason,
)
from futures_bot.domain.venue_capability_freshness import (
    CapabilitySourceHealth,
    VenueCapabilityFreshnessCheck,
    VenueCapabilityFreshnessPolicy,
)
from futures_bot.domain.venue_capability_resolution import (
    VenueCapabilityResolutionDecision,
    VenueCapabilityResolutionReason,
    VenueCapabilityResolutionRequest,
)
from futures_bot.execution_manager.coordinator import DeterministicExecutionManagerCoordinator
from futures_bot.order_lifecycle.in_memory import (
    InMemoryExecutionOrderRecordStore,
    InMemoryExecutionReconciliationStore,
    InMemoryOrderIntentJournal,
    InMemoryOrderLifecycleEventStore,
)
from futures_bot.venue_capabilities.in_memory import (
    InMemoryVenueCapabilitySnapshotStore,
    InMemoryVenueInstrumentRuleSnapshotStore,
)
from futures_bot.venue_capabilities.resolution import (
    DeterministicVenueCapabilityResolutionGateway,
)


def _policy(max_age_ms: int = 60_000) -> VenueCapabilityFreshnessPolicy:
    return VenueCapabilityFreshnessPolicy.strict(
        policy_id=VenueCapabilityFreshnessPolicyId(value="resolution-flow-policy"),
        max_venue_snapshot_age_ms=max_age_ms,
        max_instrument_rules_age_ms=max_age_ms,
    )


def _coordinator() -> tuple[
    DeterministicExecutionManagerCoordinator,
    InMemoryExecutionOrderRecordStore,
]:
    records = InMemoryExecutionOrderRecordStore()
    coordinator = DeterministicExecutionManagerCoordinator(
        intent_journal=InMemoryOrderIntentJournal(),
        lifecycle_event_store=InMemoryOrderLifecycleEventStore(),
        order_record_store=records,
        reconciliation_store=InMemoryExecutionReconciliationStore(),
    )
    return coordinator, records


def _resolve(
    *,
    order_intent: OrderIntent,
    venue_snapshot: VenueCapabilitySnapshot | None = None,
    instrument_rules: VenueInstrumentRuleSnapshot | None = None,
    policy: VenueCapabilityFreshnessPolicy | None = None,
) -> VenueCapabilityResolutionDecision:
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    if venue_snapshot is not None:
        venue_store.put(venue_snapshot)
    if instrument_rules is not None:
        rule_store.put(instrument_rules)
    gateway = DeterministicVenueCapabilityResolutionGateway(
        venue_snapshot_store=venue_store,
        instrument_rule_store=rule_store,
    )
    return gateway.resolve(
        VenueCapabilityResolutionRequest(
            order_intent=order_intent,
            checked_at=NOW,
            freshness_policy=policy or _policy(),
            source_health=CapabilitySourceHealth.HEALTHY,
        )
    )


def _request_from_resolution(
    decision: VenueCapabilityResolutionDecision,
) -> ExecutionAdmissionRequest:
    assert decision.venue_validation_context is not None
    assert decision.freshness_check is not None
    return ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=decision.venue_validation_context.order_intent,
        order_flow_permission=permission(),
        venue_validation_context=decision.venue_validation_context,
        freshness_check=decision.freshness_check,
        require_venue_capability_validation=True,
        require_fresh_capability_snapshot=True,
        requested_at=NOW,
        requested_by="resolution-flow-test",
    )


def test_ready_resolution_feeds_admission_and_accepts_local_order() -> None:
    order_intent = order()
    decision = _resolve(
        order_intent=order_intent,
        venue_snapshot=venue(),
        instrument_rules=rules(),
    )
    assert decision.ready is True
    coordinator, records = _coordinator()
    admission = coordinator.admit(_request_from_resolution(decision))
    assert admission.accepted is True
    assert admission.reason is ExecutionAdmissionDecisionReason.ACCEPTED
    assert records.get_by_client_order_id(order_intent.client_order_id) is not None


def test_not_ready_resolution_creates_no_admission_request_with_fake_context() -> None:
    decision = _resolve(order_intent=order(), instrument_rules=rules())
    assert decision.ready is False
    assert decision.reason is VenueCapabilityResolutionReason.VENUE_SNAPSHOT_MISSING
    assert decision.venue_validation_context is None
    assert decision.freshness_check is None


def test_ready_resolution_plus_invalid_order_rejects_downstream_by_venue_capability() -> None:
    order_intent = order(order_type=OrderType.LIMIT, limit_price="100.05")
    decision = _resolve(
        order_intent=order_intent,
        venue_snapshot=venue(),
        instrument_rules=rules(),
    )
    assert decision.ready is True
    coordinator, records = _coordinator()
    admission = coordinator.admit(_request_from_resolution(decision))
    assert admission.accepted is False
    assert admission.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY
    assert admission.venue_validation_reason == VenueOrderValidationReason.PRICE_NOT_ON_TICK.value
    assert admission.venue_validation_details is not None
    assert records.get_by_client_order_id(order_intent.client_order_id) is None


def test_review_113_price_min_max_validation_preserved_through_flow() -> None:
    order_intent = order(order_type=OrderType.LIMIT, limit_price="0.5")
    constrained_rules = rules(
        price_filter=PriceFilter(
            tick_size=Decimal("0.1"),
            min_price=Decimal("1.0"),
        )
    )
    decision = _resolve(
        order_intent=order_intent,
        venue_snapshot=venue(),
        instrument_rules=constrained_rules,
    )
    assert decision.ready is True
    coordinator, _records = _coordinator()
    admission = coordinator.admit(_request_from_resolution(decision))
    assert admission.venue_validation_reason == (
        VenueOrderValidationReason.PRICE_BELOW_MINIMUM.value
    )


def test_review_116_freshness_stale_rejection_preserved() -> None:
    stale = venue(captured_at=NOW - timedelta(milliseconds=2))
    decision = _resolve(
        order_intent=order(),
        venue_snapshot=stale,
        instrument_rules=rules(),
        policy=_policy(max_age_ms=1),
    )
    assert decision.ready is False
    assert decision.reason is VenueCapabilityResolutionReason.FRESHNESS_REJECTED
    assert decision.venue_validation_context is None


def test_review_117_freshness_mismatch_handling_preserved() -> None:
    order_intent = order()
    decision = _resolve(
        order_intent=order_intent,
        venue_snapshot=venue(),
        instrument_rules=rules(),
    )
    assert decision.ready is True
    assert decision.venue_validation_context is not None
    assert decision.freshness_check is not None
    mismatched_freshness = VenueCapabilityFreshnessCheck(
        venue_id=order_intent.venue_id,
        instrument_id=order_intent.instrument_id,
        venue_snapshot=decision.venue_snapshot,
        instrument_rules=rules(source_hash="0" * 64),
        policy=decision.freshness_check.policy,
        source_health=decision.freshness_check.source_health,
        checked_at=decision.freshness_check.checked_at,
    )
    mismatched_request = ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order_intent,
        order_flow_permission=permission(),
        venue_validation_context=decision.venue_validation_context,
        freshness_check=mismatched_freshness,
        require_venue_capability_validation=True,
        require_fresh_capability_snapshot=True,
        requested_at=NOW,
        requested_by="resolution-flow-test",
    )
    coordinator, records = _coordinator()
    admission = coordinator.admit(mismatched_request)
    assert admission.reason is ExecutionAdmissionDecisionReason.FRESHNESS_CONTEXT_MISMATCH
    assert records.get_by_client_order_id(order_intent.client_order_id) is None
