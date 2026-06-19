from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from futures_bot.domain.assets import AssetSymbol
from futures_bot.domain.ids import (
    MarketConnectionId,
    MarketDataSourceId,
    VenueInstrumentId,
)
from futures_bot.domain.instruments import InstrumentSymbol, VenueId
from futures_bot.domain.market_data import (
    AggressorSide,
    CrossVenueMarketFrame,
    IndexPriceObservationPayload,
    MarketDataSourceDescriptor,
    MarketDataSourceKind,
    MarketObservationKind,
    MarketObservationPayload,
    MarketObservationProvenance,
    MarketSourceHealthState,
    MarketSourceIssueKind,
    MarketTransportKind,
    MarkPriceObservationPayload,
    NormalizedMarketObservation,
    QuoteSemantics,
    TopOfBookObservationPayload,
    TradeObservationPayload,
    VenueInstrumentRef,
    VenueMarketKind,
    build_market_source_health_snapshot,
    build_normalized_market_observation,
)
from futures_bot.market_data.frame_builder import build_cross_venue_market_frame

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
HASH = "sha256:" + "e" * 64


def build_market_evidence_fixture_frame(
    *,
    trade_price: str = "100.00",
    include_source_health: bool = True,
) -> CrossVenueMarketFrame:
    binance_spot_source = _source("BINANCE_SPOT_WS", "BINANCE", "binance")
    binance_perp_source = _source("BINANCE_PERP_WS", "BINANCE", "binance")
    bybit_perp_source = _source("BYBIT_PERP_WS", "BYBIT", "bybit")
    binance_spot = _instrument(
        "binance-spot-btcusdt",
        venue="BINANCE",
        raw_symbol="BTCUSDT",
        kind=VenueMarketKind.SPOT,
    )
    binance_perp = _instrument(
        "binance-linear-btcusdt",
        venue="BINANCE",
        raw_symbol="BTCUSDT-PERP",
        kind=VenueMarketKind.LINEAR_PERPETUAL,
    )
    bybit_perp = _instrument(
        "bybit-linear-btcusdt",
        venue="BYBIT",
        raw_symbol="BTCUSDT",
        kind=VenueMarketKind.LINEAR_PERPETUAL,
    )
    observations = (
        _observation(
            binance_spot_source,
            binance_spot,
            event_id="binance-spot-trade",
            sequence=1,
            payload=TradeObservationPayload(
                trade_id="binance-spot-trade",
                price=Decimal(trade_price),
                quantity=Decimal("0.50"),
                aggressor_side=AggressorSide.BUY,
            ),
        ),
        _observation(
            binance_spot_source,
            binance_spot,
            event_id="binance-spot-top",
            sequence=2,
            payload=TopOfBookObservationPayload(
                bid_price=Decimal("99.90"),
                bid_quantity=Decimal("1.25"),
                ask_price=Decimal("100.10"),
                ask_quantity=Decimal("1.10"),
                quote_semantics=QuoteSemantics.CENTRAL_LIMIT_ORDER_BOOK,
            ),
        ),
        _observation(
            binance_perp_source,
            binance_perp,
            event_id="binance-perp-mark",
            sequence=3,
            payload=MarkPriceObservationPayload(price=Decimal("100.05")),
        ),
        _observation(
            binance_perp_source,
            binance_perp,
            event_id="binance-perp-index",
            sequence=4,
            payload=IndexPriceObservationPayload(price=Decimal("100.02")),
        ),
        _observation(
            bybit_perp_source,
            bybit_perp,
            event_id="bybit-perp-top",
            sequence=5,
            payload=TopOfBookObservationPayload(
                bid_price=Decimal("99.88"),
                bid_quantity=Decimal("0.80"),
                ask_price=Decimal("100.12"),
                ask_quantity=Decimal("0.75"),
                quote_semantics=QuoteSemantics.CENTRAL_LIMIT_ORDER_BOOK,
            ),
        ),
    )
    health = ()
    if include_source_health:
        health = (
            build_market_source_health_snapshot(
                source=binance_spot_source,
                instrument=None,
                observation_kind=None,
                state=MarketSourceHealthState.LIVE,
                evaluated_at=NOW,
                last_received_at=NOW - timedelta(seconds=1),
                last_source_event_time=NOW - timedelta(seconds=1),
                last_sequence=10,
                reconnect_generation=0,
                consecutive_failures=0,
                issues=(),
            ),
            build_market_source_health_snapshot(
                source=binance_perp_source,
                instrument=binance_perp,
                observation_kind=MarketObservationKind.MARK_PRICE,
                state=MarketSourceHealthState.DEGRADED,
                evaluated_at=NOW,
                last_received_at=NOW - timedelta(seconds=2),
                last_source_event_time=NOW - timedelta(seconds=2),
                last_sequence=20,
                reconnect_generation=1,
                consecutive_failures=2,
                issues=(MarketSourceIssueKind.RATE_LIMITED,),
            ),
            build_market_source_health_snapshot(
                source=bybit_perp_source,
                instrument=bybit_perp,
                observation_kind=None,
                state=MarketSourceHealthState.STALE,
                evaluated_at=NOW,
                last_received_at=NOW - timedelta(minutes=3),
                last_source_event_time=NOW - timedelta(minutes=3),
                last_sequence=None,
                reconnect_generation=2,
                consecutive_failures=1,
                issues=(MarketSourceIssueKind.STALE_DATA,),
            ),
        )
    return build_cross_venue_market_frame(
        logical_instrument="BTC/USDT",
        as_of=NOW,
        observations=observations,
        source_health=health,
    )


def _source(
    source_id: str,
    venue: str,
    provider: str,
) -> MarketDataSourceDescriptor:
    return MarketDataSourceDescriptor(
        source_id=MarketDataSourceId.from_str(source_id),
        source_kind=MarketDataSourceKind.DIRECT_VENUE,
        provider=provider,
        transport=MarketTransportKind.WEBSOCKET,
        venue=VenueId(value=venue),
        source_version="v1",
    )


def _instrument(
    instrument_id: str,
    *,
    venue: str,
    raw_symbol: str,
    kind: VenueMarketKind,
) -> VenueInstrumentRef:
    return VenueInstrumentRef(
        venue_instrument_id=VenueInstrumentId.from_str(instrument_id),
        venue=VenueId(value=venue),
        raw_symbol=raw_symbol,
        logical_instrument=InstrumentSymbol("BTC/USDT"),
        market_kind=kind,
        settlement_asset=None if kind is VenueMarketKind.SPOT else AssetSymbol("USDT"),
        collateral_asset=None if kind is VenueMarketKind.SPOT else AssetSymbol("USDT"),
        metadata_version="2026-01",
    )


def _observation(
    source: MarketDataSourceDescriptor,
    instrument: VenueInstrumentRef,
    *,
    event_id: str,
    sequence: int,
    payload: MarketObservationPayload,
) -> NormalizedMarketObservation:
    return build_normalized_market_observation(
        source=source,
        instrument=instrument,
        provenance=MarketObservationProvenance(
            source_event_id=event_id,
            received_at=NOW - timedelta(seconds=10 - sequence),
            received_monotonic_ns=sequence,
            source_sequence=sequence,
            connection_id=MarketConnectionId.from_str(f"{source.source_id}-conn"),
            reconnect_generation=0,
            raw_payload_sha256=HASH,
        ),
        payload=payload,
    )
