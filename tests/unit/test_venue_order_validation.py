from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
    TimeInForce,
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
from futures_bot.venue_capabilities.validator import (
    validate_order_against_venue_capabilities,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _dead_man() -> DeadManSwitchCapability:
    return DeadManSwitchCapability(
        capability_id=DeadManSwitchCapabilityId(value="dead-man-1"),
        supported=False,
        scope_kind=DeadManSwitchScopeKind.ACCOUNT,
    )


def _venue(**overrides: object) -> VenueCapabilitySnapshot:
    values = {
        "snapshot_id": VenueCapabilitySnapshotId(value="venue-cap-1"),
        "venue_id": "venue-1",
        "trading_status": VenueTradingStatus.ENABLED,
        "api_trading_enabled": True,
        "captured_at": NOW,
        "supported_margin_assets": ("USDT", "USDC"),
        "supported_settlement_assets": ("USDT", "USDC"),
        "supported_position_modes": (VenuePositionMode.ONE_WAY, VenuePositionMode.HEDGE),
        "supports_reduce_only": True,
        "supports_post_only": True,
        "supports_close_position": True,
        "supports_gtd": True,
        "min_gtd_duration_ms": 60_000,
        "supports_price_protection": True,
        "supported_self_trade_prevention_modes": (VenueSelfTradePreventionMode.NONE,),
        "dead_man_switch": _dead_man(),
    }
    values.update(overrides)
    return VenueCapabilitySnapshot(**values)


def _rules(**overrides: object) -> VenueInstrumentRuleSnapshot:
    values = {
        "snapshot_id": VenueInstrumentRuleSnapshotId(value="rules-1"),
        "venue_id": "venue-1",
        "instrument_id": "BTC-PERP",
        "symbol": "BTCUSDT",
        "trading_status": InstrumentTradingStatus.TRADING,
        "contract_kind": FuturesContractKind.LINEAR_PERPETUAL,
        "margin_asset": "USDT",
        "settlement_asset": "USDT",
        "captured_at": NOW,
        "price_filter": PriceFilter(tick_size=Decimal("0.1"), price_precision=1),
        "quantity_filter": QuantityFilter(
            step_size=Decimal("0.001"),
            min_quantity=Decimal("0.001"),
            max_quantity=Decimal("100"),
            quantity_precision=3,
        ),
        "notional_filter": NotionalFilter(
            min_notional=Decimal("5"),
            max_notional=Decimal("1000000"),
            requires_reference_price_for_market_orders=True,
        ),
        "max_leverage": "20",
        "supported_order_types": (
            "MARKET",
            "LIMIT",
            "STOP_MARKET",
            "STOP_LIMIT",
            "TAKE_PROFIT_MARKET",
            "TAKE_PROFIT_LIMIT",
        ),
        "supported_time_in_force": ("GTC", "IOC", "FOK", "GTD"),
        "supports_reduce_only": True,
        "supports_post_only": True,
        "supports_close_position": True,
        "supports_gtd": True,
        "min_gtd_duration_ms": 30_000,
        "supports_price_protection": True,
        "supported_self_trade_prevention_modes": (VenueSelfTradePreventionMode.NONE,),
    }
    values.update(overrides)
    return VenueInstrumentRuleSnapshot(**values)


def _order(**overrides: object) -> OrderIntent:
    values = {
        "intent_kind": OrderIntentKind.ENTRY,
        "venue_id": "venue-1",
        "instrument_id": "BTC-PERP",
        "side": OrderSide.BUY,
        "position_side": PositionSide.LONG,
        "order_type": OrderType.MARKET,
        "time_in_force": None,
        "quantity": Decimal("0.01"),
        "limit_price": None,
        "stop_price": None,
        "reduce_only": False,
        "post_only": False,
        "close_position": False,
        "permission_reason": OrderFlowPermissionReason.OK,
        "created_at": NOW,
    }
    values.update(overrides)
    return OrderIntent(**values)


def _context(
    *,
    order: OrderIntent | None = None,
    venue: VenueCapabilitySnapshot | None = None,
    rules: VenueInstrumentRuleSnapshot | None = None,
    reference_price: Decimal | None = Decimal("1000"),
) -> VenueOrderValidationContext:
    return VenueOrderValidationContext(
        order_intent=order or _order(),
        venue_snapshot=venue or _venue(),
        instrument_rules=rules or _rules(),
        reference_price=reference_price,
        requested_at=NOW,
    )


def _unsafe_context(order: OrderIntent) -> VenueOrderValidationContext:
    return VenueOrderValidationContext.model_construct(
        validation_id=_context().validation_id,
        order_intent=order,
        venue_snapshot=_venue(),
        instrument_rules=_rules(),
        reference_price=Decimal("1000"),
        requested_at=NOW,
    )


def _reason(context: VenueOrderValidationContext) -> VenueOrderValidationReason:
    return validate_order_against_venue_capabilities(context).reason


def _bounded_price_filter() -> PriceFilter:
    return PriceFilter(
        tick_size=Decimal("0.1"),
        min_price=Decimal("100"),
        max_price=Decimal("1000"),
        price_precision=1,
    )


def test_valid_linear_usdt_order_passes() -> None:
    result = validate_order_against_venue_capabilities(_context())

    assert result.valid
    assert result.reason is VenueOrderValidationReason.OK
    assert result.normalized_quantity == _order().quantity


def test_disabled_venue_rejects() -> None:
    assert _reason(_context(venue=_venue(trading_status=VenueTradingStatus.DISABLED))) is (
        VenueOrderValidationReason.VENUE_TRADING_DISABLED
    )


def test_api_trading_disabled_rejects() -> None:
    assert _reason(_context(venue=_venue(api_trading_enabled=False))) is (
        VenueOrderValidationReason.API_TRADING_DISABLED
    )


def test_halted_instrument_rejects() -> None:
    assert _reason(_context(rules=_rules(trading_status=InstrumentTradingStatus.HALTED))) is (
        VenueOrderValidationReason.INSTRUMENT_NOT_TRADING
    )


def test_inverse_contract_rejects() -> None:
    assert _reason(_context(rules=_rules(contract_kind=FuturesContractKind.INVERSE_PERPETUAL))) is (
        VenueOrderValidationReason.UNSUPPORTED_CONTRACT_KIND
    )


def test_btc_collateral_margin_rejects() -> None:
    assert _reason(_context(rules=_rules(margin_asset="BTC"))) is (
        VenueOrderValidationReason.UNSUPPORTED_MARGIN_ASSET
    )


def test_unsupported_order_type_rejects() -> None:
    order = _order(order_type=OrderType.LIMIT, limit_price="1000", time_in_force=TimeInForce.GTC)
    assert _reason(_context(order=order, rules=_rules(supported_order_types=("MARKET",)))) is (
        VenueOrderValidationReason.UNSUPPORTED_ORDER_TYPE
    )


def test_unsupported_tif_rejects() -> None:
    order = _order(order_type=OrderType.LIMIT, limit_price="1000", time_in_force=TimeInForce.GTC)
    assert _reason(_context(order=order, rules=_rules(supported_time_in_force=("IOC",)))) is (
        VenueOrderValidationReason.UNSUPPORTED_TIME_IN_FORCE
    )


def test_reduce_only_unsupported_rejects() -> None:
    order = _order(intent_kind=OrderIntentKind.REDUCE_ONLY, reduce_only=True)
    assert _reason(_context(order=order, venue=_venue(supports_reduce_only=False))) is (
        VenueOrderValidationReason.UNSUPPORTED_REDUCE_ONLY
    )


def test_post_only_unsupported_rejects() -> None:
    order = _order(order_type=OrderType.LIMIT, limit_price="1000", post_only=True)
    assert _reason(_context(order=order, rules=_rules(supports_post_only=False))) is (
        VenueOrderValidationReason.UNSUPPORTED_POST_ONLY
    )


def test_close_position_unsupported_rejects() -> None:
    order = _order(
        intent_kind=OrderIntentKind.EMERGENCY_CLOSE,
        quantity=None,
        reduce_only=True,
        close_position=True,
    )
    assert _reason(_context(order=order, venue=_venue(supports_close_position=False))) is (
        VenueOrderValidationReason.UNSUPPORTED_CLOSE_POSITION
    )


def test_gtd_unsupported_rejects() -> None:
    order = _order(
        order_type=OrderType.LIMIT,
        limit_price="1000",
        time_in_force=TimeInForce.GTD,
        expires_at=NOW + timedelta(minutes=2),
    )
    assert _reason(_context(order=order, rules=_rules(supports_gtd=False))) is (
        VenueOrderValidationReason.UNSUPPORTED_GTD
    )


def test_gtd_below_minimum_rejects() -> None:
    order = _order(
        order_type=OrderType.LIMIT,
        limit_price="1000",
        time_in_force=TimeInForce.GTD,
        expires_at=NOW + timedelta(seconds=30),
    )
    assert _reason(_context(order=order)) is VenueOrderValidationReason.GTD_BELOW_MINIMUM


def test_limit_missing_price_rejects() -> None:
    order = _order().model_copy(update={"order_type": OrderType.LIMIT})
    assert _reason(_unsafe_context(order)) is VenueOrderValidationReason.PRICE_REQUIRED


def test_stop_market_missing_stop_price_rejects() -> None:
    order = _order().model_copy(update={"order_type": OrderType.STOP_MARKET})
    assert _reason(_unsafe_context(order)) is VenueOrderValidationReason.PRICE_REQUIRED


def test_limit_price_below_min_rejects_before_tick() -> None:
    order = _order(order_type=OrderType.LIMIT, limit_price="99.95")
    assert _reason(_context(order=order, rules=_rules(price_filter=_bounded_price_filter()))) is (
        VenueOrderValidationReason.PRICE_BELOW_MINIMUM
    )


def test_limit_price_above_max_rejects() -> None:
    order = _order(order_type=OrderType.LIMIT, limit_price="1000.1")
    assert _reason(_context(order=order, rules=_rules(price_filter=_bounded_price_filter()))) is (
        VenueOrderValidationReason.PRICE_ABOVE_MAXIMUM
    )


def test_stop_price_below_min_rejects_before_tick() -> None:
    order = _order(
        intent_kind=OrderIntentKind.PROTECTIVE_STOP,
        order_type=OrderType.STOP_MARKET,
        stop_price="99.95",
        reduce_only=True,
    )
    assert _reason(_context(order=order, rules=_rules(price_filter=_bounded_price_filter()))) is (
        VenueOrderValidationReason.STOP_PRICE_BELOW_MINIMUM
    )


def test_stop_price_above_max_rejects() -> None:
    order = _order(
        intent_kind=OrderIntentKind.PROTECTIVE_STOP,
        order_type=OrderType.STOP_MARKET,
        stop_price="1000.1",
        reduce_only=True,
    )
    assert _reason(_context(order=order, rules=_rules(price_filter=_bounded_price_filter()))) is (
        VenueOrderValidationReason.STOP_PRICE_ABOVE_MAXIMUM
    )


def test_off_tick_limit_price_rejects() -> None:
    order = _order(order_type=OrderType.LIMIT, limit_price="1000.05")
    assert _reason(_context(order=order)) is VenueOrderValidationReason.PRICE_NOT_ON_TICK


def test_off_tick_stop_price_rejects() -> None:
    order = _order(
        intent_kind=OrderIntentKind.PROTECTIVE_STOP,
        order_type=OrderType.STOP_MARKET,
        stop_price="999.95",
        reduce_only=True,
    )
    assert _reason(_context(order=order)) is VenueOrderValidationReason.STOP_PRICE_NOT_ON_TICK


def test_quantity_below_min_rejects() -> None:
    order = _order(quantity="0.0005")
    assert _reason(_context(order=order)) is VenueOrderValidationReason.QUANTITY_BELOW_MINIMUM


def test_quantity_above_max_rejects() -> None:
    order = _order(quantity="101")
    assert _reason(_context(order=order)) is VenueOrderValidationReason.QUANTITY_ABOVE_MAXIMUM


def test_quantity_off_step_rejects() -> None:
    order = _order(quantity="0.0015")
    assert _reason(_context(order=order)) is VenueOrderValidationReason.QUANTITY_NOT_ON_STEP


def test_market_notional_requiring_reference_price_rejects_when_missing() -> None:
    assert _reason(_context(reference_price=None)) is (
        VenueOrderValidationReason.REFERENCE_PRICE_REQUIRED
    )


def test_notional_below_min_rejects() -> None:
    order = _order(quantity="0.004")
    assert _reason(_context(order=order, reference_price=Decimal("1000"))) is (
        VenueOrderValidationReason.NOTIONAL_BELOW_MINIMUM
    )


def test_stop_market_notional_below_min_uses_stop_price_when_reference_missing() -> None:
    order = _order(
        intent_kind=OrderIntentKind.PROTECTIVE_STOP,
        order_type=OrderType.STOP_MARKET,
        quantity="0.001",
        stop_price="1000",
        reduce_only=True,
    )
    assert _reason(_context(order=order, reference_price=None)) is (
        VenueOrderValidationReason.NOTIONAL_BELOW_MINIMUM
    )


def test_take_profit_market_notional_below_min_uses_stop_price_when_reference_missing() -> None:
    order = _order(
        intent_kind=OrderIntentKind.PROTECTIVE_TAKE_PROFIT,
        order_type=OrderType.TAKE_PROFIT_MARKET,
        quantity="0.001",
        stop_price="1000",
        reduce_only=True,
    )
    assert _reason(_context(order=order, reference_price=None)) is (
        VenueOrderValidationReason.NOTIONAL_BELOW_MINIMUM
    )


def test_stop_market_notional_above_max_uses_stop_price_when_reference_missing() -> None:
    order = _order(
        intent_kind=OrderIntentKind.PROTECTIVE_STOP,
        order_type=OrderType.STOP_MARKET,
        quantity="0.001",
        stop_price="1000",
        reduce_only=True,
    )
    rules = _rules(
        notional_filter=NotionalFilter(
            min_notional=Decimal("0.1"),
            max_notional=Decimal("0.5"),
            requires_reference_price_for_market_orders=True,
        )
    )
    assert _reason(_context(order=order, rules=rules, reference_price=None)) is (
        VenueOrderValidationReason.NOTIONAL_ABOVE_MAXIMUM
    )


def test_take_profit_market_notional_above_max_uses_stop_price_when_reference_missing() -> None:
    order = _order(
        intent_kind=OrderIntentKind.PROTECTIVE_TAKE_PROFIT,
        order_type=OrderType.TAKE_PROFIT_MARKET,
        quantity="0.001",
        stop_price="1000",
        reduce_only=True,
    )
    rules = _rules(
        notional_filter=NotionalFilter(
            min_notional=Decimal("0.1"),
            max_notional=Decimal("0.5"),
            requires_reference_price_for_market_orders=True,
        )
    )
    assert _reason(_context(order=order, rules=rules, reference_price=None)) is (
        VenueOrderValidationReason.NOTIONAL_ABOVE_MAXIMUM
    )


def test_valid_close_position_emergency_order_does_not_require_quantity() -> None:
    order = _order(
        intent_kind=OrderIntentKind.EMERGENCY_CLOSE,
        quantity=None,
        reduce_only=True,
        close_position=True,
    )
    result = validate_order_against_venue_capabilities(_context(order=order))

    assert result.valid
    assert result.reason is VenueOrderValidationReason.OK
