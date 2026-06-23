from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from futures_bot.domain.execution_manager import (
    ExecutionAdmissionDecisionReason,
    ExecutionAdmissionRequest,
    ExecutionAdmissionRequestKind,
)
from futures_bot.domain.ids import (
    DeadManSwitchCapabilityId,
    VenueCapabilitySnapshotId,
    VenueInstrumentRuleSnapshotId,
)
from futures_bot.domain.order_lifecycle import (
    OrderIntent,
    OrderIntentKind,
    OrderLifecycleState,
    OrderSide,
    OrderType,
    PositionSide,
    ReplaceOrderIntent,
)
from futures_bot.domain.runtime_control import (
    OrderFlowPermission,
    OrderFlowPermissionReason,
)
from futures_bot.domain.venue_capabilities import (
    DeadManSwitchCapability,
    DeadManSwitchScopeKind,
    FuturesContractKind,
    InstrumentTradingStatus,
    NotionalFilter,
    PriceFilter,
    QuantityFilter,
    VenueCapabilitySnapshot,
    VenueInstrumentRuleSnapshot,
    VenueOrderValidationContext,
    VenueOrderValidationReason,
    VenuePositionMode,
    VenueSelfTradePreventionMode,
    VenueTradingStatus,
)
from futures_bot.execution_manager.coordinator import DeterministicExecutionManagerCoordinator
from futures_bot.order_lifecycle.in_memory import (
    InMemoryExecutionOrderRecordStore,
    InMemoryExecutionReconciliationStore,
    InMemoryOrderIntentJournal,
    InMemoryOrderLifecycleEventStore,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _dead_man() -> DeadManSwitchCapability:
    return DeadManSwitchCapability(
        capability_id=DeadManSwitchCapabilityId(value="dead-man-1"),
        supported=False,
        scope_kind=DeadManSwitchScopeKind.ACCOUNT,
    )


def _venue(**overrides: object) -> VenueCapabilitySnapshot:
    values: dict[str, object] = {
        "snapshot_id": VenueCapabilitySnapshotId(value="venue-cap-1"),
        "venue_id": "venue-1",
        "trading_status": VenueTradingStatus.ENABLED,
        "api_trading_enabled": True,
        "captured_at": NOW,
        "supported_margin_assets": ("USDT",),
        "supported_settlement_assets": ("USDT",),
        "supported_position_modes": (VenuePositionMode.ONE_WAY,),
        "supports_reduce_only": True,
        "supports_post_only": True,
        "supports_close_position": True,
        "supports_gtd": False,
        "supports_price_protection": False,
        "supported_self_trade_prevention_modes": (VenueSelfTradePreventionMode.NONE,),
        "dead_man_switch": _dead_man(),
    }
    values.update(overrides)
    return VenueCapabilitySnapshot(**values)


def _rules(**overrides: object) -> VenueInstrumentRuleSnapshot:
    values: dict[str, object] = {
        "snapshot_id": VenueInstrumentRuleSnapshotId(value="rules-1"),
        "venue_id": "venue-1",
        "instrument_id": "BTC-PERP",
        "symbol": "BTCUSDT",
        "trading_status": InstrumentTradingStatus.TRADING,
        "contract_kind": FuturesContractKind.LINEAR_PERPETUAL,
        "margin_asset": "USDT",
        "settlement_asset": "USDT",
        "captured_at": NOW,
        "price_filter": PriceFilter(tick_size=Decimal("0.1")),
        "quantity_filter": QuantityFilter(
            step_size=Decimal("0.001"),
            min_quantity=Decimal("0.001"),
        ),
        "notional_filter": NotionalFilter(requires_reference_price_for_market_orders=False),
        "supported_order_types": ("MARKET", "LIMIT"),
        "supported_time_in_force": ("GTC",),
        "supports_reduce_only": True,
        "supports_post_only": True,
        "supports_close_position": True,
        "supports_gtd": False,
        "supports_price_protection": False,
        "supported_self_trade_prevention_modes": (VenueSelfTradePreventionMode.NONE,),
    }
    values.update(overrides)
    return VenueInstrumentRuleSnapshot(**values)


def _order(**overrides: object) -> OrderIntent:
    values: dict[str, object] = {
        "intent_kind": OrderIntentKind.ENTRY,
        "venue_id": "venue-1",
        "instrument_id": "BTC-PERP",
        "account_id": "acct-1",
        "side": OrderSide.BUY,
        "position_side": PositionSide.LONG,
        "order_type": OrderType.MARKET,
        "quantity": "1",
        "reduce_only": False,
        "post_only": False,
        "close_position": False,
        "permission_reason": OrderFlowPermissionReason.OK,
        "created_at": NOW,
    }
    values.update(overrides)
    return OrderIntent(**values)


def _context(
    order: OrderIntent,
    venue: VenueCapabilitySnapshot | None = None,
    rules: VenueInstrumentRuleSnapshot | None = None,
) -> VenueOrderValidationContext:
    return VenueOrderValidationContext(
        order_intent=order,
        venue_snapshot=venue or _venue(),
        instrument_rules=rules or _rules(),
        requested_at=NOW,
    )


def _permission(
    *,
    allow_new_entries: bool = True,
    allow_exit_orders: bool = True,
) -> OrderFlowPermission:
    return OrderFlowPermission(
        allow_new_entries=allow_new_entries,
        allow_entry_order_cancel=True,
        allow_exit_orders=allow_exit_orders,
        allow_reduce_only_orders=True,
        allow_exit_order_cancel=True,
        allow_emergency_close=True,
        allow_reconciliation=False,
        guardian_required=False,
        manual_intervention_required=False,
        reason=OrderFlowPermissionReason.OK,
    )


def _coordinator() -> tuple[
    DeterministicExecutionManagerCoordinator,
    InMemoryExecutionOrderRecordStore,
    InMemoryOrderLifecycleEventStore,
    InMemoryOrderIntentJournal,
]:
    records = InMemoryExecutionOrderRecordStore()
    lifecycle = InMemoryOrderLifecycleEventStore()
    journal = InMemoryOrderIntentJournal()
    coordinator = DeterministicExecutionManagerCoordinator(
        intent_journal=journal,
        lifecycle_event_store=lifecycle,
        order_record_store=records,
        reconciliation_store=InMemoryExecutionReconciliationStore(),
    )
    return coordinator, records, lifecycle, journal


def _admit_order(
    coordinator: DeterministicExecutionManagerCoordinator,
    order: OrderIntent,
    permission: OrderFlowPermission,
) -> None:
    coordinator.admit(
        ExecutionAdmissionRequest(
            request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
            order_intent=order,
            order_flow_permission=permission,
            requested_at=NOW,
            requested_by="setup",
        )
    )


def _replace_request(
    original: OrderIntent,
    replacement: OrderIntent,
    permission: OrderFlowPermission,
    *,
    ctx: VenueOrderValidationContext | None = None,
    require_validation: bool = False,
) -> ExecutionAdmissionRequest:
    assert original.client_order_id is not None
    replace_intent = ReplaceOrderIntent(
        target_client_order_id=original.client_order_id,
        target_intent_kind=original.intent_kind,
        replacement_order=replacement,
        replace_reason="replace-for-test",
        created_at=NOW,
    )
    return ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.REPLACE_INTENT,
        replace_intent=replace_intent,
        order_flow_permission=permission,
        venue_validation_context=ctx,
        require_venue_capability_validation=require_validation,
        requested_at=NOW,
        requested_by="replace-tester",
    )


