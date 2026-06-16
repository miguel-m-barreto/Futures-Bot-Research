from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from futures_bot.domain.ids import (
    MarketConnectionId,
    MarketDataSourceId,
    VenueInstrumentId,
)
from futures_bot.domain.instruments import VenueId
from futures_bot.domain.market_data import (
    AggressorSide,
    MarketDataSourceDescriptor,
    MarketDataSourceKind,
    MarketObservationProvenance,
    MarketSourceHealthSnapshot,
    MarketSourceHealthState,
    MarketSourceIssueKind,
    MarketTransportKind,
    NormalizedMarketObservation,
    TradeObservationPayload,
    VenueInstrumentRef,
    VenueMarketKind,
    build_market_source_health_snapshot,
    build_normalized_market_observation,
)
from futures_bot.market_data.frame_builder import build_cross_venue_market_frame

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
HASH = "sha256:" + "c" * 64


def source(
    source_id: str,
    *,
    venue: str = "BINANCE",
    provider: str = "binance",
    kind: MarketDataSourceKind = MarketDataSourceKind.DIRECT_VENUE,
) -> MarketDataSourceDescriptor:
    return MarketDataSourceDescriptor(
        source_id=MarketDataSourceId(source_id),
        source_kind=kind,
        provider=provider,
        transport=MarketTransportKind.WEBSOCKET,
        venue=None if kind is not MarketDataSourceKind.DIRECT_VENUE else VenueId(value=venue),
        source_version="v1",
    )


def instrument(
    instrument_id: str,
    *,
    venue: str = "BINANCE",
    raw_symbol: str = "BTCUSDT",
    logical: str = "BTC/USDT",
    kind: VenueMarketKind = VenueMarketKind.SPOT,
) -> VenueInstrumentRef:
    return VenueInstrumentRef(
        venue_instrument_id=VenueInstrumentId(instrument_id),
        venue=VenueId(value=venue),
        raw_symbol=raw_symbol,
        logical_instrument=logical,
        market_kind=kind,
        settlement_asset="USDT" if kind is not VenueMarketKind.SPOT else None,
        collateral_asset="USDT" if kind is not VenueMarketKind.SPOT else None,
        metadata_version="2026-01",
    )


def observation(  # noqa: PLR0913
    src: MarketDataSourceDescriptor,
    inst: VenueInstrumentRef,
    *,
    event_id: str,
    received_at: datetime = NOW,
    monotonic: int = 1,
    sequence: int | None = 1,
    price: str = "43000",
    connection_id: str | None = None,
    reconnect_generation: int = 0,
) -> NormalizedMarketObservation:
    return build_normalized_market_observation(
        source=src,
        instrument=inst,
        provenance=MarketObservationProvenance(
            source_event_id=event_id,
            received_at=received_at,
            received_monotonic_ns=monotonic,
            source_sequence=sequence,
            connection_id=MarketConnectionId(
                connection_id if connection_id is not None else f"{src.source_id}-conn"
            ),
            reconnect_generation=reconnect_generation,
            raw_payload_sha256=HASH,
        ),
        payload=TradeObservationPayload(
            trade_id=event_id,
            price=Decimal(price),
            quantity=Decimal("0.1"),
            aggressor_side=AggressorSide.UNKNOWN,
        ),
    )


def health(  # noqa: PLR0913
    src: MarketDataSourceDescriptor,
    inst: VenueInstrumentRef | None,
    *,
    state: MarketSourceHealthState = MarketSourceHealthState.LIVE,
    evaluated_at: datetime = NOW,
    last_received_at: datetime | None = NOW,
    issues: tuple[MarketSourceIssueKind, ...] = (),
) -> MarketSourceHealthSnapshot:
    return build_market_source_health_snapshot(
        source=src,
        instrument=inst,
        observation_kind=None,
        state=state,
        evaluated_at=evaluated_at,
        last_received_at=last_received_at,
        last_source_event_time=last_received_at,
        last_sequence=1 if last_received_at is not None else None,
        reconnect_generation=0,
        consecutive_failures=0,
        issues=issues,
    )


def test_builder_is_input_order_independent_and_selects_latest_per_stream() -> None:
    src = source("BINANCE_SPOT_WS_PRIMARY")
    inst = instrument("binance-spot-btcusdt")
    older = observation(
        src,
        inst,
        event_id="older",
        received_at=NOW - timedelta(seconds=1),
        monotonic=1,
        sequence=1,
        price="43000",
    )
    newer = observation(
        src,
        inst,
        event_id="newer",
        received_at=NOW,
        monotonic=2,
        sequence=2,
        price="43001",
    )
    frame_a = build_cross_venue_market_frame(
        logical_instrument="BTCUSDT",
        as_of=NOW,
        observations=(older, newer),
        source_health=(),
    )
    frame_b = build_cross_venue_market_frame(
        logical_instrument={"value": "BTC/USDT"},
        as_of=NOW,
        observations=(newer, older),
        source_health=(),
    )

    assert frame_a == frame_b
    assert frame_a.observations == (newer,)


