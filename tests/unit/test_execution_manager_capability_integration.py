from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from futures_bot.domain.execution_manager import (
    ExecutionAdmissionDecisionReason,
    ExecutionAdmissionRequest,
    ExecutionAdmissionRequestKind,
    deterministic_execution_admission_request_id,
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
    allow_reduce_only_orders: bool = True,
) -> OrderFlowPermission:
    return OrderFlowPermission(
        allow_new_entries=allow_new_entries,
        allow_entry_order_cancel=True,
        allow_exit_orders=True,
        allow_reduce_only_orders=allow_reduce_only_orders,
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
]:
    records = InMemoryExecutionOrderRecordStore()
    lifecycle = InMemoryOrderLifecycleEventStore()
    coordinator = DeterministicExecutionManagerCoordinator(
        intent_journal=InMemoryOrderIntentJournal(),
        lifecycle_event_store=lifecycle,
        order_record_store=records,
        reconciliation_store=InMemoryExecutionReconciliationStore(),
    )
    return coordinator, records, lifecycle


def _request(
    order: OrderIntent,
    permission: OrderFlowPermission,
    *,
    ctx: VenueOrderValidationContext | None = None,
    require_validation: bool = False,
) -> ExecutionAdmissionRequest:
    return ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order,
        order_flow_permission=permission,
        venue_validation_context=ctx,
        require_venue_capability_validation=require_validation,
        requested_at=NOW,
        requested_by="integration-test",
    )


# ---------- Existing behavior preserved ----------

def test_runtime_blocked_entry_creates_no_active_record_and_no_gate_run() -> None:
    coordinator, records, _ = _coordinator()
    order = _order()
    decision = coordinator.admit(
        _request(order, _permission(allow_new_entries=False))
    )
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_PERMISSION
    assert records.get_by_client_order_id(order.client_order_id) is None


def test_no_capability_validation_accepts_without_context() -> None:
    coordinator, records, _ = _coordinator()
    order = _order()
    decision = coordinator.admit(
        _request(order, _permission(), ctx=None, require_validation=False)
    )
    assert decision.accepted
    record = records.get_by_client_order_id(order.client_order_id)
    assert record is not None
    assert record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


# ---------- Runtime allowed + venue valid → ACCEPTED_BY_EXECUTION ----------

def test_runtime_allowed_venue_valid_creates_accepted_record() -> None:
    coordinator, records, _ = _coordinator()
    order = _order()
    ctx = _context(order)
    decision = coordinator.admit(
        _request(order, _permission(), ctx=ctx, require_validation=True)
    )
    assert decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.ACCEPTED
    record = records.get_by_client_order_id(order.client_order_id)
    assert record is not None
    assert record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION


def test_accepted_order_is_never_submitted_to_venue() -> None:
    coordinator, records, _ = _coordinator()
    order = _order()
    ctx = _context(order)
    coordinator.admit(_request(order, _permission(), ctx=ctx, require_validation=True))
    record = records.get_by_client_order_id(order.client_order_id)
    assert record is not None
    assert record.lifecycle_state is not OrderLifecycleState.SUBMITTED_TO_VENUE


# ---------- Runtime allowed + venue invalid → REJECTED_BY_VENUE_CAPABILITY ----------

def test_runtime_allowed_venue_invalid_rejects_by_venue_capability() -> None:
    coordinator, _records, _ = _coordinator()
    order = _order()
    disabled_venue = _venue(trading_status=VenueTradingStatus.DISABLED)
    ctx = _context(order, venue=disabled_venue)
    decision = coordinator.admit(
        _request(order, _permission(), ctx=ctx, require_validation=True)
    )
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY


def test_venue_invalid_rejection_creates_no_active_record() -> None:
    coordinator, records, _ = _coordinator()
    order = _order()
    disabled_venue = _venue(trading_status=VenueTradingStatus.DISABLED)
    ctx = _context(order, venue=disabled_venue)
    coordinator.admit(_request(order, _permission(), ctx=ctx, require_validation=True))
    assert records.get_by_client_order_id(order.client_order_id) is None


def test_venue_invalid_rejection_appends_auditable_lifecycle_event() -> None:
    coordinator, _, lifecycle = _coordinator()
    order = _order()
    disabled_venue = _venue(trading_status=VenueTradingStatus.DISABLED)
    ctx = _context(order, venue=disabled_venue)
    coordinator.admit(_request(order, _permission(), ctx=ctx, require_validation=True))
    events = lifecycle.list_events()
    rejection_events = [
        e for e in events
        if isinstance(e.payload, dict) and (
            e.payload.get("stage") == "rejected_by_venue_capability"
            or "venue_validation_reason" in e.payload
        )
    ]
    assert len(rejection_events) >= 1


def test_venue_invalid_rejection_event_contains_venue_reason() -> None:
    coordinator, _, lifecycle = _coordinator()
    order = _order()
    disabled_venue = _venue(trading_status=VenueTradingStatus.DISABLED)
    ctx = _context(order, venue=disabled_venue)
    coordinator.admit(_request(order, _permission(), ctx=ctx, require_validation=True))
    events = lifecycle.list_events()
    payloads = [e.payload for e in events if isinstance(e.payload, dict)]
    venue_reasons = [p.get("venue_validation_reason") for p in payloads if "venue_validation_reason" in p]  # noqa: E501
    assert VenueOrderValidationReason.VENUE_TRADING_DISABLED.value in venue_reasons


# ---------- Runtime blocked → capability gate not invoked ----------

