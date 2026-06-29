from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from tests.unit.capability_freshness_fixtures import (
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
    deterministic_execution_admission_request_id,
)
from futures_bot.domain.ids import (
    VenueCapabilityFreshnessPolicyId,
    VenueInstrumentRuleSnapshotId,
)
from futures_bot.domain.order_lifecycle import (
    OrderIntent,
    OrderIntentKind,
    OrderLifecycleEventKind,
    OrderLifecycleState,
    OrderSide,
    OrderType,
    ReplaceOrderIntent,
)
from futures_bot.domain.venue_capabilities import (
    VenueInstrumentRuleSnapshot,
    VenueTradingStatus,
)
from futures_bot.domain.venue_capability_freshness import (
    CapabilityFreshnessDecisionReason,
    CapabilitySourceHealth,
    VenueCapabilityFreshnessCheck,
    VenueCapabilityFreshnessPolicy,
)
from futures_bot.execution_manager.coordinator import DeterministicExecutionManagerCoordinator
from futures_bot.order_lifecycle.in_memory import (
    InMemoryExecutionOrderRecordStore,
    InMemoryExecutionReconciliationStore,
    InMemoryOrderIntentJournal,
    InMemoryOrderLifecycleEventStore,
)


class _ExplodingCapabilityGate:
    def check(self, check: object) -> object:
        raise AssertionError("capability gate should not run")


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


def _coordinator() -> tuple[
    DeterministicExecutionManagerCoordinator,
    InMemoryExecutionOrderRecordStore,
    InMemoryOrderIntentJournal,
]:
    coordinator, records, _lifecycle, journal = _coordinator_with_lifecycle()
    return coordinator, records, journal


def _coordinator_with_lifecycle(
    *,
    capability_gate: Any = None,
) -> tuple[
    DeterministicExecutionManagerCoordinator,
    InMemoryExecutionOrderRecordStore,
    InMemoryOrderLifecycleEventStore,
    InMemoryOrderIntentJournal,
]:
    records = InMemoryExecutionOrderRecordStore()
    journal = InMemoryOrderIntentJournal()
    lifecycle = InMemoryOrderLifecycleEventStore()
    coordinator = DeterministicExecutionManagerCoordinator(
        intent_journal=journal,
        lifecycle_event_store=lifecycle,
        order_record_store=records,
        reconciliation_store=InMemoryExecutionReconciliationStore(),
        capability_gate=cast(Any, capability_gate),
    )
    return coordinator, records, lifecycle, journal


def _order_request(
    order_intent: OrderIntent,
    *,
    ctx: object,
    freshness: VenueCapabilityFreshnessCheck | None,
) -> ExecutionAdmissionRequest:
    return ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order_intent,
        order_flow_permission=permission(),
        venue_validation_context=ctx,
        freshness_check=freshness,
        require_venue_capability_validation=True,
        require_fresh_capability_snapshot=True,
        requested_at=NOW,
        requested_by="freshness-integration",
    )


def _missing_freshness_order_request(order_intent: OrderIntent) -> ExecutionAdmissionRequest:
    request = ExecutionAdmissionRequest.model_construct(
        request_id=None,
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order_intent,
        cancel_intent=None,
        replace_intent=None,
        order_flow_permission=permission(),
        venue_validation_context=context(order_intent),
        freshness_check=None,
        require_venue_capability_validation=True,
        require_fresh_capability_snapshot=True,
        requested_at=NOW,
        requested_by="freshness-integration",
        correlation_id=None,
    )
    object.__setattr__(request, "request_id", deterministic_execution_admission_request_id(request))
    return request


def _admit_order(
    coordinator: DeterministicExecutionManagerCoordinator,
    order_intent: OrderIntent,
) -> None:
    coordinator.admit(
        ExecutionAdmissionRequest(
            request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
            order_intent=order_intent,
            order_flow_permission=permission(),
            requested_at=NOW,
            requested_by="setup",
        )
    )


def _replace_request(
    original: OrderIntent,
    replacement: OrderIntent,
    *,
    ctx: object,
    freshness: VenueCapabilityFreshnessCheck,
) -> ExecutionAdmissionRequest:
    assert original.client_order_id is not None
    return ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.REPLACE_INTENT,
        replace_intent=ReplaceOrderIntent(
            target_client_order_id=original.client_order_id,
            target_intent_kind=original.intent_kind,
            replacement_order=replacement,
            replace_reason="freshness-test",
            created_at=NOW,
        ),
        order_flow_permission=permission(),
        venue_validation_context=ctx,
        freshness_check=freshness,
        require_venue_capability_validation=True,
        require_fresh_capability_snapshot=True,
        requested_at=NOW,
        requested_by="freshness-integration",
    )