# ---------- Replace: runtime blocked does not run capability gate ----------

def test_replace_runtime_blocked_does_not_run_capability_gate() -> None:
    coordinator, records, _, _ = _coordinator()
    original = _order(intent_kind=OrderIntentKind.ENTRY)
    _admit_order(coordinator, original, _permission())
    replacement = _order(quantity="2")
    ctx = _context(replacement)
    # guardian_required blocks ENTRY-class replace
    permission = OrderFlowPermission(
        allow_new_entries=True,
        allow_entry_order_cancel=True,
        allow_exit_orders=True,
        allow_reduce_only_orders=True,
        allow_exit_order_cancel=True,
        allow_emergency_close=True,
        allow_reconciliation=False,
        guardian_required=True,
        manual_intervention_required=False,
        reason=OrderFlowPermissionReason.OK,
    )
    decision = coordinator.admit(
        _replace_request(original, replacement, permission, ctx=ctx, require_validation=True)
    )
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_PERMISSION
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


def test_replace_scope_mismatch_does_not_run_capability_gate() -> None:
    coordinator, records, _, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    # Replacement with different instrument (scope mismatch)
    replacement = _order(instrument_id="ETH-PERP")
    decision = coordinator.admit(
        _replace_request(original, replacement, _permission(), require_validation=False)
    )
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VALIDATION
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


