from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import (
    DeadManSwitchCapabilityId,
    VenueCapabilitySnapshotId,
    VenueInstrumentRuleSnapshotId,
    VenueOrderValidationId,
    VenueRateLimitProfileId,
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
    VenueOrderValidationResult,
    VenuePositionMode,
    VenueRateLimitProfile,
    VenueRateLimitRule,
    VenueSelfTradePreventionMode,
    VenueTradingStatus,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _dead_man() -> DeadManSwitchCapability:
    return DeadManSwitchCapability(
        capability_id=DeadManSwitchCapabilityId(value="dead-man-1"),
        supported=True,
        scope_kind=DeadManSwitchScopeKind.ACCOUNT,
        min_countdown_ms=1_000,
        max_countdown_ms=60_000,
        recommended_heartbeat_ms=5_000,
    )


def _venue(*, venue_id: str = "venue-1") -> VenueCapabilitySnapshot:
    return VenueCapabilitySnapshot(
        snapshot_id=VenueCapabilitySnapshotId(value=f"venue-cap:{venue_id}"),
        venue_id=venue_id,
        trading_status=VenueTradingStatus.ENABLED,
        api_trading_enabled=True,
        captured_at=NOW,
        supported_margin_assets=("USDT", "USDC"),
        supported_settlement_assets=("USDT", "USDC"),
        supported_position_modes=(VenuePositionMode.ONE_WAY, VenuePositionMode.HEDGE),
        supports_reduce_only=True,
        supports_post_only=True,
        supports_close_position=True,
        supports_gtd=True,
        min_gtd_duration_ms=60_000,
        supports_price_protection=True,
        supported_self_trade_prevention_modes=(VenueSelfTradePreventionMode.NONE,),
        dead_man_switch=_dead_man(),
    )


def _rules(
    *,
    venue_id: str = "venue-1",
    instrument_id: str = "BTC-PERP",
) -> VenueInstrumentRuleSnapshot:
    return VenueInstrumentRuleSnapshot(
        snapshot_id=VenueInstrumentRuleSnapshotId(
            value=f"rules:{venue_id}:{instrument_id}"
        ),
        venue_id=venue_id,
        instrument_id=instrument_id,
        symbol=instrument_id,
        trading_status=InstrumentTradingStatus.TRADING,
        contract_kind=FuturesContractKind.LINEAR_PERPETUAL,
        margin_asset="USDT",
        settlement_asset="USDT",
        captured_at=NOW,
        price_filter=PriceFilter(tick_size=Decimal("0.1"), price_precision=1),
        quantity_filter=QuantityFilter(
            step_size=Decimal("0.001"),
            min_quantity=Decimal("0.001"),
            quantity_precision=3,
        ),
        notional_filter=NotionalFilter(
            min_notional=Decimal("5"),
            requires_reference_price_for_market_orders=True,
        ),
        max_leverage=Decimal("20"),
        supported_order_types=("MARKET", "LIMIT"),
        supported_time_in_force=("GTC", "IOC", "FOK", "GTD"),
        supports_reduce_only=True,
        supports_post_only=True,
        supports_close_position=True,
        supports_gtd=True,
        min_gtd_duration_ms=30_000,
        supports_price_protection=True,
        supported_self_trade_prevention_modes=(VenueSelfTradePreventionMode.NONE,),
    )


def _order(*, venue_id: str = "venue-1", instrument_id: str = "BTC-PERP") -> OrderIntent:
    return OrderIntent(
        intent_kind=OrderIntentKind.ENTRY,
        venue_id=venue_id,
        instrument_id=instrument_id,
        side=OrderSide.BUY,
        position_side=PositionSide.LONG,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        reduce_only=False,
        post_only=False,
        close_position=False,
        permission_reason=OrderFlowPermissionReason.OK,
        created_at=NOW,
    )


def test_price_filter_rejects_non_positive_tick() -> None:
    with pytest.raises(ValidationError, match="tick_size"):
        PriceFilter(tick_size=Decimal("0"))


def test_quantity_filter_rejects_non_positive_step_min_quantity() -> None:
    with pytest.raises(ValidationError, match="step_size"):
        QuantityFilter(step_size=Decimal("0"), min_quantity=Decimal("1"))
    with pytest.raises(ValidationError, match="min_quantity"):
        QuantityFilter(step_size=Decimal("1"), min_quantity=Decimal("0"))


def test_notional_filter_validates_min_max() -> None:
    with pytest.raises(ValidationError, match="max_notional"):
        NotionalFilter(
            min_notional=Decimal("10"),
            max_notional=Decimal("9"),
            requires_reference_price_for_market_orders=False,
        )


def test_price_filter_detects_off_tick_price() -> None:
    price_filter = PriceFilter(tick_size=Decimal("0.5"))
    assert price_filter.is_price_on_tick(Decimal("100.5"))
    assert not price_filter.is_price_on_tick(Decimal("100.25"))


def test_quantity_filter_detects_off_step_quantity() -> None:
    quantity_filter = QuantityFilter(
        step_size=Decimal("0.01"),
        min_quantity=Decimal("0.01"),
    )
    assert quantity_filter.is_quantity_on_step(Decimal("1.23"))
    assert not quantity_filter.is_quantity_on_step(Decimal("1.234"))


def test_precision_helpers_work_with_decimal() -> None:
    assert PriceFilter(tick_size=Decimal("0.01"), price_precision=2).price_precision_ok(
        Decimal("1.23")
    )
    assert not PriceFilter(
        tick_size=Decimal("0.01"),
        price_precision=2,
    ).price_precision_ok(
        Decimal("1.234")
    )
    assert QuantityFilter(
        step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        quantity_precision=3,
    ).quantity_precision_ok(Decimal("1.234"))
    assert not QuantityFilter(
        step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        quantity_precision=3,
    ).quantity_precision_ok(Decimal("1.2345"))


def test_venue_capability_snapshot_restricts_supported_assets_to_stablecoins() -> None:
    with pytest.raises(ValidationError, match="USDT/USDC"):
        VenueCapabilitySnapshot(
            **{
                **_venue().model_dump(),
                "supported_margin_assets": ("BTC",),
            }
        )
    with pytest.raises(ValidationError, match="USDT/USDC"):
        VenueCapabilitySnapshot(
            **{
                **_venue().model_dump(),
                "supported_settlement_assets": ("BTC",),
            }
        )


def test_venue_instrument_rule_snapshot_rejects_invalid_max_leverage() -> None:
    with pytest.raises(ValidationError, match="max_leverage"):
        VenueInstrumentRuleSnapshot(**{**_rules().model_dump(), "max_leverage": "0"})


def test_dead_man_switch_capability_requires_heartbeat_when_supported() -> None:
    with pytest.raises(ValidationError, match="heartbeat"):
        DeadManSwitchCapability(
            capability_id=DeadManSwitchCapabilityId(value="dead-man-2"),
            supported=True,
            scope_kind=DeadManSwitchScopeKind.ACCOUNT,
        )


def test_rate_limit_rule_requires_positive_window_limits() -> None:
    with pytest.raises(ValidationError, match="window_ms"):
        VenueRateLimitRule(name="orders", window_ms=0, max_orders=1)
    with pytest.raises(ValidationError, match="max_weight"):
        VenueRateLimitRule(name="weights", window_ms=1_000, max_weight=0)

    profile = VenueRateLimitProfile(
        profile_id=VenueRateLimitProfileId(value="rate-limit-1"),
        rules=(VenueRateLimitRule(name="orders", window_ms=1_000, max_orders=100),),
    )
    assert profile.rules[0].max_orders == 100


def test_validation_result_valid_reason_consistency() -> None:
    with pytest.raises(ValidationError, match="valid results"):
        VenueOrderValidationResult(
            validation_id=VenueOrderValidationId(value="validation-1"),
            valid=True,
            reason=VenueOrderValidationReason.PRICE_REQUIRED,
            details={},
        )
    with pytest.raises(ValidationError, match="invalid results"):
        VenueOrderValidationResult(
            validation_id=VenueOrderValidationId(value="validation-2"),
            valid=False,
            reason=VenueOrderValidationReason.OK,
            details={},
        )


def test_validation_reasons_include_price_bound_failures() -> None:
    assert VenueOrderValidationReason.PRICE_BELOW_MINIMUM.value == "PRICE_BELOW_MINIMUM"
    assert VenueOrderValidationReason.PRICE_ABOVE_MAXIMUM.value == "PRICE_ABOVE_MAXIMUM"
    assert (
        VenueOrderValidationReason.STOP_PRICE_BELOW_MINIMUM.value
        == "STOP_PRICE_BELOW_MINIMUM"
    )
    assert (
        VenueOrderValidationReason.STOP_PRICE_ABOVE_MAXIMUM.value
        == "STOP_PRICE_ABOVE_MAXIMUM"
    )


def test_validation_context_rejects_venue_instrument_mismatch() -> None:
    with pytest.raises(ValidationError, match="venue_id"):
        VenueOrderValidationContext(
            order_intent=_order(venue_id="venue-2"),
            venue_snapshot=_venue(),
            instrument_rules=_rules(),
            requested_at=NOW,
        )
    with pytest.raises(ValidationError, match="instrument_id"):
        VenueOrderValidationContext(
            order_intent=_order(instrument_id="ETH-PERP"),
            venue_snapshot=_venue(),
            instrument_rules=_rules(),
            requested_at=NOW,
        )


def test_validation_context_deterministic_validation_id() -> None:
    first = VenueOrderValidationContext(
        order_intent=_order(),
        venue_snapshot=_venue(),
        instrument_rules=_rules(),
        reference_price=Decimal("1000"),
        requested_at=NOW,
    )
    second = VenueOrderValidationContext(
        order_intent=_order(),
        venue_snapshot=_venue(),
        instrument_rules=_rules(),
        reference_price=Decimal("1000"),
        requested_at=NOW,
    )

    assert first.validation_id == second.validation_id