def _mismatched_rule_snapshots() -> tuple[
    VenueInstrumentRuleSnapshot,
    VenueInstrumentRuleSnapshot,
]:
    return (
        rules(snapshot_id=VenueInstrumentRuleSnapshotId(value="rules-A")),
        rules(snapshot_id=VenueInstrumentRuleSnapshotId(value="rules-B")),
    )


def test_runtime_blocked_order_does_not_run_freshness_or_capability() -> None:
    coordinator, records, _ = _coordinator()
    order_intent = order()
    stale = venue(captured_at=NOW - timedelta(milliseconds=2))
    request = ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order_intent,
        order_flow_permission=permission(allow_new_entries=False),
        venue_validation_context=context(order_intent, venue_snapshot=stale),
        freshness_check=_freshness(venue_snapshot=stale, policy=_policy(max_age_ms=1)),
        require_venue_capability_validation=True,
        require_fresh_capability_snapshot=True,
        requested_at=NOW,
        requested_by="freshness-integration",
    )
    decision = coordinator.admit(request)
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_PERMISSION
    assert decision.freshness_checked is False
    assert decision.freshness_reason is None
    assert records.get_by_client_order_id(order_intent.client_order_id) is None


def test_runtime_allowed_stale_freshness_rejects_with_no_active_record() -> None:
    coordinator, records, _ = _coordinator()
    order_intent = order()
    stale = venue(captured_at=NOW - timedelta(milliseconds=2))
    decision = coordinator.admit(
        _order_request(
            order_intent,
            ctx=context(order_intent, venue_snapshot=stale),
            freshness=_freshness(venue_snapshot=stale, policy=_policy(max_age_ms=1)),
        )
    )
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_CAPABILITY_FRESHNESS
    assert decision.freshness_reason == CapabilityFreshnessDecisionReason.VENUE_SNAPSHOT_STALE
    assert decision.venue_validation_reason is None
    assert records.get_by_client_order_id(order_intent.client_order_id) is None


def test_runtime_allowed_missing_freshness_context_rejects_with_no_active_record() -> None:
    coordinator, records, _ = _coordinator()
    order_intent = order()
    decision = coordinator.admit(_missing_freshness_order_request(order_intent))
    assert decision.reason is ExecutionAdmissionDecisionReason.FRESHNESS_CONTEXT_REQUIRED
    assert decision.freshness_checked is False
    assert records.get_by_client_order_id(order_intent.client_order_id) is None


def test_order_freshness_context_mismatch_returns_decision_not_exception() -> None:
    coordinator, _records, _lifecycle, _journal = _coordinator_with_lifecycle(
        capability_gate=_ExplodingCapabilityGate()
    )
    order_intent = order()
    rules_a, rules_b = _mismatched_rule_snapshots()
    decision = coordinator.admit(
        _order_request(
            order_intent,
            ctx=context(order_intent, instrument_rules=rules_a),
            freshness=_freshness(instrument_rules=rules_b),
        )
    )
    assert decision.accepted is False
    assert decision.reason is ExecutionAdmissionDecisionReason.FRESHNESS_CONTEXT_MISMATCH
    assert decision.freshness_checked is False
    assert decision.freshness_reason == "FRESHNESS_CONTEXT_MISMATCH"
    assert decision.venue_validation_reason is None


def test_order_freshness_context_mismatch_creates_no_active_record() -> None:
    coordinator, records, _lifecycle, _journal = _coordinator_with_lifecycle()
    order_intent = order()
    rules_a, rules_b = _mismatched_rule_snapshots()
    coordinator.admit(
        _order_request(
            order_intent,
            ctx=context(order_intent, instrument_rules=rules_a),
            freshness=_freshness(instrument_rules=rules_b),
        )
    )
    assert records.get_by_client_order_id(order_intent.client_order_id) is None


def test_order_freshness_context_mismatch_does_not_run_venue_validation() -> None:
    coordinator, _records, _lifecycle, _journal = _coordinator_with_lifecycle(
        capability_gate=_ExplodingCapabilityGate()
    )
    order_intent = order()
    rules_a, rules_b = _mismatched_rule_snapshots()
    decision = coordinator.admit(
        _order_request(
            order_intent,
            ctx=context(order_intent, instrument_rules=rules_a),
            freshness=_freshness(instrument_rules=rules_b),
        )
    )
    assert decision.reason is ExecutionAdmissionDecisionReason.FRESHNESS_CONTEXT_MISMATCH
    assert decision.venue_validation_details is None