def test_sequence_orders_same_session_even_when_lower_sequence_arrives_later() -> None:
    src = source("BINANCE_SPOT_WS_PRIMARY")
    inst = instrument("binance-spot-btcusdt")
    sequence_10 = observation(
        src,
        inst,
        event_id="seq-10",
        received_at=NOW,
        monotonic=10,
        sequence=10,
        price="43010",
        connection_id="shared-session",
    )
    sequence_9_later_arrival = observation(
        src,
        inst,
        event_id="seq-9",
        received_at=NOW + timedelta(seconds=1),
        monotonic=11,
        sequence=9,
        price="43009",
        connection_id="shared-session",
    )

    frame = build_cross_venue_market_frame(
        logical_instrument="BTC/USDT",
        as_of=NOW + timedelta(seconds=1),
        observations=(sequence_9_later_arrival, sequence_10),
        source_health=(),
    )

    assert frame.observations == (sequence_10,)


def test_equal_wall_clock_across_connections_is_ambiguous_not_monotonic_ordered() -> None:
    src = source("BINANCE_SPOT_WS_PRIMARY")
    inst = instrument("binance-spot-btcusdt")

    with pytest.raises(ValueError, match="incomparable sessions"):
        build_cross_venue_market_frame(
            logical_instrument="BTC/USDT",
            as_of=NOW,
            observations=(
                observation(
                    src,
                    inst,
                    event_id="conn-a",
                    received_at=NOW,
                    monotonic=1,
                    sequence=None,
                    price="43000",
                    connection_id="conn-a",
                ),
                observation(
                    src,
                    inst,
                    event_id="conn-b",
                    received_at=NOW,
                    monotonic=2,
                    sequence=None,
                    price="43001",
                    connection_id="conn-b",
                ),
            ),
            source_health=(),
        )


def test_same_session_unsequenced_observations_use_monotonic_ordering() -> None:
    src = source("BINANCE_SPOT_WS_PRIMARY")
    inst = instrument("binance-spot-btcusdt")
    older = observation(
        src,
        inst,
        event_id="older",
        received_at=NOW,
        monotonic=1,
        sequence=None,
        price="43000",
        connection_id="same-session",
    )
    newer = observation(
        src,
        inst,
        event_id="newer",
        received_at=NOW,
        monotonic=2,
        sequence=None,
        price="43001",
        connection_id="same-session",
    )

    frame = build_cross_venue_market_frame(
        logical_instrument="BTC/USDT",
        as_of=NOW,
        observations=(newer, older),
        source_health=(),
    )

    assert frame.observations == (newer,)


def test_exact_duplicate_observations_do_not_create_false_ambiguity() -> None:
    src = source("BINANCE_SPOT_WS_PRIMARY")
    inst = instrument("binance-spot-btcusdt")
    obs = observation(
        src,
        inst,
        event_id="duplicate",
        received_at=NOW,
        monotonic=1,
        sequence=1,
        price="43000",
    )

    frame = build_cross_venue_market_frame(
        logical_instrument="BTC/USDT",
        as_of=NOW,
        observations=(obs, obs),
        source_health=(),
    )

    assert frame.observations == (obs,)


def test_builder_selects_latest_health_per_scope_and_preserves_stale_source() -> None:
    binance = source("BINANCE_SPOT_WS_PRIMARY")
    bybit = source("BYBIT_LINEAR_WS_PRIMARY", venue="BYBIT", provider="bybit")
    spot = instrument("binance-spot-btcusdt")
    linear = instrument(
        "bybit-linear-btcusdt",
        venue="BYBIT",
        kind=VenueMarketKind.LINEAR_PERPETUAL,
    )
    old_health = health(
        binance,
        spot,
        state=MarketSourceHealthState.LIVE,
        evaluated_at=NOW - timedelta(seconds=1),
        last_received_at=NOW - timedelta(seconds=1),
    )
    stale_health = health(
        binance,
        spot,
        state=MarketSourceHealthState.STALE,
        evaluated_at=NOW,
        issues=(MarketSourceIssueKind.STALE_DATA,),
    )
    live_bybit = health(bybit, linear)
    frame = build_cross_venue_market_frame(
        logical_instrument="BTC/USDT",
        as_of=NOW,
        observations=(),
        source_health=(live_bybit, old_health, stale_health),
    )

    assert frame.observations == ()
    assert len(frame.source_health) == 2
    assert {snapshot.state for snapshot in frame.source_health} == {
        MarketSourceHealthState.LIVE,
        MarketSourceHealthState.STALE,
    }
    assert any(snapshot.source.source_id == binance.source_id for snapshot in frame.source_health)
    assert any(snapshot.source.source_id == bybit.source_id for snapshot in frame.source_health)


