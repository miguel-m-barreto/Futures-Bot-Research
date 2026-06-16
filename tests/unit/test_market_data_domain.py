from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import (
    MarketConnectionId,
    MarketDataSourceId,
    MarketObservationId,
    VenueInstrumentId,
)
from futures_bot.domain.instruments import VenueId
from futures_bot.domain.market_data import (
    AggressorSide,
    IndexPriceObservationPayload,
    MarketDataSourceDescriptor,
    MarketDataSourceKind,
    MarketObservationProvenance,
    MarketTransportKind,
    MarkPriceObservationPayload,
    NormalizedMarketObservation,
    QuoteSemantics,
    TopOfBookObservationPayload,
    TradeObservationPayload,
    VenueInstrumentRef,
    VenueMarketKind,
    build_market_observation_id,
    build_normalized_market_observation,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
HASH = "sha256:" + "a" * 64


def source(  # noqa: PLR0913
    source_id: str = "BINANCE_SPOT_WS_PRIMARY",
    *,
    kind: MarketDataSourceKind = MarketDataSourceKind.DIRECT_VENUE,
    venue: VenueId | None = None,
    provider: str = "binance",
    transport: MarketTransportKind = MarketTransportKind.WEBSOCKET,
    version: str = "v1",
) -> MarketDataSourceDescriptor:
    if venue is None and kind is MarketDataSourceKind.DIRECT_VENUE:
        venue = VenueId(value="BINANCE")
    return MarketDataSourceDescriptor(
        source_id=MarketDataSourceId(source_id),
        source_kind=kind,
        provider=provider,
        transport=transport,
        venue=venue,
        source_version=version,
    )


def instrument(  # noqa: PLR0913
    instrument_id: str = "binance-spot-btcusdt",
    *,
    venue: str = "BINANCE",
    raw_symbol: str = "BTCUSDT",
    logical: str = "BTC/USDT",
    kind: VenueMarketKind = VenueMarketKind.SPOT,
    settlement: str | None = None,
    collateral: str | None = None,
    expiry: datetime | None = None,
    version: str = "2026-01",
) -> VenueInstrumentRef:
    return VenueInstrumentRef(
        venue_instrument_id=VenueInstrumentId(instrument_id),
        venue=VenueId(value=venue),
        raw_symbol=raw_symbol,
        logical_instrument=logical,
        market_kind=kind,
        settlement_asset=settlement,
        collateral_asset=collateral,
        contract_expiry=expiry,
        metadata_version=version,
    )


def provenance(  # noqa: PLR0913
    *,
    event_id: str = "event-1",
    received_at: datetime = NOW,
    monotonic: int = 10,
    sequence: int | None = 1,
    connection_id: str = "conn-1",
    generation: int = 0,
    payload_hash: str = HASH,
) -> MarketObservationProvenance:
    return MarketObservationProvenance(
        source_event_id=event_id,
        source_event_time=received_at + timedelta(seconds=5),
        engine_time=received_at,
        received_at=received_at,
        received_monotonic_ns=monotonic,
        source_sequence=sequence,
        connection_id=MarketConnectionId(connection_id),
        reconnect_generation=generation,
        raw_payload_sha256=payload_hash,
    )


def trade_payload(
    *,
    trade_id: str = "t-1",
    price: Decimal | str = Decimal("43000.10"),
    quantity: Decimal | str = Decimal("0.2500"),
    side: AggressorSide = AggressorSide.BUY,
) -> TradeObservationPayload:
    return TradeObservationPayload(
        trade_id=trade_id,
        price=price,
        quantity=quantity,
        aggressor_side=side,
    )


def observation() -> NormalizedMarketObservation:
    return build_normalized_market_observation(
        source=source(),
        instrument=instrument(),
        provenance=provenance(),
        payload=trade_payload(),
    )


def test_source_descriptor_validation_and_round_trip() -> None:
    with pytest.raises(ValidationError):
        MarketDataSourceDescriptor(
            source_id=MarketDataSourceId("bad-direct"),
            source_kind=MarketDataSourceKind.DIRECT_VENUE,
            provider="binance",
            transport=MarketTransportKind.WEBSOCKET,
            venue=None,
            source_version="v1",
        )

    aggregator = source(
        "COINGECKO_REFERENCE",
        kind=MarketDataSourceKind.AGGREGATOR,
        provider="coingecko",
        transport=MarketTransportKind.REST,
    )
    assert aggregator.venue is None
    assert MarketDataSourceDescriptor.model_validate(aggregator.model_dump()) == aggregator

    for field, value in (
        ("provider", " binance"),
        ("source_version", "v1 "),
        ("provider", "binańce"),
    ):
        payload = aggregator.model_dump()
        payload[field] = value
        with pytest.raises(ValidationError):
            MarketDataSourceDescriptor.model_validate(payload)


def test_venue_instrument_identity_keeps_raw_symbol_and_contract_kind_separate() -> None:
    spot = instrument(raw_symbol="BTCUSDT")
    linear = instrument(
        "binance-linear-btcusdt",
        raw_symbol="BTCUSDT",
        kind=VenueMarketKind.LINEAR_PERPETUAL,
        settlement="USDT",
        collateral="USDT",
    )

    assert spot.raw_symbol == "BTCUSDT"
    assert spot.logical_instrument == linear.logical_instrument
    assert spot.raw_symbol == linear.raw_symbol
    assert spot.venue_instrument_id != linear.venue_instrument_id
    assert spot.market_kind is VenueMarketKind.SPOT
    assert linear.market_kind is VenueMarketKind.LINEAR_PERPETUAL
    assert spot.settlement_asset is None
    assert spot.collateral_asset is None

    inverse = instrument(
        "bybit-inverse-btcusd",
        venue="BYBIT",
        raw_symbol="BTCUSD",
        logical="BTC/USD",
        kind=VenueMarketKind.INVERSE_PERPETUAL,
        settlement="BTC",
        collateral="BTC",
    )
    assert str(inverse.logical_instrument) == "BTC/USD"

    assert VenueInstrumentRef.model_validate(linear.model_dump()) == linear


def test_venue_instrument_rejects_bad_raw_symbol_and_expiry_rules() -> None:
    with pytest.raises(ValidationError):
        instrument(raw_symbol="BTCUSDṮ")
    with pytest.raises(ValidationError):
        instrument(raw_symbol=" BTCUSDT")
    with pytest.raises(ValidationError):
        instrument(kind=VenueMarketKind.DELIVERY_FUTURE)
    with pytest.raises(ValidationError):
        instrument(expiry=NOW)

    delivery = instrument(
        "binance-delivery-btcusd-202612",
        raw_symbol="BTCUSD_261225",
        logical="BTC/USD",
        kind=VenueMarketKind.DELIVERY_FUTURE,
        settlement="BTC",
        collateral="BTC",
        expiry=NOW,
    )
    assert delivery.contract_expiry == NOW


def test_payloads_validate_decimal_boundaries_and_preserve_scale() -> None:
    trade = trade_payload(price=Decimal("1.2300"), quantity=Decimal("0.0100"))
    restored = TradeObservationPayload.model_validate_json(trade.model_dump_json())
    assert str(restored.price) == "1.2300"
    assert str(restored.quantity) == "0.0100"

    book = TopOfBookObservationPayload(
        bid_price=Decimal("10.0"),
        bid_quantity=Decimal("1.0"),
        ask_price=Decimal("10.5"),
        ask_quantity=Decimal("2.0"),
        quote_semantics=QuoteSemantics.CENTRAL_LIMIT_ORDER_BOOK,
    )
    assert book.bid_price <= book.ask_price
    assert MarkPriceObservationPayload(price=Decimal("10.0")).price == Decimal("10.0")
    assert IndexPriceObservationPayload(price=Decimal("10.0")).price == Decimal("10.0")


@pytest.mark.parametrize("bad", [1.1, True, "NaN", "Infinity", "-Infinity", " 1.0"])
def test_payloads_reject_float_bool_non_finite_and_whitespace_decimal(bad: object) -> None:
    with pytest.raises(ValidationError):
        TradeObservationPayload(
            trade_id="t-1",
            price=bad,
            quantity=Decimal("1"),
            aggressor_side=AggressorSide.UNKNOWN,
        )


@pytest.mark.parametrize("price", [Decimal("0"), Decimal("-1")])
def test_payloads_reject_non_positive_price_and_quantity(price: Decimal) -> None:
    with pytest.raises(ValidationError):
        trade_payload(price=price)
    with pytest.raises(ValidationError):
        trade_payload(quantity=price)


def test_top_of_book_rejects_crossed_market_and_bad_discriminator() -> None:
    with pytest.raises(ValidationError):
        TopOfBookObservationPayload(
            bid_price=Decimal("11"),
            bid_quantity=Decimal("1"),
            ask_price=Decimal("10"),
            ask_quantity=Decimal("1"),
            quote_semantics=QuoteSemantics.INDICATIVE,
        )

    payload = trade_payload().model_dump()
    payload["kind"] = "MARK_PRICE"
    with pytest.raises(ValidationError):
        build_normalized_market_observation(
            source=source(),
            instrument=instrument(),
            provenance=provenance(),
            payload=payload,  # type: ignore[arg-type]
        )


def test_observation_id_is_deterministic_and_covers_authority_fields() -> None:
    base_source = source()
    base_instrument = instrument()
    base_provenance = provenance()
    base_payload = trade_payload()
    base_id = build_market_observation_id(
        source=base_source,
        instrument=base_instrument,
        provenance=base_provenance,
        payload=base_payload,
    )

    assert base_id == build_market_observation_id(
        source=base_source,
        instrument=base_instrument,
        provenance=base_provenance,
        payload=base_payload,
    )

    changed_inputs = (
        (source(provider="binance-copy"), base_instrument, base_provenance, base_payload),
        (
            source(transport=MarketTransportKind.FILE),
            base_instrument,
            base_provenance,
            base_payload,
        ),
        (
            source(kind=MarketDataSourceKind.REPLAY, venue=None),
            base_instrument,
            base_provenance,
            base_payload,
        ),
        (
            source(version="v2"),
            base_instrument,
            base_provenance,
            base_payload,
        ),
        (base_source, instrument(raw_symbol="btc_usdt"), base_provenance, base_payload),
        (
            base_source,
            instrument(kind=VenueMarketKind.LINEAR_PERPETUAL, settlement="USDT"),
            base_provenance,
            base_payload,
        ),
        (base_source, base_instrument, provenance(event_id="event-2"), base_payload),
        (base_source, base_instrument, provenance(monotonic=11), base_payload),
        (base_source, base_instrument, provenance(sequence=None), base_payload),
        (base_source, base_instrument, provenance(generation=1), base_payload),
        (base_source, base_instrument, base_provenance, trade_payload(price=Decimal("43001"))),
        (
            base_source,
            base_instrument,
            base_provenance,
            trade_payload(side=AggressorSide.SELL),
        ),
    )
    for changed_source, changed_instrument, changed_provenance, changed_payload in changed_inputs:
        assert build_market_observation_id(
            source=changed_source,
            instrument=changed_instrument,
            provenance=changed_provenance,
            payload=changed_payload,
        ) != base_id


def test_observation_round_trip_rejects_wrong_id_hash_and_nested_tampering() -> None:
    obs = observation()

    assert NormalizedMarketObservation.model_validate(obs.model_dump()) == obs

    bad_id_payload = obs.model_dump()
    bad_id_payload["observation_id"] = {"value": "market-observation:" + "0" * 64}
    with pytest.raises(ValidationError):
        NormalizedMarketObservation.model_validate(bad_id_payload)

    tampered_source = obs.source.model_copy(update={"provider": " binance"})
    with pytest.raises(ValidationError):
        NormalizedMarketObservation.model_validate(
            obs.model_copy(update={"source": tampered_source}).model_dump()
        )

    tampered_payload = obs.payload.model_copy(update={"price": Decimal("-1")})
    with pytest.raises(ValidationError):
        NormalizedMarketObservation.model_validate(
            obs.model_copy(update={"payload": tampered_payload}).model_dump()
        )

    with pytest.raises(ValidationError):
        provenance(payload_hash="sha256:" + "A" * 64)

    with pytest.raises(ValidationError):
        NormalizedMarketObservation(
            observation_id=MarketObservationId("random"),
            source=source(),
            instrument=instrument(),
            provenance=provenance(),
            payload=trade_payload(),
        )


def test_observation_enforces_direct_venue_provenance_consistency() -> None:
    direct_binance = source()
    bybit_instrument = instrument(
        "bybit-spot-btcusdt",
        venue="BYBIT",
        raw_symbol="BTCUSDT",
    )

    with pytest.raises((ValidationError, ValueError)):
        build_normalized_market_observation(
            source=direct_binance,
            instrument=bybit_instrument,
            provenance=provenance(),
            payload=trade_payload(),
        )

    accepted = build_normalized_market_observation(
        source=direct_binance,
        instrument=instrument(),
        provenance=provenance(),
        payload=trade_payload(),
    )
    assert accepted.source.venue == accepted.instrument.venue

    aggregator = MarketDataSourceDescriptor(
        source_id=MarketDataSourceId("AGGREGATOR_REFERENCE"),
        source_kind=MarketDataSourceKind.AGGREGATOR,
        provider="aggregator",
        transport=MarketTransportKind.REST,
        venue=None,
        source_version="v1",
    )
    accepted_aggregator = build_normalized_market_observation(
        source=aggregator,
        instrument=bybit_instrument,
        provenance=provenance(),
        payload=trade_payload(),
    )
    assert accepted_aggregator.source.source_kind is MarketDataSourceKind.AGGREGATOR