def test_order_freshness_context_mismatch_appends_auditable_rejection_event() -> None:
    coordinator, _records, lifecycle, _journal = _coordinator_with_lifecycle()
    order_intent = order()
    rules_a, rules_b = _mismatched_rule_snapshots()
    decision = coordinator.admit(
        _order_request(
            order_intent,
            ctx=context(order_intent, instrument_rules=rules_a),
            freshness=_freshness(instrument_rules=rules_b),
        )
    )
    events = lifecycle.list_events()
    rejection_events = [
        event
        for event in events
        if event.event_kind is OrderLifecycleEventKind.REJECTED_BY_VALIDATION
    ]
    assert len(rejection_events) == 1
    assert rejection_events[0].event_id in decision.lifecycle_event_ids
    assert rejection_events[0].payload["freshness_reason"] == (
        "FRESHNESS_CONTEXT_MISMATCH"
    )
    assert rejection_events[0].payload["freshness_details"]["mismatch"] == (
        "instrument_rules"
    )


def test_runtime_allowed_fresh_but_venue_invalid_rejects_by_venue_capability() -> None:
    coordinator, records, _ = _coordinator()
    order_intent = order()
    disabled = venue(trading_status=VenueTradingStatus.DISABLED)
    rule_snapshot = rules()
    decision = coordinator.admit(
        _order_request(
            order_intent,
            ctx=context(order_intent, venue_snapshot=disabled, instrument_rules=rule_snapshot),
            freshness=_freshness(venue_snapshot=disabled, instrument_rules=rule_snapshot),
        )
    )
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY
    assert decision.freshness_reason == CapabilityFreshnessDecisionReason.FRESH
    assert decision.venue_validation_reason is not None
    assert records.get_by_client_order_id(order_intent.client_order_id) is None


def test_runtime_allowed_fresh_and_venue_valid_creates_local_accepted_record() -> None:
    coordinator, records, _ = _coordinator()
    order_intent = order()
    decision = coordinator.admit(
        _order_request(
            order_intent,
            ctx=context(order_intent),
            freshness=_freshness(),
        )
    )
    assert decision.accepted is True
    assert decision.freshness_reason == CapabilityFreshnessDecisionReason.FRESH
    record = records.get_by_client_order_id(order_intent.client_order_id)
    assert record is not None
    assert record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
    assert record.lifecycle_state is not OrderLifecycleState.SUBMITTED_TO_VENUE


def test_replace_target_missing_does_not_run_freshness() -> None:
    coordinator, _records, _ = _coordinator()
    original = order(intent_kind=OrderIntentKind.EXIT, reduce_only=True, side=OrderSide.SELL)
    replacement = order(
        intent_kind=OrderIntentKind.EXIT,
        reduce_only=True,
        side=OrderSide.SELL,
        quantity="2",
    )
    decision = coordinator.admit(
        _replace_request(
            original,
            replacement,
            ctx=context(replacement),
            freshness=_freshness(),
        )
    )
    assert decision.reason is ExecutionAdmissionDecisionReason.RECONCILIATION_REQUIRED
    assert decision.freshness_checked is False


def test_replace_scope_mismatch_does_not_run_freshness() -> None:
    coordinator, records, _ = _coordinator()
    original = order()
    _admit_order(coordinator, original)
    replacement = order(instrument_id="ETH-PERP")
    eth_rules = rules(instrument_id="ETH-PERP")
    decision = coordinator.admit(
        _replace_request(
            original,
            replacement,
            ctx=context(replacement, instrument_rules=eth_rules),
            freshness=_freshness(
                instrument_id="ETH-PERP",
                instrument_rules=eth_rules,
            ),
        )
    )
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VALIDATION
    assert decision.freshness_checked is False
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


def test_replace_stale_freshness_rejects_without_updating_target() -> None:
    coordinator, records, _ = _coordinator()
    original = order()
    _admit_order(coordinator, original)
    replacement = order(quantity="2")
    stale = venue(captured_at=NOW - timedelta(milliseconds=2))
    decision = coordinator.admit(
        _replace_request(
            original,
            replacement,
            ctx=context(replacement, venue_snapshot=stale),
            freshness=_freshness(venue_snapshot=stale, policy=_policy(max_age_ms=1)),
        )
    )
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_CAPABILITY_FRESHNESS
    assert decision.freshness_details == {
        "max_venue_snapshot_age_ms": 1,
        "venue_snapshot_age_ms": 2,
    }
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
    assert records.get_by_client_order_id(replacement.client_order_id) is None


