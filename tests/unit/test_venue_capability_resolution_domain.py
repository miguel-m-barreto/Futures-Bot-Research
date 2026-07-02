from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.unit.capability_freshness_fixtures import NOW, context, order, rules, venue

from futures_bot.domain.ids import VenueCapabilityFreshnessPolicyId
from futures_bot.domain.venue_capability_freshness import (
    CapabilitySourceHealth,
    VenueCapabilityFreshnessCheck,
    VenueCapabilityFreshnessDecision,
    VenueCapabilityFreshnessPolicy,
)
from futures_bot.domain.venue_capability_resolution import (
    VenueCapabilityResolutionDecision,
    VenueCapabilityResolutionReason,
    VenueCapabilityResolutionRequest,
)


def _policy() -> VenueCapabilityFreshnessPolicy:
    return VenueCapabilityFreshnessPolicy.strict(
        policy_id=VenueCapabilityFreshnessPolicyId(value="resolution-policy"),
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


def _freshness_check() -> VenueCapabilityFreshnessCheck:
    return VenueCapabilityFreshnessCheck(
        venue_id="venue-1",
        instrument_id="BTC-PERP",
        venue_snapshot=venue(),
        instrument_rules=rules(),
        policy=_policy(),
        source_health=CapabilitySourceHealth.HEALTHY,
        checked_at=NOW,
    )


def _freshness_decision(
    freshness_check: VenueCapabilityFreshnessCheck,
) -> VenueCapabilityFreshnessDecision:
    assert freshness_check.check_id is not None
    return VenueCapabilityFreshnessDecision(
        check_id=freshness_check.check_id,
        fresh=True,
        reason="FRESH",
        venue_snapshot_age_ms=0,
        instrument_rules_age_ms=0,
        source_health=CapabilitySourceHealth.HEALTHY,
        checked_at=NOW,
        details={"source_health": "HEALTHY"},
    )


def test_resolution_request_sets_deterministic_id() -> None:
    assert _request().request_id == _request().request_id


def test_resolution_request_default_does_not_require_official_provenance() -> None:
    request = _request()

    assert request.require_official_source_provenance is False


def test_resolution_request_with_official_provenance_requirement_is_deterministic() -> None:
    left = VenueCapabilityResolutionRequest(
        order_intent=order(),
        checked_at=NOW,
        freshness_policy=_policy(),
        source_health=CapabilitySourceHealth.HEALTHY,
        require_official_source_provenance=True,
    )
    right = VenueCapabilityResolutionRequest(
        order_intent=order(),
        checked_at=NOW,
        freshness_policy=_policy(),
        source_health=CapabilitySourceHealth.HEALTHY,
        require_official_source_provenance=True,
    )

    assert left.request_id == right.request_id
    assert left.request_id != _request().request_id


def test_resolution_decision_ready_requires_ready_reason() -> None:
    request = _request()
    assert request.request_id is not None
    freshness_check = _freshness_check()
    with pytest.raises(ValidationError):
        VenueCapabilityResolutionDecision(
            request_id=request.request_id,
            ready=True,
            reason=VenueCapabilityResolutionReason.FRESHNESS_REJECTED,
            venue_snapshot=venue(),
            instrument_rules=rules(),
            freshness_check=freshness_check,
            freshness_decision=_freshness_decision(freshness_check),
            venue_validation_context=context(order()),
            checked_at=NOW,
            details={},
        )


def test_ready_decision_requires_all_resolved_artifacts() -> None:
    request = _request()
    assert request.request_id is not None
    with pytest.raises(ValidationError):
        VenueCapabilityResolutionDecision(
            request_id=request.request_id,
            ready=True,
            reason=VenueCapabilityResolutionReason.READY,
            checked_at=NOW,
            details={},
        )


def test_not_ready_decision_forbids_ready_reason() -> None:
    request = _request()
    assert request.request_id is not None
    with pytest.raises(ValidationError):
        VenueCapabilityResolutionDecision(
            request_id=request.request_id,
            ready=False,
            reason=VenueCapabilityResolutionReason.READY,
            checked_at=NOW,
            details={},
        )


def test_resolution_decision_details_must_be_json_compatible() -> None:
    request = _request()
    assert request.request_id is not None
    with pytest.raises(ValidationError):
        VenueCapabilityResolutionDecision(
            request_id=request.request_id,
            ready=False,
            reason=VenueCapabilityResolutionReason.VENUE_SNAPSHOT_MISSING,
            checked_at=NOW,
            details={"bad": object()},
        )


def test_resolution_decision_can_carry_provenance_status() -> None:
    request = _request()
    assert request.request_id is not None
    decision = VenueCapabilityResolutionDecision(
        request_id=request.request_id,
        ready=False,
        reason=VenueCapabilityResolutionReason.SOURCE_RECORD_MISSING,
        provenance_checked=True,
        provenance_reason=VenueCapabilityResolutionReason.SOURCE_RECORD_MISSING.value,
        provenance_details={"snapshot_kind": "venue_snapshot"},
        checked_at=NOW,
        details={"provenance_reason": "SOURCE_RECORD_MISSING"},
    )

    assert decision.provenance_checked is True
    assert decision.provenance_details == {"snapshot_kind": "venue_snapshot"}


def test_resolution_decision_provenance_details_must_be_json_compatible() -> None:
    request = _request()
    assert request.request_id is not None
    with pytest.raises(ValidationError):
        VenueCapabilityResolutionDecision(
            request_id=request.request_id,
            ready=False,
            reason=VenueCapabilityResolutionReason.SOURCE_RECORD_MISSING,
            provenance_checked=True,
            provenance_reason="SOURCE_RECORD_MISSING",
            provenance_details={"bad": object()},
            checked_at=NOW,
            details={},
        )
