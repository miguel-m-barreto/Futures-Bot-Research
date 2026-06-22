from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_bot.domain.ids import (
    DeadManSwitchCapabilityId,
    VenueCapabilitySnapshotId,
    VenueInstrumentRuleSnapshotId,
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
    VenuePositionMode,
    VenueSelfTradePreventionMode,
    VenueTradingStatus,
)
from futures_bot.venue_capabilities.in_memory import (
    InMemoryVenueCapabilitySnapshotStore,
    InMemoryVenueInstrumentRuleSnapshotStore,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _dead_man() -> DeadManSwitchCapability:
    return DeadManSwitchCapability(
        capability_id=DeadManSwitchCapabilityId(value="dead-man-1"),
        supported=False,
        scope_kind=DeadManSwitchScopeKind.ACCOUNT,
    )


def _venue_snapshot(
    snapshot_id: str,
    *,
    venue_id: str = "venue-1",
    captured_at: datetime = NOW,
) -> VenueCapabilitySnapshot:
    return VenueCapabilitySnapshot(
        snapshot_id=VenueCapabilitySnapshotId(value=snapshot_id),
        venue_id=venue_id,
        trading_status=VenueTradingStatus.ENABLED,
        api_trading_enabled=True,
        captured_at=captured_at,
        supported_margin_assets=("USDT",),
        supported_settlement_assets=("USDT",),
        supported_position_modes=(VenuePositionMode.ONE_WAY,),
        supports_reduce_only=True,
        supports_post_only=True,
        supports_close_position=True,
        supports_gtd=False,
        supports_price_protection=True,
        supported_self_trade_prevention_modes=(VenueSelfTradePreventionMode.NONE,),
        dead_man_switch=_dead_man(),
    )


def _rule_snapshot(
    snapshot_id: str,
    *,
    venue_id: str = "venue-1",
    instrument_id: str = "BTC-PERP",
    captured_at: datetime = NOW,
) -> VenueInstrumentRuleSnapshot:
    return VenueInstrumentRuleSnapshot(
        snapshot_id=VenueInstrumentRuleSnapshotId(value=snapshot_id),
        venue_id=venue_id,
        instrument_id=instrument_id,
        symbol=instrument_id,
        trading_status=InstrumentTradingStatus.TRADING,
        contract_kind=FuturesContractKind.LINEAR_PERPETUAL,
        margin_asset="USDT",
        settlement_asset="USDT",
        captured_at=captured_at,
        price_filter=PriceFilter(tick_size=Decimal("0.1")),
        quantity_filter=QuantityFilter(
            step_size=Decimal("0.001"),
            min_quantity=Decimal("0.001"),
        ),
        notional_filter=NotionalFilter(
            min_notional=Decimal("5"),
            requires_reference_price_for_market_orders=True,
        ),
        supported_order_types=("MARKET",),
        supported_time_in_force=("GTC",),
        supports_reduce_only=True,
        supports_post_only=True,
        supports_close_position=True,
        supports_gtd=False,
        supports_price_protection=True,
        supported_self_trade_prevention_modes=(VenueSelfTradePreventionMode.NONE,),
    )


def test_venue_snapshot_store_idempotent_same_snapshot() -> None:
    store = InMemoryVenueCapabilitySnapshotStore()
    snapshot = _venue_snapshot("venue-cap-1")

    store.put(snapshot)
    store.put(snapshot)

    assert store.get_latest("venue-1") == snapshot


def test_venue_snapshot_store_rejects_same_id_different_payload() -> None:
    store = InMemoryVenueCapabilitySnapshotStore()
    snapshot = _venue_snapshot("venue-cap-1")
    changed = _venue_snapshot("venue-cap-1", venue_id="venue-2")

    store.put(snapshot)
    with pytest.raises(ValueError, match="venue capability snapshot"):
        store.put(changed)


def test_venue_latest_snapshot_uses_captured_at() -> None:
    store = InMemoryVenueCapabilitySnapshotStore()
    older = _venue_snapshot("venue-cap-1", captured_at=NOW)
    newer = _venue_snapshot("venue-cap-2", captured_at=NOW + timedelta(minutes=1))

    store.put(newer)
    store.put(older)

    assert store.get_latest("venue-1") == newer


def test_instrument_rule_store_idempotent_same_snapshot() -> None:
    store = InMemoryVenueInstrumentRuleSnapshotStore()
    snapshot = _rule_snapshot("rules-1")

    store.put(snapshot)
    store.put(snapshot)

    assert store.get_latest("venue-1", "BTC-PERP") == snapshot


def test_instrument_rule_store_rejects_same_id_different_payload() -> None:
    store = InMemoryVenueInstrumentRuleSnapshotStore()
    snapshot = _rule_snapshot("rules-1")
    changed = _rule_snapshot("rules-1", instrument_id="ETH-PERP")

    store.put(snapshot)
    with pytest.raises(ValueError, match="instrument rule snapshot"):
        store.put(changed)


def test_instrument_latest_snapshot_by_venue_instrument_uses_captured_at() -> None:
    store = InMemoryVenueInstrumentRuleSnapshotStore()
    older = _rule_snapshot("rules-1", captured_at=NOW)
    newer = _rule_snapshot("rules-2", captured_at=NOW + timedelta(minutes=1))

    store.put(newer)
    store.put(older)

    assert store.get_latest("venue-1", "BTC-PERP") == newer