def test_replace_fresh_but_venue_invalid_rejects_without_updating_target() -> None:
    coordinator, records, _ = _coordinator()
    original = order()
    _admit_order(coordinator, original)
    replacement = order(quantity="2")
    disabled = venue(trading_status=VenueTradingStatus.DISABLED)
    rule_snapshot = rules()
    decision = coordinator.admit(
        _replace_request(
            original,
            replacement,
            ctx=context(replacement, venue_snapshot=disabled, instrument_rules=rule_snapshot),
            freshness=_freshness(venue_snapshot=disabled, instrument_rules=rule_snapshot),
        )
    )
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
    assert records.get_by_client_order_id(replacement.client_order_id) is None


def test_replace_fresh_and_venue_valid_updates_target_and_creates_replacement() -> None:
    coordinator, records, _ = _coordinator()
    original = order()
    _admit_order(coordinator, original)
    replacement = order(quantity="2")
    decision = coordinator.admit(
        _replace_request(
            original,
            replacement,
            ctx=context(replacement),
            freshness=_freshness(),
        )
    )
    assert decision.accepted is True
    target = records.get_by_client_order_id(original.client_order_id)
    replacement_record = records.get_by_client_order_id(replacement.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.REPLACE_REQUESTED
    assert replacement_record is not None
    assert replacement_record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


def _protective_stop_order(**overrides: object) -> OrderIntent:
    values: dict[str, object] = {
        "intent_kind": OrderIntentKind.PROTECTIVE_STOP,
        "reduce_only": True,
        "side": OrderSide.SELL,
        "order_type": OrderType.STOP_MARKET,
        "stop_price": "90",
    }
    values.update(overrides)
    return order(**values)


def test_replace_freshness_context_mismatch_returns_decision_not_exception() -> None:
    coordinator, records, _lifecycle, _journal = _coordinator_with_lifecycle(
        capability_gate=_ExplodingCapabilityGate()
    )
    original = _protective_stop_order()
    _admit_order(coordinator, original)
    replacement = _protective_stop_order(stop_price="91")
    rules_a, rules_b = _mismatched_rule_snapshots()
    decision = coordinator.admit(
        _replace_request(
            original,
            replacement,
            ctx=context(replacement, instrument_rules=rules_a),
            freshness=_freshness(instrument_rules=rules_b),
        )
    )
    assert decision.accepted is False
    assert decision.reason is ExecutionAdmissionDecisionReason.FRESHNESS_CONTEXT_MISMATCH
    assert decision.freshness_checked is False
    assert decision.venue_validation_reason is None
    assert records.get_by_client_order_id(replacement.client_order_id) is None


def test_replace_freshness_context_mismatch_does_not_update_target() -> None:
    coordinator, records, _lifecycle, _journal = _coordinator_with_lifecycle()
    original = _protective_stop_order()
    _admit_order(coordinator, original)
    replacement = _protective_stop_order(stop_price="91")
    rules_a, rules_b = _mismatched_rule_snapshots()
    coordinator.admit(
        _replace_request(
            original,
            replacement,
            ctx=context(replacement, instrument_rules=rules_a),
            freshness=_freshness(instrument_rules=rules_b),
        )
    )
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


def test_replace_freshness_context_mismatch_does_not_create_replacement_record() -> None:
    coordinator, records, _lifecycle, _journal = _coordinator_with_lifecycle()
    original = _protective_stop_order()
    _admit_order(coordinator, original)
    replacement = _protective_stop_order(stop_price="91")
    rules_a, rules_b = _mismatched_rule_snapshots()
    coordinator.admit(
        _replace_request(
            original,
            replacement,
            ctx=context(replacement, instrument_rules=rules_a),
            freshness=_freshness(instrument_rules=rules_b),
        )
    )
    assert records.get_by_client_order_id(replacement.client_order_id) is None


def test_replace_freshness_context_mismatch_does_not_run_venue_validation() -> None:
    coordinator, records, _lifecycle, _journal = _coordinator_with_lifecycle(
        capability_gate=_ExplodingCapabilityGate()
    )
    original = _protective_stop_order()
    _admit_order(coordinator, original)
    replacement = _protective_stop_order(stop_price="91")
    rules_a, rules_b = _mismatched_rule_snapshots()
    decision = coordinator.admit(
        _replace_request(
            original,
            replacement,
            ctx=context(replacement, instrument_rules=rules_a),
            freshness=_freshness(instrument_rules=rules_b),
        )
    )
    assert decision.reason is ExecutionAdmissionDecisionReason.FRESHNESS_CONTEXT_MISMATCH
    assert decision.venue_validation_reason is None
    assert records.get_by_client_order_id(replacement.client_order_id) is None