# ---------- Replace: invalid replacement venue capability rejects without mutating target ----------  # noqa: E501

def test_replace_invalid_replacement_venue_capability_rejects() -> None:
    coordinator, _records, _, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    replacement = _order(quantity="2")
    disabled_venue = _venue(trading_status=VenueTradingStatus.DISABLED)
    ctx = _context(replacement, venue=disabled_venue)
    decision = coordinator.admit(
        _replace_request(original, replacement, _permission(), ctx=ctx, require_validation=True)
    )
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY


def test_replace_invalid_replacement_venue_capability_does_not_update_target() -> None:
    coordinator, records, _, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    replacement = _order(quantity="2")
    disabled_venue = _venue(trading_status=VenueTradingStatus.DISABLED)
    ctx = _context(replacement, venue=disabled_venue)
    coordinator.admit(
        _replace_request(original, replacement, _permission(), ctx=ctx, require_validation=True)
    )
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


def test_replace_invalid_replacement_venue_capability_does_not_create_replacement_record() -> None:
    coordinator, records, _, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    replacement = _order(quantity="2")
    disabled_venue = _venue(trading_status=VenueTradingStatus.DISABLED)
    ctx = _context(replacement, venue=disabled_venue)
    coordinator.admit(
        _replace_request(original, replacement, _permission(), ctx=ctx, require_validation=True)
    )
    assert records.get_by_client_order_id(replacement.client_order_id) is None


def test_replace_invalid_venue_capability_appends_auditable_event() -> None:
    coordinator, _, lifecycle, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    replacement = _order(quantity="2")
    disabled_venue = _venue(trading_status=VenueTradingStatus.DISABLED)
    ctx = _context(replacement, venue=disabled_venue)
    coordinator.admit(
        _replace_request(original, replacement, _permission(), ctx=ctx, require_validation=True)
    )
    events = lifecycle.list_events()
    rejection_events = [
        e for e in events
        if isinstance(e.payload, dict) and e.payload.get("stage") == "rejected_by_venue_capability"
    ]
    assert len(rejection_events) >= 1
    payload = rejection_events[0].payload
    assert isinstance(payload, dict)
    assert payload.get("venue_validation_reason") == VenueOrderValidationReason.VENUE_TRADING_DISABLED.value  # noqa: E501


# ---------- Replace: valid target + valid replacement venue capability updates target ----------

def test_replace_valid_target_and_valid_capability_updates_target_to_replace_requested() -> None:
    coordinator, records, _, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    replacement = _order(quantity="2")
    ctx = _context(replacement)
    decision = coordinator.admit(
        _replace_request(original, replacement, _permission(), ctx=ctx, require_validation=True)
    )
    assert decision.accepted
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.REPLACE_REQUESTED


def test_replace_valid_target_and_valid_capability_creates_replacement_record() -> None:
    coordinator, records, _, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    replacement = _order(quantity="2")
    ctx = _context(replacement)
    coordinator.admit(
        _replace_request(original, replacement, _permission(), ctx=ctx, require_validation=True)
    )
    replacement_record = records.get_by_client_order_id(replacement.client_order_id)
    assert replacement_record is not None
    assert replacement_record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


# ---------- Replace: off-tick price rejects ----------

def test_replace_off_tick_price_rejects_by_venue_capability() -> None:
    coordinator, records, _, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    replacement = _order(order_type=OrderType.LIMIT, limit_price="100.05")
    ctx = _context(replacement)
    decision = coordinator.admit(
        _replace_request(original, replacement, _permission(), ctx=ctx, require_validation=True)
    )
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


# ---------- Regression: existing replace behavior preserved without capability gate ----------

def test_replace_without_capability_validation_still_works() -> None:
    coordinator, records, _, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    replacement = _order(quantity="2")
    decision = coordinator.admit(
        _replace_request(original, replacement, _permission(), require_validation=False)
    )
    assert decision.accepted
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.REPLACE_REQUESTED


# ---------- Regression Review tests (107-113) ----------

