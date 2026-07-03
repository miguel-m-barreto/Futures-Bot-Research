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
from futures_bot.domain.venue_capability_sources import (
    VenueCapabilityManualImportRequest,
    VenueCapabilitySourceDescriptor,
    VenueCapabilitySourceFetchMode,
    VenueCapabilitySourceHealthStatus,
    VenueCapabilitySourceKind,
    VenueCapabilitySourcePayload,
    VenueCapabilitySourceRecord,
    VenueCapabilitySourceRecordReason,
    VenueCapabilitySourceTrust,
)
from futures_bot.execution_manager.coordinator import DeterministicExecutionManagerCoordinator
from futures_bot.order_lifecycle.in_memory import (
    InMemoryExecutionOrderRecordStore,
    InMemoryExecutionReconciliationStore,
    InMemoryOrderIntentJournal,
    InMemoryOrderLifecycleEventStore,
)
from futures_bot.venue_capabilities.in_memory import (
    InMemoryVenueCapabilityManualImportStore,
    InMemoryVenueCapabilitySnapshotStore,
    InMemoryVenueCapabilitySourceRecordStore,
    InMemoryVenueInstrumentRuleSnapshotStore,
)
from futures_bot.venue_capabilities.resolution import (
    DeterministicVenueCapabilityResolutionGateway,
)
from futures_bot.venue_capabilities.sources import (
    DeterministicVenueCapabilityManualImportGateway,
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


def _source_record() -> VenueCapabilitySourceRecord:
    descriptor = VenueCapabilitySourceDescriptor(
        venue_id="venue-1",
        source_kind=VenueCapabilitySourceKind.OFFICIAL_EXCHANGE_EXPORT,
        trust=VenueCapabilitySourceTrust.OFFICIAL,
        fetch_mode=VenueCapabilitySourceFetchMode.MANUAL,
        reference_name="Official export",
        official_owner="Venue",
        version="2026-01-01",
        created_at=NOW,
        metadata={},
    )
    payload = VenueCapabilitySourcePayload(
        canonical_payload={"venue": "venue-1", "symbols": ["BTCUSDT"]},
        content_type="application/json",
        captured_at=NOW,
        observed_at=NOW,
    )
    return VenueCapabilitySourceRecord(
        descriptor=descriptor,
        payload=payload,
        health_status=VenueCapabilitySourceHealthStatus.HEALTHY,
        reason=VenueCapabilitySourceRecordReason.ACCEPTED,
        accepted_for_execution=True,
        recorded_at=NOW,
        details={},
    )


def _resolve(  # noqa: PLR0913
    *,
    order_intent: OrderIntent,
    venue_snapshot: VenueCapabilitySnapshot | None = None,
    instrument_rules: VenueInstrumentRuleSnapshot | None = None,
    policy: VenueCapabilityFreshnessPolicy | None = None,
    source_record_store: InMemoryVenueCapabilitySourceRecordStore | None = None,
    require_official_source_provenance: bool = False,
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
        source_record_store=source_record_store,
    )
    return gateway.resolve(
        VenueCapabilityResolutionRequest(
            order_intent=order_intent,
            checked_at=NOW,
            freshness_policy=policy or _policy(),
            source_health=CapabilitySourceHealth.HEALTHY,
            require_official_source_provenance=require_official_source_provenance,
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


def test_provenance_ready_resolution_feeds_admission_and_accepts_local_order() -> None:
    source_record = _source_record()
    assert source_record.record_id is not None
    assert source_record.payload.payload_hash is not None
    source_store = InMemoryVenueCapabilitySourceRecordStore()
    source_store.put(source_record)
    order_intent = order()
    decision = _resolve(
        order_intent=order_intent,
        venue_snapshot=venue(
            source_record_id=source_record.record_id,
            source_payload_hash=source_record.payload.payload_hash,
        ),
        instrument_rules=rules(
            source_record_id=source_record.record_id,
            source_payload_hash=source_record.payload.payload_hash,
        ),
        source_record_store=source_store,
        require_official_source_provenance=True,
    )
    assert decision.ready is True
    assert decision.provenance_checked is True
    coordinator, records = _coordinator()
    admission = coordinator.admit(_request_from_resolution(decision))
    assert admission.accepted is True
    assert admission.reason is ExecutionAdmissionDecisionReason.ACCEPTED
    assert records.get_by_client_order_id(order_intent.client_order_id) is not None


def test_manual_import_strict_resolution_feeds_execution_manager_acceptance() -> None:
    source_record = _source_record()
    assert source_record.record_id is not None
    assert source_record.payload.payload_hash is not None
    source_store = InMemoryVenueCapabilitySourceRecordStore()
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    import_store = InMemoryVenueCapabilityManualImportStore()
    venue_snapshot = venue(
        source_record_id=source_record.record_id,
        source_payload_hash=source_record.payload.payload_hash,
    )
    instrument_rules = rules(
        source_record_id=source_record.record_id,
        source_payload_hash=source_record.payload.payload_hash,
    )
    import_decision = DeterministicVenueCapabilityManualImportGateway(
        source_record_store=source_store,
        venue_snapshot_store=venue_store,
        instrument_rule_store=rule_store,
        manual_import_store=import_store,
    ).import_capabilities(
        VenueCapabilityManualImportRequest(
            source_record=source_record,
            venue_snapshot=venue_snapshot,
            instrument_rules=(instrument_rules,),
            imported_at=NOW,
            imported_by="operator",
            details={},
        )
    )
    decision = DeterministicVenueCapabilityResolutionGateway(
        venue_snapshot_store=venue_store,
        instrument_rule_store=rule_store,
        source_record_store=source_store,
    ).resolve(
        VenueCapabilityResolutionRequest(
            order_intent=order(),
            checked_at=NOW,
            freshness_policy=_policy(),
            source_health=CapabilitySourceHealth.HEALTHY,
            require_official_source_provenance=True,
        )
    )

    assert import_decision.accepted is True
    assert decision.ready is True
    coordinator, records = _coordinator()
    admission = coordinator.admit(_request_from_resolution(decision))
    assert admission.accepted is True
    assert admission.reason is ExecutionAdmissionDecisionReason.ACCEPTED
    assert records.get_by_client_order_id(
        decision.venue_validation_context.order_intent.client_order_id
    ) is not None


def test_not_ready_resolution_creates_no_admission_request_with_fake_context() -> None:
    decision = _resolve(order_intent=order(), instrument_rules=rules())
    assert decision.ready is False
    assert decision.reason is VenueCapabilityResolutionReason.VENUE_SNAPSHOT_MISSING
    assert decision.venue_validation_context is None
    assert decision.freshness_check is None


def test_provenance_not_ready_resolution_creates_no_fake_admission_context() -> None:
    decision = _resolve(
        order_intent=order(),
        venue_snapshot=venue(),
        instrument_rules=rules(),
        require_official_source_provenance=True,
    )
    assert decision.ready is False
    assert decision.reason is VenueCapabilityResolutionReason.SOURCE_PROVENANCE_REQUIRED
    assert decision.provenance_checked is True
    assert decision.venue_validation_context is None
    assert decision.freshness_check is not None


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


def test_provenance_ready_invalid_order_rejects_downstream_by_venue_capability() -> None:
    source_record = _source_record()
    assert source_record.record_id is not None
    assert source_record.payload.payload_hash is not None
    source_store = InMemoryVenueCapabilitySourceRecordStore()
    source_store.put(source_record)
    order_intent = order(order_type=OrderType.LIMIT, limit_price="100.05")
    decision = _resolve(
        order_intent=order_intent,
        venue_snapshot=venue(
            source_record_id=source_record.record_id,
            source_payload_hash=source_record.payload.payload_hash,
        ),
        instrument_rules=rules(
            source_record_id=source_record.record_id,
            source_payload_hash=source_record.payload.payload_hash,
        ),
        source_record_store=source_store,
        require_official_source_provenance=True,
    )
    assert decision.ready is True
    coordinator, records = _coordinator()
    admission = coordinator.admit(_request_from_resolution(decision))
    assert admission.accepted is False
    assert admission.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY
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


def test_review_115_venue_validation_reason_details_propagation_preserved() -> None:
    order_intent = order(order_type=OrderType.LIMIT, limit_price="100.05")
    decision = _resolve(
        order_intent=order_intent,
        venue_snapshot=venue(),
        instrument_rules=rules(),
    )
    assert decision.ready is True
    coordinator, _records = _coordinator()
    admission = coordinator.admit(_request_from_resolution(decision))
    assert admission.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY
    assert admission.venue_validation_reason == VenueOrderValidationReason.PRICE_NOT_ON_TICK.value
    assert admission.venue_validation_details is not None
    assert admission.venue_validation_details["reason"] == (
        VenueOrderValidationReason.PRICE_NOT_ON_TICK.value
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


def test_review_118_missing_snapshot_no_context_behavior_preserved() -> None:
    decision = _resolve(order_intent=order(), instrument_rules=rules())

    assert decision.ready is False
    assert decision.reason is VenueCapabilityResolutionReason.VENUE_SNAPSHOT_MISSING
    assert decision.venue_snapshot is None
    assert decision.venue_validation_context is None
    assert decision.freshness_check is None
