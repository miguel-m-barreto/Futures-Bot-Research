from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError
from tests.unit.capability_freshness_fixtures import NOW, rules, venue

from futures_bot.domain.ids import VenueCapabilityFreshnessPolicyId
from futures_bot.domain.venue_capability_freshness import (
    CapabilityFreshnessDecisionReason,
    CapabilityFreshnessMode,
    CapabilitySourceHealth,
    VenueCapabilityFreshnessCheck,
    VenueCapabilityFreshnessDecision,
    VenueCapabilityFreshnessPolicy,
)
from futures_bot.venue_capabilities.in_memory import (
    InMemoryVenueCapabilityFreshnessDecisionStore,
)


def _policy() -> VenueCapabilityFreshnessPolicy:
    return VenueCapabilityFreshnessPolicy.strict(
        max_venue_snapshot_age_ms=60_000,
        max_instrument_rules_age_ms=60_000,
    )


def _check(**overrides: object) -> VenueCapabilityFreshnessCheck:
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


def test_strict_policy_defaults_are_hard_safety() -> None:
    policy = _policy()
    assert policy.mode is CapabilityFreshnessMode.STRICT
    assert policy.reject_future_snapshots is True
    assert policy.reject_degraded_source is True
    assert policy.reject_unknown_source is True
    assert policy.require_venue_snapshot is True
    assert policy.require_instrument_rules is True


@pytest.mark.parametrize(
    "field",
    ["max_venue_snapshot_age_ms", "max_instrument_rules_age_ms"],
)
def test_policy_rejects_invalid_max_ages(field: str) -> None:
    values = {
        "policy_id": VenueCapabilityFreshnessPolicyId("policy-1"),
        "max_venue_snapshot_age_ms": 1,
        "max_instrument_rules_age_ms": 1,
    }
    values[field] = 0
    with pytest.raises(ValidationError):
        VenueCapabilityFreshnessPolicy(**values)


def test_freshness_check_sets_deterministic_check_id() -> None:
    check = _check()
    same = _check()
    assert check.check_id == same.check_id


def test_freshness_check_rejects_venue_mismatch() -> None:
    with pytest.raises(ValidationError):
        _check(venue_snapshot=venue(venue_id="venue-2"))


def test_freshness_check_rejects_instrument_mismatch() -> None:
    with pytest.raises(ValidationError):
        _check(instrument_rules=rules(instrument_id="ETH-PERP"))


def test_freshness_decision_enforces_fresh_reason_consistency() -> None:
    check = _check()
    assert check.check_id is not None
    with pytest.raises(ValidationError):
        VenueCapabilityFreshnessDecision(
            check_id=check.check_id,
            fresh=True,
            reason=CapabilityFreshnessDecisionReason.VENUE_SNAPSHOT_STALE,
            source_health=CapabilitySourceHealth.HEALTHY,
            checked_at=NOW,
            details={},
        )


def test_freshness_decision_sets_deterministic_decision_id() -> None:
    check = _check()
    assert check.check_id is not None
    values = {
        "check_id": check.check_id,
        "fresh": False,
        "reason": CapabilityFreshnessDecisionReason.VENUE_SNAPSHOT_STALE,
        "venue_snapshot_age_ms": 60_001,
        "source_health": CapabilitySourceHealth.HEALTHY,
        "checked_at": NOW,
        "details": {"max_venue_snapshot_age_ms": 60_000},
    }
    assert VenueCapabilityFreshnessDecision(**values).decision_id == (
        VenueCapabilityFreshnessDecision(**values).decision_id
    )


def test_policy_disabled_can_be_explicit() -> None:
    policy = VenueCapabilityFreshnessPolicy(
        policy_id=VenueCapabilityFreshnessPolicyId("policy-disabled"),
        mode=CapabilityFreshnessMode.DISABLED,
        max_venue_snapshot_age_ms=1,
        max_instrument_rules_age_ms=1,
        max_clock_skew_ms=0,
        reject_future_snapshots=False,
        reject_degraded_source=False,
        reject_unknown_source=False,
        require_venue_snapshot=False,
        require_instrument_rules=False,
    )
    check = _check(
        policy=policy,
        venue_snapshot=None,
        instrument_rules=None,
        checked_at=NOW + timedelta(days=365),
    )
    assert check.policy.mode is CapabilityFreshnessMode.DISABLED


def test_in_memory_freshness_decision_store_is_idempotent_and_ordered() -> None:
    check = _check()
    assert check.check_id is not None
    first = VenueCapabilityFreshnessDecision(
        check_id=check.check_id,
        fresh=True,
        reason=CapabilityFreshnessDecisionReason.FRESH,
        venue_snapshot_age_ms=0,
        instrument_rules_age_ms=0,
        source_health=CapabilitySourceHealth.HEALTHY,
        checked_at=NOW,
        details={"index": 1},
    )
    second_check = _check(correlation_id="second")
    assert second_check.check_id is not None
    second = VenueCapabilityFreshnessDecision(
        check_id=second_check.check_id,
        fresh=True,
        reason=CapabilityFreshnessDecisionReason.FRESH,
        venue_snapshot_age_ms=0,
        instrument_rules_age_ms=0,
        source_health=CapabilitySourceHealth.HEALTHY,
        checked_at=NOW,
        details={"index": 2},
    )
    store = InMemoryVenueCapabilityFreshnessDecisionStore()
    store.put(first)
    store.put(first)
    store.put(second)
    assert store.list_decisions() == (first, second)


def test_in_memory_freshness_decision_store_rejects_id_collision() -> None:
    check = _check()
    assert check.check_id is not None
    first = VenueCapabilityFreshnessDecision(
        check_id=check.check_id,
        fresh=True,
        reason=CapabilityFreshnessDecisionReason.FRESH,
        source_health=CapabilitySourceHealth.HEALTHY,
        checked_at=NOW,
        details={"index": 1},
    )
    collision = first.model_copy(update={"details": {"index": 999}})
    store = InMemoryVenueCapabilityFreshnessDecisionStore()
    store.put(first)
    with pytest.raises(ValueError):
        store.put(collision)
