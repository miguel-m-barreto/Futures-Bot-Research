from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from tests.unit.capability_freshness_fixtures import NOW, context, order, rules, venue

from futures_bot.domain.execution_capability_gate import (
    ExecutionCapabilityCheck,
    ExecutionCapabilityDecisionReason,
)
from futures_bot.domain.ids import (
    ExecutionCapabilityCheckId,
    VenueCapabilityFreshnessPolicyId,
)
from futures_bot.domain.venue_capabilities import (
    VenueOrderValidationReason,
    VenueTradingStatus,
)
from futures_bot.domain.venue_capability_freshness import (
    CapabilityFreshnessDecisionReason,
    CapabilitySourceHealth,
    VenueCapabilityFreshnessCheck,
    VenueCapabilityFreshnessPolicy,
)
from futures_bot.execution_manager import capability_gate as gate_module
from futures_bot.execution_manager.capability_gate import DeterministicExecutionCapabilityGate


def _policy(max_age_ms: int = 60_000) -> VenueCapabilityFreshnessPolicy:
    return VenueCapabilityFreshnessPolicy(
        policy_id=VenueCapabilityFreshnessPolicyId("policy-1"),
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


def _check(**overrides: object) -> ExecutionCapabilityCheck:
    order_intent = order()
    values: dict[str, object] = {
        "order_intent": order_intent,
        "venue_validation_context": context(order_intent),
        "freshness_check": _freshness(),
        "require_fresh_capability_snapshot": True,
        "requested_at": NOW,
        "requested_by": "gate-test",
    }
    values.update(overrides)
    return ExecutionCapabilityCheck(**values)


def test_check_requires_freshness_when_required() -> None:
    order_intent = order()
    with pytest.raises(ValidationError):
        ExecutionCapabilityCheck(
            order_intent=order_intent,
            venue_validation_context=context(order_intent),
            require_fresh_capability_snapshot=True,
            requested_at=NOW,
            requested_by="gate-test",
        )


def test_freshness_required_and_missing_rejects_before_venue_validation() -> None:
    order_intent = order()
    check = ExecutionCapabilityCheck.model_construct(
        check_id=ExecutionCapabilityCheckId("check-missing-freshness"),
        order_intent=order_intent,
        venue_validation_context=context(order_intent),
        freshness_check=None,
        require_fresh_capability_snapshot=True,
        requested_at=NOW,
        requested_by="gate-test",
        correlation_id=None,
    )
    decision = DeterministicExecutionCapabilityGate().check(check)
    assert decision.reason is ExecutionCapabilityDecisionReason.FRESHNESS_CONTEXT_REQUIRED
    assert decision.venue_validation_reason is None
    assert decision.freshness_checked is False


def test_stale_freshness_rejects_before_venue_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_validator(_context: object) -> Any:
        raise AssertionError("venue validator should not run")

    monkeypatch.setattr(
        gate_module,
        "validate_order_against_venue_capabilities",
        fail_validator,
    )
    stale = venue(captured_at=NOW - timedelta(milliseconds=2))
    check = _check(
        venue_validation_context=context(order(), venue_snapshot=stale),
        freshness_check=_freshness(venue_snapshot=stale, policy=_policy(max_age_ms=1)),
    )
    decision = DeterministicExecutionCapabilityGate().check(check)
    assert decision.reason is ExecutionCapabilityDecisionReason.REJECTED_BY_CAPABILITY_FRESHNESS
    assert decision.freshness_reason == CapabilityFreshnessDecisionReason.VENUE_SNAPSHOT_STALE
    assert decision.venue_validation_reason is None


def test_freshness_mismatch_rejects_before_venue_validation() -> None:
    order_intent = order()
    ctx = context(order_intent)
    different_venue = venue(source_hash="0" * 64)
    freshness = _freshness(venue_snapshot=different_venue)
    check = ExecutionCapabilityCheck.model_construct(
        check_id=ExecutionCapabilityCheckId("check-freshness-mismatch"),
        order_intent=order_intent,
        venue_validation_context=ctx,
        freshness_check=freshness,
        require_fresh_capability_snapshot=True,
        requested_at=NOW,
        requested_by="gate-test",
        correlation_id=None,
    )
    decision = DeterministicExecutionCapabilityGate().check(check)
    assert decision.reason is ExecutionCapabilityDecisionReason.FRESHNESS_CONTEXT_MISMATCH
    assert decision.venue_validation_reason is None


def test_freshness_pass_then_venue_valid_returns_executable() -> None:
    decision = DeterministicExecutionCapabilityGate().check(_check())
    assert decision.executable is True
    assert decision.reason is ExecutionCapabilityDecisionReason.EXECUTABLE
    assert decision.freshness_reason == CapabilityFreshnessDecisionReason.FRESH
    assert decision.venue_validation_reason == VenueOrderValidationReason.OK.value


def test_freshness_pass_then_venue_invalid_returns_venue_rejection() -> None:
    order_intent = order()
    disabled = venue(trading_status=VenueTradingStatus.DISABLED)
    rule_snapshot = rules()
    check = _check(
        order_intent=order_intent,
        venue_validation_context=context(
            order_intent,
            venue_snapshot=disabled,
            instrument_rules=rule_snapshot,
        ),
        freshness_check=_freshness(venue_snapshot=disabled, instrument_rules=rule_snapshot),
    )
    decision = DeterministicExecutionCapabilityGate().check(check)
    assert decision.reason is ExecutionCapabilityDecisionReason.REJECTED_BY_VENUE_CAPABILITY
    assert decision.freshness_reason == CapabilityFreshnessDecisionReason.FRESH
    assert decision.venue_validation_reason == (
        VenueOrderValidationReason.VENUE_TRADING_DISABLED.value
    )


def test_freshness_decision_details_are_preserved() -> None:
    stale = venue(captured_at=NOW - timedelta(milliseconds=2))
    check = _check(
        venue_validation_context=context(order(), venue_snapshot=stale),
        freshness_check=_freshness(venue_snapshot=stale, policy=_policy(max_age_ms=1)),
    )
    decision = DeterministicExecutionCapabilityGate().check(check)
    assert decision.freshness_details == {
        "max_venue_snapshot_age_ms": 1,
        "venue_snapshot_age_ms": 2,
    }
    assert decision.venue_validation_reason is None
