from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from futures_bot.domain.execution_capability_gate import (
    ExecutionCapabilityCheck,
    ExecutionCapabilityDecisionReason,
)
from futures_bot.domain.ids import (
    DeadManSwitchCapabilityId,
    VenueCapabilitySnapshotId,
    VenueInstrumentRuleSnapshotId,
)
from futures_bot.domain.order_lifecycle import (
    OrderIntent,
    OrderIntentKind,
    OrderSide,
    OrderType,
    PositionSide,
)
from futures_bot.domain.runtime_control import OrderFlowPermissionReason
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
from futures_bot.execution_manager.capability_gate import DeterministicExecutionCapabilityGate

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


def _check(order: OrderIntent, ctx: VenueOrderValidationContext) -> ExecutionCapabilityCheck:
    return ExecutionCapabilityCheck(
        order_intent=order,
        venue_validation_context=ctx,
        requested_at=NOW,
        requested_by="gate-tester",
    )


def _gate() -> DeterministicExecutionCapabilityGate:
    return DeterministicExecutionCapabilityGate()


# ---------- Valid context → EXECUTABLE ----------

def test_valid_context_returns_executable() -> None:
    order = _order()
    ctx = _context(order)
    check = _check(order, ctx)
    decision = _gate().check(check)
    assert decision.executable is True
    assert decision.reason is ExecutionCapabilityDecisionReason.EXECUTABLE
    assert decision.venue_validation_reason == VenueOrderValidationReason.OK.value


def test_executable_decision_check_id_matches_check() -> None:
    order = _order()
    ctx = _context(order)
    check = _check(order, ctx)
    decision = _gate().check(check)
    assert decision.check_id == check.check_id


# ---------- Disabled venue → REJECTED_BY_VENUE_CAPABILITY ----------

def test_disabled_venue_returns_rejected_by_venue_capability() -> None:
    order = _order()
    venue = _venue(trading_status=VenueTradingStatus.DISABLED)
    ctx = _context(order, venue=venue)
    check = _check(order, ctx)
    decision = _gate().check(check)
    assert decision.executable is False
    assert decision.reason is ExecutionCapabilityDecisionReason.REJECTED_BY_VENUE_CAPABILITY
    assert decision.venue_validation_reason == VenueOrderValidationReason.VENUE_TRADING_DISABLED.value  # noqa: E501


def test_disabled_venue_decision_has_details() -> None:
    order = _order()
    venue = _venue(trading_status=VenueTradingStatus.DISABLED)
    ctx = _context(order, venue=venue)
    check = _check(order, ctx)
    decision = _gate().check(check)
    assert decision.venue_validation_details is not None


# ---------- Unsupported reduce_only → REJECTED_BY_VENUE_CAPABILITY ----------

def test_unsupported_reduce_only_returns_rejected_by_venue_capability() -> None:
    order = _order(reduce_only=True, intent_kind=OrderIntentKind.EXIT, side=OrderSide.SELL)
    venue = _venue(supports_reduce_only=False)
    rules = _rules(supports_reduce_only=False)
    ctx = _context(order, venue=venue, rules=rules)
    check = _check(order, ctx)
    decision = _gate().check(check)
    assert decision.executable is False
    assert decision.reason is ExecutionCapabilityDecisionReason.REJECTED_BY_VENUE_CAPABILITY
    assert decision.venue_validation_reason == VenueOrderValidationReason.UNSUPPORTED_REDUCE_ONLY.value  # noqa: E501


# ---------- Off-tick price → REJECTED_BY_VENUE_CAPABILITY ----------

def test_off_tick_price_returns_rejected_by_venue_capability() -> None:
    order = _order(order_type=OrderType.LIMIT, limit_price="100.05")
    ctx = _context(order)
    check = _check(order, ctx)
    decision = _gate().check(check)
    assert decision.executable is False
    assert decision.reason is ExecutionCapabilityDecisionReason.REJECTED_BY_VENUE_CAPABILITY
    assert decision.venue_validation_reason == VenueOrderValidationReason.PRICE_NOT_ON_TICK.value


def test_on_tick_price_returns_executable() -> None:
    order = _order(order_type=OrderType.LIMIT, limit_price="100.0")
    ctx = _context(order)
    check = _check(order, ctx)
    decision = _gate().check(check)
    assert decision.executable is True


# ---------- API trading disabled → REJECTED_BY_VENUE_CAPABILITY ----------

def test_api_trading_disabled_returns_rejected() -> None:
    order = _order()
    venue = _venue(api_trading_enabled=False)
    ctx = _context(order, venue=venue)
    check = _check(order, ctx)
    decision = _gate().check(check)
    assert decision.executable is False
    assert decision.venue_validation_reason == VenueOrderValidationReason.API_TRADING_DISABLED.value


# ---------- Halted instrument → REJECTED_BY_VENUE_CAPABILITY ----------

def test_halted_instrument_returns_rejected() -> None:
    order = _order()
    rules = _rules(trading_status=InstrumentTradingStatus.HALTED)
    ctx = _context(order, rules=rules)
    check = _check(order, ctx)
    decision = _gate().check(check)
    assert decision.executable is False
    assert decision.venue_validation_reason == VenueOrderValidationReason.INSTRUMENT_NOT_TRADING.value  # noqa: E501


# ---------- Decision determinism ----------

def test_gate_decision_is_deterministic_for_same_inputs() -> None:
    order = _order()
    ctx = _context(order)
    check = _check(order, ctx)
    gate = _gate()
    d1 = gate.check(check)
    d2 = gate.check(check)
    assert d1.decision_id == d2.decision_id
    assert d1 == d2


# ---------- Venue validation reason preserved through gate ----------

def test_venue_validation_details_preserved_on_executable() -> None:
    order = _order()
    ctx = _context(order)
    check = _check(order, ctx)
    decision = _gate().check(check)
    assert isinstance(decision.venue_validation_details, dict)


def test_venue_validation_reason_preserved_on_rejection() -> None:
    order = _order()
    venue = _venue(trading_status=VenueTradingStatus.DISABLED)
    ctx = _context(order, venue=venue)
    check = _check(order, ctx)
    decision = _gate().check(check)
    assert decision.venue_validation_reason == "VENUE_TRADING_DISABLED"
    assert decision.venue_validation_details is not None
