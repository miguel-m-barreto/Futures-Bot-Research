from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.execution_capability_gate import (
    ExecutionCapabilityCheck,
    ExecutionCapabilityDecision,
    ExecutionCapabilityDecisionReason,
    deterministic_execution_capability_check_id,
    deterministic_execution_capability_decision_id,
)
from futures_bot.domain.execution_manager import (
    ExecutionAdmissionDecision,
    ExecutionAdmissionDecisionReason,
    ExecutionAdmissionRequest,
    ExecutionAdmissionRequestKind,
)
from futures_bot.domain.ids import (
    ClientOrderId,
    DeadManSwitchCapabilityId,
    ExecutionAdmissionRequestId,
    ExecutionCapabilityCheckId,
    VenueCapabilitySnapshotId,
    VenueInstrumentRuleSnapshotId,
)
from futures_bot.domain.order_lifecycle import (
    CancelOrderIntent,
    CancelScope,
    OrderIntent,
    OrderIntentKind,
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
    VenuePositionMode,
    VenueSelfTradePreventionMode,
    VenueTradingStatus,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _dead_man() -> DeadManSwitchCapability:
    return DeadManSwitchCapability(
        capability_id=DeadManSwitchCapabilityId(value="dead-man-1"),
        supported=False,
        scope_kind=DeadManSwitchScopeKind.ACCOUNT,
    )


def _venue() -> VenueCapabilitySnapshot:
    return VenueCapabilitySnapshot(
        snapshot_id=VenueCapabilitySnapshotId(value="venue-cap-1"),
        venue_id="venue-1",
        trading_status=VenueTradingStatus.ENABLED,
        api_trading_enabled=True,
        captured_at=NOW,
        supported_margin_assets=("USDT",),
        supported_settlement_assets=("USDT",),
        supported_position_modes=(VenuePositionMode.ONE_WAY,),
        supports_reduce_only=True,
        supports_post_only=True,
        supports_close_position=True,
        supports_gtd=False,
        supports_price_protection=False,
        supported_self_trade_prevention_modes=(VenueSelfTradePreventionMode.NONE,),
        dead_man_switch=_dead_man(),
    )


def _rules() -> VenueInstrumentRuleSnapshot:
    return VenueInstrumentRuleSnapshot(
        snapshot_id=VenueInstrumentRuleSnapshotId(value="rules-1"),
        venue_id="venue-1",
        instrument_id="BTC-PERP",
        symbol="BTCUSDT",
        trading_status=InstrumentTradingStatus.TRADING,
        contract_kind=FuturesContractKind.LINEAR_PERPETUAL,
        margin_asset="USDT",
        settlement_asset="USDT",
        captured_at=NOW,
        price_filter=PriceFilter(tick_size=Decimal("0.1")),
        quantity_filter=QuantityFilter(
            step_size=Decimal("0.001"),
            min_quantity=Decimal("0.001"),
        ),
        notional_filter=NotionalFilter(requires_reference_price_for_market_orders=False),
        supported_order_types=("MARKET", "LIMIT"),
        supported_time_in_force=("GTC",),
        supports_reduce_only=True,
        supports_post_only=True,
        supports_close_position=True,
        supports_gtd=False,
        supports_price_protection=False,
        supported_self_trade_prevention_modes=(VenueSelfTradePreventionMode.NONE,),
    )


def _order(instrument_id: str = "BTC-PERP") -> OrderIntent:
    return OrderIntent(
        intent_kind=OrderIntentKind.ENTRY,
        venue_id="venue-1",
        instrument_id=instrument_id,
        account_id="acct-1",
        side=OrderSide.BUY,
        position_side=PositionSide.LONG,
        order_type=OrderType.MARKET,
        quantity="1",
        reduce_only=False,
        post_only=False,
        close_position=False,
        permission_reason=OrderFlowPermissionReason.OK,
        created_at=NOW,
    )


def _context(order: OrderIntent | None = None) -> VenueOrderValidationContext:
    intent = order or _order()
    return VenueOrderValidationContext(
        order_intent=intent,
        venue_snapshot=_venue(),
        instrument_rules=_rules(),
        requested_at=NOW,
    )


def _permission() -> OrderFlowPermission:
    return OrderFlowPermission(
        allow_new_entries=True,
        allow_entry_order_cancel=True,
        allow_exit_orders=True,
        allow_reduce_only_orders=True,
        allow_exit_order_cancel=True,
        allow_emergency_close=True,
        allow_reconciliation=False,
        guardian_required=False,
        manual_intervention_required=False,
        reason=OrderFlowPermissionReason.OK,
    )


# ---------- ExecutionCapabilityCheck ----------

def test_check_id_is_deterministic() -> None:
    order = _order()
    ctx = _context(order)
    check1 = ExecutionCapabilityCheck(
        order_intent=order,
        venue_validation_context=ctx,
        requested_at=NOW,
        requested_by="tester",
    )
    check2 = ExecutionCapabilityCheck(
        order_intent=order,
        venue_validation_context=ctx,
        requested_at=NOW,
        requested_by="tester",
    )
    assert check1.check_id == check2.check_id


def test_check_id_differs_for_different_inputs() -> None:
    order1 = _order("BTC-PERP")
    check1 = ExecutionCapabilityCheck(
        order_intent=order1,
        venue_validation_context=_context(order1),
        requested_at=NOW,
        requested_by="tester",
    )
    # can't create valid check for ETH-PERP with BTC-PERP rules, so just differ by requested_by
    check3 = ExecutionCapabilityCheck(
        order_intent=order1,
        venue_validation_context=_context(order1),
        requested_at=NOW,
        requested_by="other-tester",
    )
    assert check1.check_id != check3.check_id


def test_check_id_matches_deterministic_function() -> None:
    order = _order()
    ctx = _context(order)
    check = ExecutionCapabilityCheck(
        order_intent=order,
        venue_validation_context=ctx,
        requested_at=NOW,
        requested_by="tester",
    )
    expected = deterministic_execution_capability_check_id(check)
    assert check.check_id == expected


def test_check_rejects_explicit_wrong_check_id() -> None:
    order = _order()
    ctx = _context(order)
    with pytest.raises(ValidationError, match="check_id is not deterministic"):
        ExecutionCapabilityCheck(
            check_id=ExecutionCapabilityCheckId(value="exec-capability-check:wrongid"),
            order_intent=order,
            venue_validation_context=ctx,
            requested_at=NOW,
            requested_by="tester",
        )


def test_check_rejects_context_order_mismatch() -> None:
    order_a = _order("BTC-PERP")
    order_b = _order("ETH-PERP")
    # Build a context for order_a, but supply order_b as the order_intent to the check
    # We must construct the context manually to avoid the venue_id mismatch
    # Actually: ETH-PERP is a different instrument_id from the rules fixture (BTC-PERP).
    # So we need a different rules snapshot for ETH-PERP.
    rules_eth = VenueInstrumentRuleSnapshot(
        snapshot_id=VenueInstrumentRuleSnapshotId(value="rules-eth"),
        venue_id="venue-1",
        instrument_id="ETH-PERP",
        symbol="ETHUSDT",
        trading_status=InstrumentTradingStatus.TRADING,
        contract_kind=FuturesContractKind.LINEAR_PERPETUAL,
        margin_asset="USDT",
        settlement_asset="USDT",
        captured_at=NOW,
        price_filter=PriceFilter(tick_size=Decimal("0.01")),
        quantity_filter=QuantityFilter(
            step_size=Decimal("0.01"),
            min_quantity=Decimal("0.01"),
        ),
        notional_filter=NotionalFilter(requires_reference_price_for_market_orders=False),
        supported_order_types=("MARKET",),
        supported_time_in_force=("GTC",),
        supports_reduce_only=True,
        supports_post_only=True,
        supports_close_position=True,
        supports_gtd=False,
        supports_price_protection=False,
        supported_self_trade_prevention_modes=(VenueSelfTradePreventionMode.NONE,),
    )
    ctx_b = VenueOrderValidationContext(
        order_intent=order_b,
        venue_snapshot=_venue(),
        instrument_rules=rules_eth,
        requested_at=NOW,
    )
    # Construct check with order_a but ctx_b (which has order_b inside)
    with pytest.raises(ValidationError, match="order_intent must match"):
        ExecutionCapabilityCheck(
            order_intent=order_a,
            venue_validation_context=ctx_b,
            requested_at=NOW,
            requested_by="tester",
        )


# ---------- ExecutionCapabilityDecision ----------

def test_decision_id_is_deterministic() -> None:
    check_id = ExecutionCapabilityCheckId(value="exec-capability-check:aabbcc")
    d1 = ExecutionCapabilityDecision(
        check_id=check_id,
        executable=True,
        reason=ExecutionCapabilityDecisionReason.EXECUTABLE,
        venue_validation_reason="OK",
        venue_validation_details={"message": "ok"},
        decided_at=NOW,
    )
    d2 = ExecutionCapabilityDecision(
        check_id=check_id,
        executable=True,
        reason=ExecutionCapabilityDecisionReason.EXECUTABLE,
        venue_validation_reason="OK",
        venue_validation_details={"message": "ok"},
        decided_at=NOW,
    )
    assert d1.decision_id == d2.decision_id


def test_decision_id_matches_deterministic_function() -> None:
    check_id = ExecutionCapabilityCheckId(value="exec-capability-check:aabbcc")
    decision = ExecutionCapabilityDecision(
        check_id=check_id,
        executable=True,
        reason=ExecutionCapabilityDecisionReason.EXECUTABLE,
        venue_validation_reason="OK",
        venue_validation_details={"message": "ok"},
        decided_at=NOW,
    )
    expected = deterministic_execution_capability_decision_id(decision)
    assert decision.decision_id == expected


def test_decision_executable_requires_executable_reason() -> None:
    check_id = ExecutionCapabilityCheckId(value="exec-capability-check:aabbcc")
    with pytest.raises(ValidationError, match="executable=True requires reason EXECUTABLE"):
        ExecutionCapabilityDecision(
            check_id=check_id,
            executable=True,
            reason=ExecutionCapabilityDecisionReason.REJECTED_BY_VENUE_CAPABILITY,
            decided_at=NOW,
        )


def test_decision_not_executable_requires_non_executable_reason() -> None:
    check_id = ExecutionCapabilityCheckId(value="exec-capability-check:aabbcc")
    with pytest.raises(ValidationError, match="executable=False requires reason"):
        ExecutionCapabilityDecision(
            check_id=check_id,
            executable=False,
            reason=ExecutionCapabilityDecisionReason.EXECUTABLE,
            decided_at=NOW,
        )


def test_decision_rejected_by_venue_capability_is_valid() -> None:
    check_id = ExecutionCapabilityCheckId(value="exec-capability-check:aabbcc")
    decision = ExecutionCapabilityDecision(
        check_id=check_id,
        executable=False,
        reason=ExecutionCapabilityDecisionReason.REJECTED_BY_VENUE_CAPABILITY,
        venue_validation_reason="VENUE_TRADING_DISABLED",
        venue_validation_details={"reason": "VENUE_TRADING_DISABLED"},
        decided_at=NOW,
    )
    assert not decision.executable
    assert decision.reason is ExecutionCapabilityDecisionReason.REJECTED_BY_VENUE_CAPABILITY


def test_decision_validation_context_mismatch_is_valid() -> None:
    check_id = ExecutionCapabilityCheckId(value="exec-capability-check:aabbcc")
    decision = ExecutionCapabilityDecision(
        check_id=check_id,
        executable=False,
        reason=ExecutionCapabilityDecisionReason.VALIDATION_CONTEXT_MISMATCH,
        venue_validation_reason="VALIDATION_CONTEXT_MISMATCH",
        venue_validation_details={"message": "mismatch"},
        decided_at=NOW,
    )
    assert not decision.executable
    assert decision.reason is ExecutionCapabilityDecisionReason.VALIDATION_CONTEXT_MISMATCH


# ---------- ExecutionAdmissionRequest capability validation fields ----------

def test_admission_request_accepts_venue_context_for_order_intent() -> None:
    order = _order()
    ctx = _context(order)
    req = ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order,
        order_flow_permission=_permission(),
        venue_validation_context=ctx,
        require_venue_capability_validation=True,
        requested_at=NOW,
        requested_by="tester",
    )
    assert req.require_venue_capability_validation is True
    assert req.venue_validation_context is not None