def test_runtime_blocked_does_not_run_capability_gate() -> None:
    coordinator, _records, _lifecycle = _coordinator()
    order = _order()
    ctx = _context(order)
    decision = coordinator.admit(
        _request(order, _permission(allow_new_entries=False), ctx=ctx, require_validation=True)
    )
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_PERMISSION
    assert _records.get_by_client_order_id(order.client_order_id) is None


# ---------- Missing required venue context ----------

def test_missing_required_venue_context_rejects_with_context_required() -> None:
    coordinator, records, _ = _coordinator()
    order = _order()
    # Use model_construct to bypass domain validation and simulate defensive path in coordinator
    request = ExecutionAdmissionRequest.model_construct(
        request_id=None,
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order,
        cancel_intent=None,
        replace_intent=None,
        order_flow_permission=_permission(),
        venue_validation_context=None,
        require_venue_capability_validation=True,
        requested_at=NOW,
        requested_by="integration-test",
        correlation_id=None,
    )
    # Patch request_id via deterministic function
    computed_id = deterministic_execution_admission_request_id(request)
    object.__setattr__(request, "request_id", computed_id)
    decision = coordinator.admit(request)
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.VENUE_CAPABILITY_CONTEXT_REQUIRED
    assert records.get_by_client_order_id(order.client_order_id) is None


# ---------- Venue context mismatch ----------

def test_venue_context_order_mismatch_rejects_with_mismatch_reason() -> None:
    coordinator, records, _ = _coordinator()
    order_a = _order()
    order_b = _order(account_id="acct-2")
    # Build a context that holds order_b but submit request with order_a
    # The domain model for ExecutionAdmissionRequest doesn't validate this, so it can be constructed
    ctx_for_b = _context(order_b)
    # Directly construct request with mismatched context (domain doesn't validate order mismatch)
    request = ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order_a,
        order_flow_permission=_permission(),
        venue_validation_context=ctx_for_b,
        require_venue_capability_validation=True,
        requested_at=NOW,
        requested_by="integration-test",
    )
    decision = coordinator.admit(request)
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.VENUE_CAPABILITY_CONTEXT_MISMATCH
    assert records.get_by_client_order_id(order_a.client_order_id) is None


# ---------- Regression: accepted record state is ACCEPTED_BY_EXECUTION only ----------

def test_accepted_record_state_is_accepted_by_execution_not_submitted() -> None:
    coordinator, records, _ = _coordinator()
    order = _order()
    ctx = _context(order)
    coordinator.admit(_request(order, _permission(), ctx=ctx, require_validation=True))
    record = records.get_by_client_order_id(order.client_order_id)
    assert record is not None
    assert record.lifecycle_state is OrderLifecycleState.ACCEPTED_BY_EXECUTION
    assert record.lifecycle_state is not OrderLifecycleState.SUBMITTED_TO_VENUE


def test_off_tick_price_rejects_by_venue_capability() -> None:
    coordinator, records, _ = _coordinator()
    order = _order(order_type=OrderType.LIMIT, limit_price="100.05")
    ctx = _context(order)
    decision = coordinator.admit(
        _request(order, _permission(), ctx=ctx, require_validation=True)
    )
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY
    assert records.get_by_client_order_id(order.client_order_id) is None


# ---------- Admission decision venue reason propagation ----------

def test_order_capability_rejection_decision_includes_venue_reason() -> None:
    coordinator, _, _ = _coordinator()
    order = _order(order_type=OrderType.LIMIT, limit_price="100.05")
    ctx = _context(order)
    decision = coordinator.admit(
        _request(order, _permission(), ctx=ctx, require_validation=True)
    )
    assert decision.venue_validation_reason == VenueOrderValidationReason.PRICE_NOT_ON_TICK.value


def test_order_capability_rejection_decision_includes_venue_details() -> None:
    coordinator, _, _ = _coordinator()
    order = _order(order_type=OrderType.LIMIT, limit_price="100.05")
    ctx = _context(order)
    decision = coordinator.admit(
        _request(order, _permission(), ctx=ctx, require_validation=True)
    )
    assert decision.venue_validation_details is not None


def test_order_capability_acceptance_decision_includes_ok_venue_reason() -> None:
    coordinator, _, _ = _coordinator()
    order = _order()
    ctx = _context(order)
    decision = coordinator.admit(
        _request(order, _permission(), ctx=ctx, require_validation=True)
    )
    assert decision.accepted
    assert decision.venue_validation_reason == VenueOrderValidationReason.OK.value


def test_runtime_permission_rejection_decision_has_no_venue_reason() -> None:
    coordinator, _, _ = _coordinator()
    order = _order()
    ctx = _context(order)
    decision = coordinator.admit(
        _request(order, _permission(allow_new_entries=False), ctx=ctx, require_validation=True)
    )
    assert not decision.accepted
    assert decision.reason is ExecutionAdmissionDecisionReason.REJECTED_BY_PERMISSION
    assert decision.venue_validation_reason is None


def test_order_capability_context_mismatch_decision_includes_mismatch_venue_reason() -> None:
    coordinator, _, _ = _coordinator()
    order_a = _order()
    order_b = _order(account_id="acct-2")
    ctx_for_b = _context(order_b)
    request = ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order_a,
        order_flow_permission=_permission(),
        venue_validation_context=ctx_for_b,
        require_venue_capability_validation=True,
        requested_at=NOW,
        requested_by="integration-test",
    )
    decision = coordinator.admit(request)
    assert decision.reason is ExecutionAdmissionDecisionReason.VENUE_CAPABILITY_CONTEXT_MISMATCH
    assert decision.venue_validation_reason == "VALIDATION_CONTEXT_MISMATCH"
