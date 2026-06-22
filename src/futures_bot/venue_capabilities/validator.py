from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from futures_bot.domain.order_lifecycle import OrderType, TimeInForce
from futures_bot.domain.venue_capabilities import (
    FuturesContractKind,
    InstrumentTradingStatus,
    StableCollateralAsset,
    VenueOrderValidationContext,
    VenueOrderValidationReason,
    VenueOrderValidationResult,
    VenueTradingStatus,
)


def validate_order_against_venue_capabilities(
    context: VenueOrderValidationContext,
) -> VenueOrderValidationResult:
    """Validate hard venue/instrument executability constraints for one order."""

    for check in (
        _trading_status_reason,
        _contract_and_asset_reason,
        _order_support_reason,
        _gtd_reason,
        _price_reason,
        _quantity_and_notional_reason,
    ):
        reason = check(context)
        if reason is not None:
            return _invalid(context, reason)

    order = context.order_intent
    return VenueOrderValidationResult(
        validation_id=_validation_id(context),
        valid=True,
        reason=VenueOrderValidationReason.OK,
        normalized_quantity=order.quantity,
        normalized_limit_price=order.limit_price,
        normalized_stop_price=order.stop_price,
        details={"message": "order is executable under supplied venue capabilities"},
    )


def _trading_status_reason(
    context: VenueOrderValidationContext,
) -> VenueOrderValidationReason | None:
    venue = context.venue_snapshot
    rules = context.instrument_rules
    if venue.trading_status is not VenueTradingStatus.ENABLED:
        return VenueOrderValidationReason.VENUE_TRADING_DISABLED
    if not venue.api_trading_enabled:
        return VenueOrderValidationReason.API_TRADING_DISABLED
    if rules.trading_status is not InstrumentTradingStatus.TRADING:
        return VenueOrderValidationReason.INSTRUMENT_NOT_TRADING
    return None


def _contract_and_asset_reason(
    context: VenueOrderValidationContext,
) -> VenueOrderValidationReason | None:
    venue = context.venue_snapshot
    rules = context.instrument_rules
    if rules.contract_kind not in {
        FuturesContractKind.LINEAR_PERPETUAL,
        FuturesContractKind.LINEAR_DELIVERY,
    }:
        return VenueOrderValidationReason.UNSUPPORTED_CONTRACT_KIND
    if not _is_stable_asset(rules.margin_asset):
        return VenueOrderValidationReason.UNSUPPORTED_MARGIN_ASSET
    if not _is_stable_asset(rules.settlement_asset):
        return VenueOrderValidationReason.UNSUPPORTED_SETTLEMENT_ASSET
    if rules.margin_asset not in venue.supported_margin_assets:
        return VenueOrderValidationReason.ACCOUNT_ASSET_MISMATCH
    if rules.settlement_asset not in venue.supported_settlement_assets:
        return VenueOrderValidationReason.ACCOUNT_ASSET_MISMATCH
    return None


def _order_support_reason(
    context: VenueOrderValidationContext,
) -> VenueOrderValidationReason | None:
    order = context.order_intent
    venue = context.venue_snapshot
    rules = context.instrument_rules
    if order.order_type.value not in rules.supported_order_types:
        return VenueOrderValidationReason.UNSUPPORTED_ORDER_TYPE
    if (
        order.time_in_force is not None
        and order.time_in_force.value not in rules.supported_time_in_force
    ):
        return VenueOrderValidationReason.UNSUPPORTED_TIME_IN_FORCE
    if order.reduce_only and (not venue.supports_reduce_only or not rules.supports_reduce_only):
        return VenueOrderValidationReason.UNSUPPORTED_REDUCE_ONLY
    if order.post_only and (not venue.supports_post_only or not rules.supports_post_only):
        return VenueOrderValidationReason.UNSUPPORTED_POST_ONLY
    if order.close_position and (
        not venue.supports_close_position or not rules.supports_close_position
    ):
        return VenueOrderValidationReason.UNSUPPORTED_CLOSE_POSITION
    return None


def _gtd_reason(context: VenueOrderValidationContext) -> VenueOrderValidationReason | None:
    order = context.order_intent
    venue = context.venue_snapshot
    rules = context.instrument_rules
    if order.time_in_force is TimeInForce.GTD:
        if not venue.supports_gtd or not rules.supports_gtd:
            return VenueOrderValidationReason.UNSUPPORTED_GTD
        if _gtd_below_minimum(context):
            return VenueOrderValidationReason.GTD_BELOW_MINIMUM
    return None


def _price_reason(context: VenueOrderValidationContext) -> VenueOrderValidationReason | None:
    required_reason = _required_price_reason(context)
    if required_reason is not None:
        return required_reason
    return _price_filter_reason(context)


def _required_price_reason(
    context: VenueOrderValidationContext,
) -> VenueOrderValidationReason | None:
    order = context.order_intent
    if order.order_type in {
        OrderType.LIMIT,
        OrderType.STOP_LIMIT,
        OrderType.TAKE_PROFIT_LIMIT,
    } and order.limit_price is None:
        return VenueOrderValidationReason.PRICE_REQUIRED
    if order.order_type in {
        OrderType.STOP_MARKET,
        OrderType.STOP_LIMIT,
        OrderType.TAKE_PROFIT_MARKET,
        OrderType.TAKE_PROFIT_LIMIT,
    } and order.stop_price is None:
        return VenueOrderValidationReason.PRICE_REQUIRED
    return None