def test_admission_request_requires_venue_context_when_validation_required_for_order_intent() -> None:  # noqa: E501
    order = _order()
    with pytest.raises(ValidationError, match="require_venue_capability_validation"):
        ExecutionAdmissionRequest(
            request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
            order_intent=order,
            order_flow_permission=_permission(),
            venue_validation_context=None,
            require_venue_capability_validation=True,
            requested_at=NOW,
            requested_by="tester",
        )


def test_admission_request_does_not_require_venue_context_when_validation_not_required() -> None:
    order = _order()
    req = ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        order_intent=order,
        order_flow_permission=_permission(),
        venue_validation_context=None,
        require_venue_capability_validation=False,
        requested_at=NOW,
        requested_by="tester",
    )
    assert req.venue_validation_context is None


def test_admission_request_requires_venue_context_when_validation_required_for_replace_intent() -> None:  # noqa: E501
    original = _order()
    replacement = _order()
    replace_intent = ReplaceOrderIntent(
        target_client_order_id=original.client_order_id,
        target_intent_kind=OrderIntentKind.ENTRY,
        replacement_order=replacement,
        replace_reason="adjust-size",
        created_at=NOW,
    )
    with pytest.raises(ValidationError, match="require_venue_capability_validation"):
        ExecutionAdmissionRequest(
            request_kind=ExecutionAdmissionRequestKind.REPLACE_INTENT,
            replace_intent=replace_intent,
            order_flow_permission=_permission(),
            venue_validation_context=None,
            require_venue_capability_validation=True,
            requested_at=NOW,
            requested_by="tester",
        )


