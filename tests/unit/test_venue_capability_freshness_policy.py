from __future__ import annotations

from datetime import timedelta

import pytest
from tests.unit.capability_freshness_fixtures import NOW, rules, venue

from futures_bot.domain.ids import VenueCapabilityFreshnessPolicyId
from futures_bot.domain.venue_capability_freshness import (
    CapabilityFreshnessDecisionReason,
    CapabilityFreshnessMode,
    CapabilitySourceHealth,
    VenueCapabilityFreshnessCheck,
    VenueCapabilityFreshnessPolicy,
)
from futures_bot.venue_capabilities.freshness import validate_venue_capability_freshness


def _policy(**overrides: object) -> VenueCapabilityFreshnessPolicy:
    values: dict[str, object] = {
        "policy_id": VenueCapabilityFreshnessPolicyId("policy-1"),
        "max_venue_snapshot_age_ms": 60_000,
        "max_instrument_rules_age_ms": 60_000,
    }
    values.update(overrides)
    return VenueCapabilityFreshnessPolicy(**values)


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


def _reason(check: VenueCapabilityFreshnessCheck) -> CapabilityFreshnessDecisionReason:
    return validate_venue_capability_freshness(check).reason


def test_fresh_snapshots_pass() -> None:
    decision = validate_venue_capability_freshness(_check())
    assert decision.fresh is True
    assert decision.reason is CapabilityFreshnessDecisionReason.FRESH


def test_missing_venue_snapshot_rejects() -> None:
    assert _reason(_check(venue_snapshot=None)) is (
        CapabilityFreshnessDecisionReason.VENUE_SNAPSHOT_MISSING
    )


def test_missing_instrument_rules_rejects() -> None:
    assert _reason(_check(instrument_rules=None)) is (
        CapabilityFreshnessDecisionReason.INSTRUMENT_RULES_MISSING
    )


def test_venue_snapshot_stale_rejects() -> None:
    stale = venue(captured_at=NOW - timedelta(milliseconds=60_001))
    assert _reason(_check(venue_snapshot=stale)) is (
        CapabilityFreshnessDecisionReason.VENUE_SNAPSHOT_STALE
    )


def test_instrument_rules_stale_rejects() -> None:
    stale = rules(captured_at=NOW - timedelta(milliseconds=60_001))
    assert _reason(_check(instrument_rules=stale)) is (
        CapabilityFreshnessDecisionReason.INSTRUMENT_RULES_STALE
    )


def test_venue_snapshot_future_rejects() -> None:
    future = venue(captured_at=NOW + timedelta(milliseconds=1))
    assert _reason(_check(venue_snapshot=future)) is (
        CapabilityFreshnessDecisionReason.VENUE_SNAPSHOT_FROM_FUTURE
    )


def test_instrument_rules_future_rejects() -> None:
    future = rules(captured_at=NOW + timedelta(milliseconds=1))
    assert _reason(_check(instrument_rules=future)) is (
        CapabilityFreshnessDecisionReason.INSTRUMENT_RULES_FROM_FUTURE
    )


@pytest.mark.parametrize(
    ("health", "expected"),
    [
        (
            CapabilitySourceHealth.UNAVAILABLE,
            CapabilityFreshnessDecisionReason.SOURCE_HEALTH_UNAVAILABLE,
        ),
        (
            CapabilitySourceHealth.UNKNOWN,
            CapabilityFreshnessDecisionReason.SOURCE_HEALTH_UNKNOWN,
        ),
        (
            CapabilitySourceHealth.DEGRADED,
            CapabilityFreshnessDecisionReason.SOURCE_HEALTH_DEGRADED,
        ),
    ],
)
def test_source_health_rejections(
    health: CapabilitySourceHealth,
    expected: CapabilityFreshnessDecisionReason,
) -> None:
    assert _reason(_check(source_health=health)) is expected


def test_policy_disabled_passes_with_policy_disabled() -> None:
    policy = _policy(
        mode=CapabilityFreshnessMode.DISABLED,
        reject_future_snapshots=False,
        reject_degraded_source=False,
        reject_unknown_source=False,
        require_venue_snapshot=False,
        require_instrument_rules=False,
    )
    decision = validate_venue_capability_freshness(
        _check(policy=policy, venue_snapshot=None, instrument_rules=None)
    )
    assert decision.fresh is True
    assert decision.reason is CapabilityFreshnessDecisionReason.POLICY_DISABLED


def test_clock_skew_tolerance_permits_small_future_timestamp() -> None:
    policy = _policy(max_clock_skew_ms=500)
    future = venue(captured_at=NOW + timedelta(milliseconds=500))
    decision = validate_venue_capability_freshness(
        _check(policy=policy, venue_snapshot=future)
    )
    assert decision.fresh is True
    assert decision.venue_snapshot_age_ms == 0


def test_age_equal_to_max_passes() -> None:
    exact = venue(captured_at=NOW - timedelta(milliseconds=60_000))
    assert _reason(_check(venue_snapshot=exact)) is CapabilityFreshnessDecisionReason.FRESH


def test_age_greater_than_max_rejects() -> None:
    stale = venue(captured_at=NOW - timedelta(milliseconds=60_001))
    assert _reason(_check(venue_snapshot=stale)) is (
        CapabilityFreshnessDecisionReason.VENUE_SNAPSHOT_STALE
    )