def test_global_health_and_instrument_id_named_global_do_not_collide() -> None:
    src = source("BINANCE_SPOT_WS_PRIMARY")
    global_named_instrument = instrument("GLOBAL")
    global_health = health(src, None)
    instrument_health = health(src, global_named_instrument)

    frame = build_cross_venue_market_frame(
        logical_instrument="BTC/USDT",
        as_of=NOW,
        observations=(),
        source_health=(global_health, instrument_health),
    )

    assert len(frame.source_health) == 2
    assert {snapshot.instrument for snapshot in frame.source_health} == {
        None,
        global_named_instrument,
    }


def test_builder_rejects_future_information_and_logical_mismatches() -> None:
    src = source("BINANCE_SPOT_WS_PRIMARY")
    btc = instrument("binance-spot-btcusdt")
    eth = instrument("binance-spot-ethusdt", raw_symbol="ETHUSDT", logical="ETH/USDT")

    with pytest.raises(ValueError):
        build_cross_venue_market_frame(
            logical_instrument="BTC/USDT",
            as_of=NOW,
            observations=(
                observation(
                    src,
                    btc,
                    event_id="future",
                    received_at=NOW + timedelta(seconds=1),
                ),
            ),
            source_health=(),
        )

    with pytest.raises(ValueError):
        build_cross_venue_market_frame(
            logical_instrument="BTC/USDT",
            as_of=NOW,
            observations=(observation(src, eth, event_id="eth"),),
            source_health=(),
        )

    with pytest.raises(ValueError):
        build_cross_venue_market_frame(
            logical_instrument="BTC/USDT",
            as_of=NOW,
            observations=(),
            source_health=(health(src, btc, evaluated_at=NOW + timedelta(seconds=1)),),
        )


def test_builder_rejects_descriptor_and_venue_instrument_collisions() -> None:
    src = source("BINANCE_SPOT_WS_PRIMARY", provider="binance")
    conflicting_source = source("BINANCE_SPOT_WS_PRIMARY", provider="other-provider")
    spot = instrument("binance-spot-btcusdt")

    with pytest.raises(ValueError):
        build_cross_venue_market_frame(
            logical_instrument="BTC/USDT",
            as_of=NOW,
            observations=(
                observation(src, spot, event_id="a"),
                observation(conflicting_source, spot, event_id="b"),
            ),
            source_health=(),
        )

    conflicting_instrument = instrument(
        "binance-spot-btcusdt",
        raw_symbol="BTC-USDT",
    )
    with pytest.raises(ValueError):
        build_cross_venue_market_frame(
            logical_instrument="BTC/USDT",
            as_of=NOW,
            observations=(
                observation(src, spot, event_id="a"),
                observation(src, conflicting_instrument, event_id="b"),
            ),
            source_health=(),
        )


def test_builder_rejects_ambiguous_latest_observation_and_health_ties() -> None:
    src = source("BINANCE_SPOT_WS_PRIMARY")
    spot = instrument("binance-spot-btcusdt")

    with pytest.raises(ValueError):
        build_cross_venue_market_frame(
            logical_instrument="BTC/USDT",
            as_of=NOW,
            observations=(
                observation(src, spot, event_id="a", monotonic=1, sequence=1, price="43000"),
                observation(src, spot, event_id="b", monotonic=1, sequence=1, price="43001"),
            ),
            source_health=(),
        )

    with pytest.raises(ValueError):
        build_cross_venue_market_frame(
            logical_instrument="BTC/USDT",
            as_of=NOW,
            observations=(),
            source_health=(
                health(src, spot, state=MarketSourceHealthState.LIVE),
                health(
                    src,
                    spot,
                    state=MarketSourceHealthState.DEGRADED,
                    issues=(MarketSourceIssueKind.CLOCK_SKEW,),
                ),
            ),
        )


def test_frame_id_changes_when_selected_inputs_change() -> None:
    src = source("BINANCE_SPOT_WS_PRIMARY")
    spot = instrument("binance-spot-btcusdt")
    frame_a = build_cross_venue_market_frame(
        logical_instrument="BTC/USDT",
        as_of=NOW,
        observations=(observation(src, spot, event_id="a", price="43000"),),
        source_health=(),
    )
    frame_b = build_cross_venue_market_frame(
        logical_instrument="BTC/USDT",
        as_of=NOW,
        observations=(observation(src, spot, event_id="b", price="43001"),),
        source_health=(),
    )
    frame_c = build_cross_venue_market_frame(
        logical_instrument="BTC/USDT",
        as_of=NOW,
        observations=(observation(src, spot, event_id="a", price="43000"),),
        source_health=(health(src, spot),),
    )

    assert frame_a.frame_id != frame_b.frame_id
    assert frame_a.frame_id != frame_c.frame_id