def test_admission_request_does_not_require_venue_context_for_cancel_intent() -> None:
    cancel = CancelOrderIntent(
        target_client_order_id=ClientOrderId(value="clord-abc"),
        instrument_id="BTC-PERP",
        venue_id="venue-1",
        cancel_scope=CancelScope.SINGLE_ORDER,
        cancel_reason="test-cancel",
        created_at=NOW,
    )
    req = ExecutionAdmissionRequest(
        request_kind=ExecutionAdmissionRequestKind.CANCEL_INTENT,
        cancel_intent=cancel,
        order_flow_permission=_permission(),
        venue_validation_context=None,
        require_venue_capability_validation=True,
        requested_at=NOW,
        requested_by="tester",
    )
    assert req.venue_validation_context is None


# ---------- ExecutionAdmissionDecision venue validation invariants ----------

_DUMMY_REQUEST_ID = ExecutionAdmissionRequestId(value="exec-admission-request:aabbcc")


def test_admission_decision_rejected_by_venue_capability_requires_venue_reason() -> None:
    with pytest.raises(ValidationError, match="venue_validation_reason"):
        ExecutionAdmissionDecision(
            request_id=_DUMMY_REQUEST_ID,
            request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
            accepted=False,
            reason=ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY,
            venue_validation_reason=None,
            decided_at=NOW,
        )


