from __future__ import annotations

from datetime import UTC, datetime
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


def dead_man() -> DeadManSwitchCapability:
    return DeadManSwitchCapability(
        capability_id=DeadManSwitchCapabilityId(value="dead-man-1"),
        supported=False,
        scope_kind=DeadManSwitchScopeKind.ACCOUNT,
    )


def venue(**overrides: object) -> VenueCapabilitySnapshot:
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
        "dead_man_switch": dead_man(),
    }
    values.update(overrides)
    return VenueCapabilitySnapshot(**values)


def rules(**overrides: object) -> VenueInstrumentRuleSnapshot:
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


def order(**overrides: object) -> OrderIntent:
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


def context(
    order_intent: OrderIntent,
    venue_snapshot: VenueCapabilitySnapshot | None = None,
    instrument_rules: VenueInstrumentRuleSnapshot | None = None,
) -> VenueOrderValidationContext:
    return VenueOrderValidationContext(
        order_intent=order_intent,
        venue_snapshot=venue_snapshot or venue(),
        instrument_rules=instrument_rules or rules(),
        requested_at=NOW,
    )


def permission(
    *,
    allow_new_entries: bool = True,
    allow_exit_orders: bool = True,
    guardian_required: bool = False,
) -> OrderFlowPermission:
    return OrderFlowPermission(
        allow_new_entries=allow_new_entries,
        allow_entry_order_cancel=True,
        allow_exit_orders=allow_exit_orders,
        allow_reduce_only_orders=True,
        allow_exit_order_cancel=True,
        allow_emergency_close=True,
        allow_reconciliation=False,
        guardian_required=guardian_required,
        manual_intervention_required=False,
        reason=OrderFlowPermissionReason.OK,
    )
