from __future__ import annotations

from tests.unit.capability_freshness_fixtures import NOW, order, rules, venue

from futures_bot.domain.ids import (
    VenueCapabilityFreshnessPolicyId,
    VenueCapabilitySourceRecordId,
)
from futures_bot.domain.venue_capability_freshness import (
    CapabilitySourceHealth,
    VenueCapabilityFreshnessPolicy,
)
from futures_bot.domain.venue_capability_resolution import (
    VenueCapabilityResolutionReason,
    VenueCapabilityResolutionRequest,
)
from futures_bot.venue_capabilities.in_memory import (
    InMemoryVenueCapabilitySnapshotStore,
    InMemoryVenueInstrumentRuleSnapshotStore,
)
from futures_bot.venue_capabilities.resolution import (
    DeterministicVenueCapabilityResolutionGateway,
)

PAYLOAD_HASH = "1" * 64


def _policy() -> VenueCapabilityFreshnessPolicy:
    return VenueCapabilityFreshnessPolicy.strict(
        policy_id=VenueCapabilityFreshnessPolicyId(value="source-resolution-policy"),
        max_venue_snapshot_age_ms=60_000,
        max_instrument_rules_age_ms=60_000,
    )


def _request() -> VenueCapabilityResolutionRequest:
    return VenueCapabilityResolutionRequest(
        order_intent=order(),
        checked_at=NOW,
        freshness_policy=_policy(),
        source_health=CapabilitySourceHealth.HEALTHY,
    )


def _gateway(
    venue_store: InMemoryVenueCapabilitySnapshotStore,
    rule_store: InMemoryVenueInstrumentRuleSnapshotStore,
) -> DeterministicVenueCapabilityResolutionGateway:
    return DeterministicVenueCapabilityResolutionGateway(
        venue_snapshot_store=venue_store,
        instrument_rule_store=rule_store,
    )


def test_ready_resolution_preserves_snapshot_source_provenance() -> None:
    source_record_id = VenueCapabilitySourceRecordId(value="record-1")
    venue_snapshot = venue(
        source_record_id=source_record_id,
        source_payload_hash=PAYLOAD_HASH,
    )
    instrument_rules = rules(
        source_record_id=source_record_id,
        source_payload_hash=PAYLOAD_HASH,
    )
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    venue_store.put(venue_snapshot)
    rule_store.put(instrument_rules)

    decision = _gateway(venue_store, rule_store).resolve(_request())

    assert decision.ready is True
    assert decision.reason is VenueCapabilityResolutionReason.READY
    assert decision.venue_source_record_id == source_record_id
    assert decision.instrument_source_record_ids == (source_record_id,)
    assert decision.venue_snapshot == venue_snapshot
    assert decision.instrument_rules == instrument_rules


def test_resolution_remains_backward_compatible_when_provenance_absent() -> None:
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    venue_store.put(venue())
    rule_store.put(rules())

    decision = _gateway(venue_store, rule_store).resolve(_request())

    assert decision.ready is True
    assert decision.reason is VenueCapabilityResolutionReason.READY
    assert decision.venue_source_record_id is None
    assert decision.instrument_source_record_ids == ()