def test_admission_decision_venue_validation_details_must_be_json_compatible() -> None:
    with pytest.raises((ValidationError, Exception)):
        ExecutionAdmissionDecision(
            request_id=_DUMMY_REQUEST_ID,
            request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
            accepted=False,
            reason=ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY,
            venue_validation_reason="PRICE_NOT_ON_TICK",
            venue_validation_details=object(),
            decided_at=NOW,
        )


def test_admission_decision_rejected_by_venue_capability_with_valid_fields_passes() -> None:
    decision = ExecutionAdmissionDecision(
        request_id=_DUMMY_REQUEST_ID,
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        accepted=False,
        reason=ExecutionAdmissionDecisionReason.REJECTED_BY_VENUE_CAPABILITY,
        venue_validation_reason="PRICE_NOT_ON_TICK",
        venue_validation_details={"tick_size": "0.1", "price": "100.05"},
        decided_at=NOW,
    )
    assert decision.venue_validation_reason == "PRICE_NOT_ON_TICK"
    assert isinstance(decision.venue_validation_details, dict)


def test_admission_decision_rejected_by_permission_can_omit_venue_reason() -> None:
    decision = ExecutionAdmissionDecision(
        request_id=_DUMMY_REQUEST_ID,
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        accepted=False,
        reason=ExecutionAdmissionDecisionReason.REJECTED_BY_PERMISSION,
        venue_validation_reason=None,
        decided_at=NOW,
    )
    assert decision.venue_validation_reason is None


def test_admission_decision_accepted_can_include_venue_reason() -> None:
    decision = ExecutionAdmissionDecision(
        request_id=_DUMMY_REQUEST_ID,
        request_kind=ExecutionAdmissionRequestKind.ORDER_INTENT,
        accepted=True,
        reason=ExecutionAdmissionDecisionReason.ACCEPTED,
        venue_validation_reason="OK",
        venue_validation_details={"ok": True},
        decided_at=NOW,
    )
    assert decision.venue_validation_reason == "OK"
