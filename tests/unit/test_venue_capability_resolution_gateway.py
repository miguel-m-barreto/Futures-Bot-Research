from __future__ import annotations

from datetime import timedelta

from tests.unit.capability_freshness_fixtures import NOW, order, rules, venue

from futures_bot.domain.ids import (
    VenueCapabilityFreshnessPolicyId,
    VenueCapabilitySnapshotId,
    VenueInstrumentRuleSnapshotId,
)
from futures_bot.domain.order_lifecycle import OrderType
from futures_bot.domain.venue_capability_freshness import (
    CapabilityFreshnessDecisionReason,
    CapabilityFreshnessMode,
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


def _policy(max_age_ms: int = 60_000) -> VenueCapabilityFreshnessPolicy:
    return VenueCapabilityFreshnessPolicy.strict(
        policy_id=VenueCapabilityFreshnessPolicyId(value="resolution-policy"),
        max_venue_snapshot_age_ms=max_age_ms,
        max_instrument_rules_age_ms=max_age_ms,
    )


def _disabled_policy() -> VenueCapabilityFreshnessPolicy:
    return VenueCapabilityFreshnessPolicy(
        policy_id=VenueCapabilityFreshnessPolicyId(value="resolution-policy-disabled"),
        mode=CapabilityFreshnessMode.DISABLED,
        max_venue_snapshot_age_ms=1,
        max_instrument_rules_age_ms=1,
        reject_future_snapshots=False,
        reject_degraded_source=False,
        reject_unknown_source=False,
        require_venue_snapshot=False,
        require_instrument_rules=False,
    )


def _request(**overrides: object) -> VenueCapabilityResolutionRequest:
    values: dict[str, object] = {
        "order_intent": order(),
        "checked_at": NOW,
        "freshness_policy": _policy(),
        "source_health": CapabilitySourceHealth.HEALTHY,
    }
    values.update(overrides)
    return VenueCapabilityResolutionRequest(**values)


def _gateway(
    venue_store: InMemoryVenueCapabilitySnapshotStore,
    rule_store: InMemoryVenueInstrumentRuleSnapshotStore,
) -> DeterministicVenueCapabilityResolutionGateway:
    return DeterministicVenueCapabilityResolutionGateway(
        venue_snapshot_store=venue_store,
        instrument_rule_store=rule_store,
    )


def _stores_with(
    *,
    venue_snapshot: object | None = None,
    instrument_rules: object | None = None,
) -> tuple[InMemoryVenueCapabilitySnapshotStore, InMemoryVenueInstrumentRuleSnapshotStore]:
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    if venue_snapshot is not None:
        venue_store.put(venue_snapshot)
    if instrument_rules is not None:
        rule_store.put(instrument_rules)
    return venue_store, rule_store


def test_missing_venue_snapshot_returns_missing() -> None:
    venue_store, rule_store = _stores_with(instrument_rules=rules())
    decision = _gateway(venue_store, rule_store).resolve(_request())
    assert decision.ready is False
    assert decision.reason is VenueCapabilityResolutionReason.VENUE_SNAPSHOT_MISSING
    assert decision.venue_validation_context is None


def test_missing_instrument_rules_returns_missing() -> None:
    venue_store, rule_store = _stores_with(venue_snapshot=venue())
    decision = _gateway(venue_store, rule_store).resolve(_request())
    assert decision.ready is False
    assert decision.reason is VenueCapabilityResolutionReason.INSTRUMENT_RULES_MISSING
    assert decision.venue_snapshot is not None
    assert decision.venue_validation_context is None


def test_fresh_snapshots_return_ready() -> None:
    venue_store, rule_store = _stores_with(venue_snapshot=venue(), instrument_rules=rules())
    decision = _gateway(venue_store, rule_store).resolve(_request())
    assert decision.ready is True
    assert decision.reason is VenueCapabilityResolutionReason.READY
    assert decision.freshness_check is not None
    assert decision.freshness_decision is not None
    assert decision.venue_validation_context is not None


def test_stale_venue_snapshot_returns_freshness_rejected() -> None:
    stale = venue(captured_at=NOW - timedelta(milliseconds=2))
    venue_store, rule_store = _stores_with(venue_snapshot=stale, instrument_rules=rules())
    decision = _gateway(venue_store, rule_store).resolve(
        _request(freshness_policy=_policy(max_age_ms=1))
    )
    assert decision.reason is VenueCapabilityResolutionReason.FRESHNESS_REJECTED
    assert decision.freshness_decision is not None
    assert decision.freshness_decision.reason is (
        CapabilityFreshnessDecisionReason.VENUE_SNAPSHOT_STALE
    )
    assert decision.venue_validation_context is None


def test_stale_instrument_rules_returns_freshness_rejected() -> None:
    stale = rules(captured_at=NOW - timedelta(milliseconds=2))
    venue_store, rule_store = _stores_with(venue_snapshot=venue(), instrument_rules=stale)
    decision = _gateway(venue_store, rule_store).resolve(
        _request(freshness_policy=_policy(max_age_ms=1))
    )
    assert decision.reason is VenueCapabilityResolutionReason.FRESHNESS_REJECTED
    assert decision.freshness_decision is not None
    assert decision.freshness_decision.reason is (
        CapabilityFreshnessDecisionReason.INSTRUMENT_RULES_STALE
    )
    assert decision.venue_validation_context is None


def test_future_venue_snapshot_returns_freshness_rejected() -> None:
    future = venue(captured_at=NOW + timedelta(milliseconds=1))
    venue_store, rule_store = _stores_with(venue_snapshot=future, instrument_rules=rules())
    decision = _gateway(venue_store, rule_store).resolve(_request())
    assert decision.reason is VenueCapabilityResolutionReason.FRESHNESS_REJECTED
    assert decision.freshness_decision is not None
    assert decision.freshness_decision.reason is (
        CapabilityFreshnessDecisionReason.VENUE_SNAPSHOT_FROM_FUTURE
    )


def test_degraded_source_returns_freshness_rejected_in_strict_mode() -> None:
    venue_store, rule_store = _stores_with(venue_snapshot=venue(), instrument_rules=rules())
    decision = _gateway(venue_store, rule_store).resolve(
        _request(source_health=CapabilitySourceHealth.DEGRADED)
    )
    assert decision.reason is VenueCapabilityResolutionReason.FRESHNESS_REJECTED
    assert decision.freshness_decision is not None
    assert decision.freshness_decision.reason is (
        CapabilityFreshnessDecisionReason.SOURCE_HEALTH_DEGRADED
    )


def test_disabled_freshness_policy_can_return_ready_with_policy_disabled() -> None:
    old_venue = venue(captured_at=NOW - timedelta(days=365))
    old_rules = rules(captured_at=NOW - timedelta(days=365))
    venue_store, rule_store = _stores_with(
        venue_snapshot=old_venue,
        instrument_rules=old_rules,
    )
    decision = _gateway(venue_store, rule_store).resolve(
        _request(freshness_policy=_disabled_policy())
    )
    assert decision.ready is True
    assert decision.freshness_decision is not None
    assert decision.freshness_decision.reason is (
        CapabilityFreshnessDecisionReason.POLICY_DISABLED
    )


def test_latest_venue_snapshot_chosen_by_captured_at() -> None:
    older = venue(snapshot_id=VenueCapabilitySnapshotId(value="venue-cap-1"))
    newer = venue(
        snapshot_id=VenueCapabilitySnapshotId(value="venue-cap-2"),
        captured_at=NOW + timedelta(milliseconds=1),
    )
    venue_store, rule_store = _stores_with(instrument_rules=rules())
    venue_store.put(newer)
    venue_store.put(older)
    decision = _gateway(venue_store, rule_store).resolve(
        _request(checked_at=NOW + timedelta(milliseconds=1))
    )
    assert decision.venue_snapshot == newer


def test_latest_instrument_rules_chosen_by_captured_at() -> None:
    older = rules(snapshot_id=VenueInstrumentRuleSnapshotId(value="rules-1"))
    newer = rules(
        snapshot_id=VenueInstrumentRuleSnapshotId(value="rules-2"),
        captured_at=NOW + timedelta(milliseconds=1),
    )
    venue_store, rule_store = _stores_with(venue_snapshot=venue())
    rule_store.put(newer)
    rule_store.put(older)
    decision = _gateway(venue_store, rule_store).resolve(
        _request(checked_at=NOW + timedelta(milliseconds=1))
    )
    assert decision.instrument_rules == newer


def test_same_captured_at_tie_breaks_by_snapshot_id() -> None:
    lower = venue(snapshot_id=VenueCapabilitySnapshotId(value="venue-cap-1"))
    higher = venue(snapshot_id=VenueCapabilitySnapshotId(value="venue-cap-2"))
    venue_store, rule_store = _stores_with(instrument_rules=rules())
    venue_store.put(lower)
    venue_store.put(higher)
    decision = _gateway(venue_store, rule_store).resolve(_request())
    assert decision.venue_snapshot == higher


def test_instrument_rules_same_captured_at_tie_breaks_by_snapshot_id() -> None:
    lower = rules(snapshot_id=VenueInstrumentRuleSnapshotId(value="rules-1"))
    higher = rules(snapshot_id=VenueInstrumentRuleSnapshotId(value="rules-2"))
    venue_store, rule_store = _stores_with(venue_snapshot=venue())
    rule_store.put(lower)
    rule_store.put(higher)
    decision = _gateway(venue_store, rule_store).resolve(_request())
    assert decision.instrument_rules == higher


def test_gateway_never_fabricates_snapshots() -> None:
    venue_store, rule_store = _stores_with()
    decision = _gateway(venue_store, rule_store).resolve(_request())
    assert decision.venue_snapshot is None
    assert decision.instrument_rules is None
    assert decision.venue_validation_context is None


def test_gateway_does_not_validate_order_capability_it_only_builds_context() -> None:
    off_tick_order = order(order_type=OrderType.LIMIT, limit_price="100.05")
    venue_store, rule_store = _stores_with(venue_snapshot=venue(), instrument_rules=rules())
    decision = _gateway(venue_store, rule_store).resolve(
        _request(order_intent=off_tick_order)
    )
    assert decision.ready is True
    assert decision.venue_validation_context is not None
    assert decision.venue_validation_context.order_intent == off_tick_order