def test_review_107_entry_replace_uses_entry_permission_class() -> None:
    """ENTRY target requires entry-class replace permission."""
    coordinator, _, _, _ = _coordinator()
    original = _order(intent_kind=OrderIntentKind.ENTRY)
    _admit_order(coordinator, original, _permission())
    replacement = _order(quantity="2")
    # allow_exit_orders=False should not block ENTRY replacement
    permission = _permission(allow_exit_orders=False)
    decision = coordinator.admit(
        _replace_request(original, replacement, permission, require_validation=False)
    )
    assert decision.accepted


def test_review_108_replace_permission_class_safety() -> None:
    """Runtime permission is checked before capability gate for replace."""
    coordinator, records, _, _ = _coordinator()
    original = _order(intent_kind=OrderIntentKind.ENTRY)
    _admit_order(coordinator, original, _permission())
    replacement = _order(quantity="2")
    ctx = _context(replacement)
    # Block new entries - this blocks ENTRY replacement
    permission = _permission(allow_new_entries=False)
    decision = coordinator.admit(
        _replace_request(original, replacement, permission, ctx=ctx, require_validation=True)
    )
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_PERMISSION
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


def test_review_109_record_store_identity_safety() -> None:
    """Two distinct orders produce distinct record IDs."""
    coordinator, records, _, _ = _coordinator()
    order_a = _order()
    order_b = _order(account_id="acct-2")
    _admit_order(coordinator, order_a, _permission())
    _admit_order(coordinator, order_b, _permission())
    rec_a = records.get_by_client_order_id(order_a.client_order_id)
    rec_b = records.get_by_client_order_id(order_b.client_order_id)
    assert rec_a is not None
    assert rec_b is not None
    assert rec_a.record_id != rec_b.record_id


def test_review_111_replace_scope_safety_preserved() -> None:
    """Scope mismatch (different instrument) rejects replace before capability gate."""
    coordinator, records, _, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    # ETH-PERP as replacement — scope mismatch, no need for context (gate is never reached)
    mismatched = _order(instrument_id="ETH-PERP")
    decision = coordinator.admit(
        _replace_request(original, mismatched, _permission(), require_validation=False)
    )
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VALIDATION
    target = records.get_by_client_order_id(original.client_order_id)
    assert target is not None
    assert target.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


def test_review_113_price_validation_preserved() -> None:
    """Off-tick limit price on replacement rejects by venue capability."""
    coordinator, _records, _, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    bad_price_replacement = _order(order_type=OrderType.LIMIT, limit_price="100.05")
    ctx = _context(bad_price_replacement)
    decision = coordinator.admit(
        _replace_request(original, bad_price_replacement, _permission(), ctx=ctx, require_validation=True)  # noqa: E501
    )
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY


# ---------- Replace admission decision venue reason propagation ----------

def test_replace_capability_rejection_decision_includes_venue_reason() -> None:
    coordinator, _, _, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    replacement = _order(quantity="2")
    disabled_venue = _venue(trading_status=VenueTradingStatus.DISABLED)
    ctx = _context(replacement, venue=disabled_venue)
    decision = coordinator.admit(
        _replace_request(original, replacement, _permission(), ctx=ctx, require_validation=True)
    )
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY
    assert decision.venue_validation_reason == VenueOrderValidationReason.VENUE_TRADING_DISABLED.value  # noqa: E501


def test_replace_capability_rejection_decision_includes_venue_details() -> None:
    coordinator, _, _, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    replacement = _order(quantity="2")
    disabled_venue = _venue(trading_status=VenueTradingStatus.DISABLED)
    ctx = _context(replacement, venue=disabled_venue)
    decision = coordinator.admit(
        _replace_request(original, replacement, _permission(), ctx=ctx, require_validation=True)
    )
    assert decision.venue_validation_details is not None


def test_replace_capability_acceptance_decision_includes_ok_venue_reason() -> None:
    coordinator, _, _, _ = _coordinator()
    original = _order()
    _admit_order(coordinator, original, _permission())
    replacement = _order(quantity="2")
    ctx = _context(replacement)
    decision = coordinator.admit(
        _replace_request(original, replacement, _permission(), ctx=ctx, require_validation=True)
    )
    assert decision.accepted
    assert decision.venue_validation_reason == VenueOrderValidationReason.OK.value