def _price_filter_reason(
    context: VenueOrderValidationContext,
) -> VenueOrderValidationReason | None:
    order = context.order_intent
    rules = context.instrument_rules
    limit_price = order.limit_price
    stop_price = order.stop_price
    bounds_reason = _price_bounds_reason(context)
    if bounds_reason is not None:
        return bounds_reason
    if limit_price is not None and not rules.price_filter.is_price_on_tick(limit_price):
        return VenueOrderValidationReason.PRICE_NOT_ON_TICK
    if stop_price is not None and not rules.price_filter.is_price_on_tick(stop_price):
        return VenueOrderValidationReason.STOP_PRICE_NOT_ON_TICK
    if limit_price is not None and not rules.price_filter.price_precision_ok(limit_price):
        return VenueOrderValidationReason.PRICE_PRECISION_EXCEEDED
    if stop_price is not None and not rules.price_filter.price_precision_ok(stop_price):
        return VenueOrderValidationReason.PRICE_PRECISION_EXCEEDED
    return None


def _price_bounds_reason(
    context: VenueOrderValidationContext,
) -> VenueOrderValidationReason | None:
    price_filter = context.instrument_rules.price_filter
    limit_price = context.order_intent.limit_price
    stop_price = context.order_intent.stop_price
    if (
        limit_price is not None
        and price_filter.min_price is not None
        and limit_price < price_filter.min_price
    ):
        return VenueOrderValidationReason.PRICE_BELOW_MINIMUM
    if (
        limit_price is not None
        and price_filter.max_price is not None
        and limit_price > price_filter.max_price
    ):
        return VenueOrderValidationReason.PRICE_ABOVE_MAXIMUM
    if (
        stop_price is not None
        and price_filter.min_price is not None
        and stop_price < price_filter.min_price
    ):
        return VenueOrderValidationReason.STOP_PRICE_BELOW_MINIMUM
    if (
        stop_price is not None
        and price_filter.max_price is not None
        and stop_price > price_filter.max_price
    ):
        return VenueOrderValidationReason.STOP_PRICE_ABOVE_MAXIMUM
    return None


def _quantity_and_notional_reason(
    context: VenueOrderValidationContext,
) -> VenueOrderValidationReason | None:
    order = context.order_intent
    quantity = order.quantity
    if quantity is None:
        if not order.close_position:
            return VenueOrderValidationReason.QUANTITY_REQUIRED
        return None
    quantity_reason = _quantity_filter_reason(context, quantity)
    if quantity_reason is not None:
        return quantity_reason
    return _notional_reason(context, quantity)


def _quantity_filter_reason(
    context: VenueOrderValidationContext,
    quantity: Decimal,
) -> VenueOrderValidationReason | None:
    rules = context.instrument_rules
    if quantity < rules.quantity_filter.min_quantity:
        return VenueOrderValidationReason.QUANTITY_BELOW_MINIMUM
    if (
        rules.quantity_filter.max_quantity is not None
        and quantity > rules.quantity_filter.max_quantity
    ):
        return VenueOrderValidationReason.QUANTITY_ABOVE_MAXIMUM
    if not rules.quantity_filter.is_quantity_on_step(quantity):
        return VenueOrderValidationReason.QUANTITY_NOT_ON_STEP
    if not rules.quantity_filter.quantity_precision_ok(quantity):
        return VenueOrderValidationReason.QUANTITY_PRECISION_EXCEEDED
    return None


def _notional_reason(
    context: VenueOrderValidationContext,
    quantity: Decimal,
) -> VenueOrderValidationReason | None:
    order = context.order_intent
    rules = context.instrument_rules
    notional = _compute_notional(context, quantity)
    if notional is None:
        if (
            order.order_type is OrderType.MARKET
            and rules.notional_filter.requires_reference_price_for_market_orders
        ):
            return VenueOrderValidationReason.REFERENCE_PRICE_REQUIRED
        return None
    if (
        rules.notional_filter.min_notional is not None
        and notional < rules.notional_filter.min_notional
    ):
        return VenueOrderValidationReason.NOTIONAL_BELOW_MINIMUM
    if (
        rules.notional_filter.max_notional is not None
        and notional > rules.notional_filter.max_notional
    ):
        return VenueOrderValidationReason.NOTIONAL_ABOVE_MAXIMUM
    return None


def _invalid(
    context: VenueOrderValidationContext,
    reason: VenueOrderValidationReason,
) -> VenueOrderValidationResult:
    return VenueOrderValidationResult(
        validation_id=_validation_id(context),
        valid=False,
        reason=reason,
        details={"reason": reason.value},
    )


def _validation_id(context: VenueOrderValidationContext):
    if context.validation_id is None:
        raise ValueError("validation_id is required")
    return context.validation_id


def _is_stable_asset(value: str) -> bool:
    return value in {StableCollateralAsset.USDT.value, StableCollateralAsset.USDC.value}


def _gtd_below_minimum(context: VenueOrderValidationContext) -> bool:
    order = context.order_intent
    if order.expires_at is None:
        return False
    minimums = tuple(
        item
        for item in (
            context.venue_snapshot.min_gtd_duration_ms,
            context.instrument_rules.min_gtd_duration_ms,
        )
        if item is not None
    )
    if not minimums:
        return False
    duration = order.expires_at - order.created_at
    return duration < timedelta(milliseconds=max(minimums))


def _compute_notional(
    context: VenueOrderValidationContext,
    quantity: Decimal,
) -> Decimal | None:
    order = context.order_intent
    if order.limit_price is not None:
        return quantity * order.limit_price
    if context.reference_price is not None:
        return quantity * context.reference_price
    if order.order_type in {
        OrderType.STOP_MARKET,
        OrderType.TAKE_PROFIT_MARKET,
    } and order.stop_price is not None:
        return quantity * order.stop_price
    return None
