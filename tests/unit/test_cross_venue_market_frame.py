from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import (
    MarketConnectionId,
    MarketDataSourceId,
    MarketFrameId,
    VenueInstrumentId,
)
from futures_bot.domain.instruments import VenueId
from futures_bot.domain.market_data import (
    AggressorSide,
    CrossVenueMarketFrame,
    MarketDataSourceDescriptor,
    MarketDataSourceKind,
    MarketObservationProvenance,
    MarketSourceHealthState,
    MarketTransportKind,
    NormalizedMarketObservation,
    TradeObservationPayload,
    VenueInstrumentRef,
    VenueMarketKind,
    build_market_frame_id,
    build_market_source_health_snapshot,
    build_normalized_market_observation,
    validate_market_frame_authority_consistency,
)
from futures_bot.market_data.frame_builder import build_cross_venue_market_frame

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
HASH = "sha256:" + "b" * 64


def source(source_id: str, venue: str, provider: str) -> MarketDataSourceDescriptor:
    return MarketDataSourceDescriptor(
        source_id=MarketDataSourceId(source_id),
        source_kind=MarketDataSourceKind.DIRECT_VENUE,
        provider=provider,
        transport=MarketTransportKind.WEBSOCKET,
        venue=VenueId(value=venue),
        source_version="v1",
    )


def instrument(
    instrument_id: str,
    *,
    venue: str,
    kind: VenueMarketKind,
) -> VenueInstrumentRef:
    return VenueInstrumentRef(
        venue_instrument_id=VenueInstrumentId(instrument_id),
        venue=VenueId(value=venue),
        raw_symbol="BTCUSDT",
        logical_instrument="BTC/USDT",
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
    received_at: datetime,
    monotonic: int,
    sequence: int,
    price: str,
) -> NormalizedMarketObservation:
    return build_normalized_market_observation(
        source=src,
        instrument=inst,
        provenance=MarketObservationProvenance(
            source_event_id=event_id,
            received_at=received_at,
            received_monotonic_ns=monotonic,
            source_sequence=sequence,
            connection_id=MarketConnectionId(f"{src.source_id}-conn"),
            reconnect_generation=0,
            raw_payload_sha256=HASH,
        ),
        payload=TradeObservationPayload(
            trade_id=event_id,
            price=Decimal(price),
            quantity=Decimal("0.1"),
            aggressor_side=AggressorSide.UNKNOWN,
        ),
    )


def test_frame_model_verifies_order_uniqueness_no_future_data_and_id() -> None:
    binance_source = source("BINANCE_SPOT_WS_PRIMARY", "BINANCE", "binance")
    bybit_source = source("BYBIT_LINEAR_WS_PRIMARY", "BYBIT", "bybit")
    spot = instrument("binance-spot-btcusdt", venue="BINANCE", kind=VenueMarketKind.SPOT)
    bybit_linear = instrument(
        "bybit-linear-btcusdt",
        venue="BYBIT",
        kind=VenueMarketKind.LINEAR_PERPETUAL,
    )
    bybit_obs = observation(
        bybit_source,
        bybit_linear,
        event_id="bybit-1",
        received_at=NOW,
        monotonic=2,
        sequence=1,
        price="43001",
    )
    spot_obs = observation(
        binance_source,
        spot,
        event_id="spot-1",
        received_at=NOW,
        monotonic=1,
        sequence=1,
        price="43000",
    )
    frame = build_cross_venue_market_frame(
        logical_instrument="BTC/USDT",
        as_of=NOW,
        observations=(bybit_obs, spot_obs),
        source_health=(),
    )

    assert frame.observations == tuple(
        sorted(frame.observations, key=lambda obs: str(obs.source.source_id))
    )
    assert frame.frame_id == build_market_frame_id(
        logical_instrument=frame.logical_instrument,
        as_of=frame.as_of,
        observations=frame.observations,
        source_health=frame.source_health,
    )
    assert CrossVenueMarketFrame.model_validate(frame.model_dump()) == frame

    unsorted_payload = frame.model_dump()
    unsorted_payload["observations"] = tuple(reversed(unsorted_payload["observations"]))
    unsorted_payload["frame_id"] = {"value": str(frame.frame_id)}
    with pytest.raises(ValidationError):
        CrossVenueMarketFrame.model_validate(unsorted_payload)

    future_obs = observation(
        binance_source,
        spot,
        event_id="future",
        received_at=NOW + timedelta(seconds=1),
        monotonic=3,
        sequence=2,
        price="43002",
    )
    future_id = build_market_frame_id(
        logical_instrument=frame.logical_instrument,
        as_of=frame.as_of,
        observations=(future_obs,),
        source_health=(),
    )
    with pytest.raises(ValidationError):
        CrossVenueMarketFrame(
            frame_id=future_id,
            logical_instrument="BTC/USDT",
            as_of=NOW,
            observations=(future_obs,),
            source_health=(),
        )


def test_frame_preserves_spot_and_perpetual_observations_separately() -> None:
    binance_spot_source = source("BINANCE_SPOT_WS_PRIMARY", "BINANCE", "binance")
    binance_perp_source = source("BINANCE_LINEAR_WS_PRIMARY", "BINANCE", "binance")
    bybit_perp_source = source("BYBIT_LINEAR_WS_PRIMARY", "BYBIT", "bybit")
    spot = instrument("binance-spot-btcusdt", venue="BINANCE", kind=VenueMarketKind.SPOT)
    binance_linear = instrument(
        "binance-linear-btcusdt",
        venue="BINANCE",
        kind=VenueMarketKind.LINEAR_PERPETUAL,
    )
    bybit_linear = instrument(
        "bybit-linear-btcusdt",
        venue="BYBIT",
        kind=VenueMarketKind.LINEAR_PERPETUAL,
    )
    observations = (
        observation(
            bybit_perp_source,
            bybit_linear,
            event_id="bybit",
            received_at=NOW,
            monotonic=3,
            sequence=1,
            price="43002",
        ),
        observation(
            binance_perp_source,
            binance_linear,
            event_id="binance-perp",
            received_at=NOW,
            monotonic=2,
            sequence=1,
            price="43001",
        ),
        observation(
            binance_spot_source,
            spot,
            event_id="binance-spot",
            received_at=NOW,
            monotonic=1,
            sequence=1,
            price="43000",
        ),
    )
    frame = build_cross_venue_market_frame(
        logical_instrument="BTCUSDT",
        as_of=NOW,
        observations=observations,
        source_health=(),
    )

    assert len(frame.observations) == 3
    assert {obs.instrument.market_kind for obs in frame.observations} == {
        VenueMarketKind.SPOT,
        VenueMarketKind.LINEAR_PERPETUAL,
    }
    assert {str(obs.instrument.venue_instrument_id) for obs in frame.observations} == {
        "binance-spot-btcusdt",
        "binance-linear-btcusdt",
        "bybit-linear-btcusdt",
    }
    assert not hasattr(frame, "average_price")
    assert not hasattr(frame, "consensus_price")


def test_frame_model_copy_tampering_is_rejected() -> None:
    src = source("BINANCE_SPOT_WS_PRIMARY", "BINANCE", "binance")
    inst = instrument("binance-spot-btcusdt", venue="BINANCE", kind=VenueMarketKind.SPOT)
    obs = observation(
        src,
        inst,
        event_id="spot",
        received_at=NOW,
        monotonic=1,
        sequence=1,
        price="43000",
    )
    health = build_market_source_health_snapshot(
        source=src,
        instrument=inst,
        observation_kind=None,
        state=MarketSourceHealthState.LIVE,
        evaluated_at=NOW,
        last_received_at=NOW,
        last_source_event_time=NOW,
        last_sequence=1,
        reconnect_generation=0,
        consecutive_failures=0,
        issues=(),
    )
    frame = build_cross_venue_market_frame(
        logical_instrument="BTC/USDT",
        as_of=NOW,
        observations=(obs,),
        source_health=(health,),
    )

    tampered = frame.model_copy(
        update={"frame_id": MarketFrameId("market-frame:" + "0" * 64)}
    )
    with pytest.raises(ValidationError):
        CrossVenueMarketFrame.model_validate(tampered.model_dump())


# ---------------------------------------------------------------------------
# Authority collision helpers
# ---------------------------------------------------------------------------

_DUMMY_FRAME_ID = MarketFrameId("market-frame:" + "0" * 64)


def _source_v(
    source_id: str,
    *,
    venue: str = "BINANCE",
    **overrides: object,
) -> MarketDataSourceDescriptor:
    fields: dict[str, object] = {
        "source_id": MarketDataSourceId(source_id),
        "source_kind": MarketDataSourceKind.DIRECT_VENUE,
        "provider": "binance",
        "transport": MarketTransportKind.WEBSOCKET,
        "venue": VenueId(value=venue),
        "source_version": "v1",
    }
    fields.update(overrides)
    return MarketDataSourceDescriptor(**fields)  # type: ignore[arg-type]


def _inst_v(
    inst_id: str,
    *,
    venue: str = "BINANCE",
    raw_symbol: str = "BTCUSDT",
    kind: VenueMarketKind = VenueMarketKind.SPOT,
    metadata_version: str = "2026-01",
) -> VenueInstrumentRef:
    return VenueInstrumentRef(
        venue_instrument_id=VenueInstrumentId(inst_id),
        venue=VenueId(value=venue),
        raw_symbol=raw_symbol,
        logical_instrument="BTC/USDT",
        market_kind=kind,
        settlement_asset="USDT" if kind is not VenueMarketKind.SPOT else None,
        collateral_asset="USDT" if kind is not VenueMarketKind.SPOT else None,
        metadata_version=metadata_version,
    )


def _obs_v(
    src: MarketDataSourceDescriptor,
    inst: VenueInstrumentRef,
    *,
    event_id: str,
) -> NormalizedMarketObservation:
    return build_normalized_market_observation(
        source=src,
        instrument=inst,
        provenance=MarketObservationProvenance(
            source_event_id=event_id,
            received_at=NOW,
            received_monotonic_ns=1,
            source_sequence=1,
            connection_id=MarketConnectionId(f"{src.source_id}-conn"),
            reconnect_generation=0,
            raw_payload_sha256=HASH,
        ),
        payload=TradeObservationPayload(
            trade_id=event_id,
            price=Decimal("43000"),
            quantity=Decimal("0.1"),
            aggressor_side=AggressorSide.UNKNOWN,
        ),
    )


def _assert_all_paths_reject(
    obs_a: NormalizedMarketObservation,
    obs_b: NormalizedMarketObservation,
) -> None:
    """Verify that the collision is rejected through every frame construction path."""
    sorted_obs = tuple(sorted((obs_a, obs_b), key=lambda o: (
        str(o.source.source_id), str(o.instrument.venue_instrument_id), o.payload.kind.value
    )))

    # builder
    with pytest.raises(ValueError):
        build_cross_venue_market_frame(
            logical_instrument="BTC/USDT",
            as_of=NOW,
            observations=sorted_obs,
            source_health=(),
        )

    # build_market_frame_id
    with pytest.raises(ValueError):
        build_market_frame_id(
            logical_instrument="BTC/USDT",
            as_of=NOW,
            observations=sorted_obs,
            source_health=(),
        )

    # direct constructor with dummy frame_id (collision check runs before ID check)
    with pytest.raises(ValidationError):
        CrossVenueMarketFrame(
            frame_id=_DUMMY_FRAME_ID,
            logical_instrument="BTC/USDT",
            as_of=NOW,
            observations=sorted_obs,
            source_health=(),
        )

    # serialized frame bypass: model_validate on a manually assembled frame dict
    frame_dict = {
        "schema_version": 1,
        "frame_id": {"value": str(_DUMMY_FRAME_ID)},
        "logical_instrument": {"value": "BTC/USDT"},
        "as_of": NOW.isoformat(),
        "observations": [obs.model_dump() for obs in sorted_obs],
        "source_health": [],
    }
    with pytest.raises(ValidationError):
        CrossVenueMarketFrame.model_validate(frame_dict)


# ---------------------------------------------------------------------------
# Source descriptor collision tests
# ---------------------------------------------------------------------------


def test_source_descriptor_collision_different_provider_rejected_through_all_paths() -> None:
    src_a = _source_v("SRC-COLL-1", provider="provider-a")
    src_b = _source_v("SRC-COLL-1", provider="provider-b")  # same ID, different provider
    inst_a = _inst_v("INST-A")
    inst_b = _inst_v("INST-B")
    obs_a = _obs_v(src_a, inst_a, event_id="a")
    obs_b = _obs_v(src_b, inst_b, event_id="b")
    _assert_all_paths_reject(obs_a, obs_b)


def test_source_descriptor_collision_different_venue_rejected_through_all_paths() -> None:
    src_a = _source_v("SRC-COLL-2", venue="BINANCE")
    src_b = _source_v("SRC-COLL-2", venue="BYBIT")  # same ID, different venue
    inst_a = _inst_v("INST-C", venue="BINANCE")
    inst_b = _inst_v("INST-D", venue="BYBIT")
    obs_a = _obs_v(src_a, inst_a, event_id="c")
    obs_b = _obs_v(src_b, inst_b, event_id="d")
    _assert_all_paths_reject(obs_a, obs_b)


def test_source_descriptor_collision_different_source_version_rejected_through_all_paths() -> None:
    src_a = _source_v("SRC-COLL-3", **{"source_version": "v1"})
    src_b = _source_v("SRC-COLL-3", **{"source_version": "v2"})  # same ID, different version
    inst_a = _inst_v("INST-E")
    inst_b = _inst_v("INST-F")
    obs_a = _obs_v(src_a, inst_a, event_id="e")
    obs_b = _obs_v(src_b, inst_b, event_id="f")
    _assert_all_paths_reject(obs_a, obs_b)


# ---------------------------------------------------------------------------
# Venue instrument collision tests
# ---------------------------------------------------------------------------


def test_venue_instrument_collision_different_raw_symbol_rejected_through_all_paths() -> None:
    src_a = _source_v("SRC-VI-A1")
    src_b = _source_v("SRC-VI-B1")
    inst_a = _inst_v("INST-COLL-1", raw_symbol="BTCUSDT")
    inst_b = _inst_v("INST-COLL-1", raw_symbol="BTC-USDT")  # same ID, different raw_symbol
    obs_a = _obs_v(src_a, inst_a, event_id="g")
    obs_b = _obs_v(src_b, inst_b, event_id="h")
    _assert_all_paths_reject(obs_a, obs_b)


def test_venue_instrument_collision_different_market_kind_rejected_through_all_paths() -> None:
    src_a = _source_v("SRC-VI-A2")
    src_b = _source_v("SRC-VI-B2")
    inst_a = _inst_v("INST-COLL-2", kind=VenueMarketKind.SPOT)
    # same venue_instrument_id, different market_kind
    inst_b = _inst_v("INST-COLL-2", kind=VenueMarketKind.LINEAR_PERPETUAL)
    obs_a = _obs_v(src_a, inst_a, event_id="i")
    obs_b = _obs_v(src_b, inst_b, event_id="j")
    _assert_all_paths_reject(obs_a, obs_b)


def test_venue_instrument_collision_different_metadata_version_rejected_through_all_paths() -> None:
    src_a = _source_v("SRC-VI-A3")
    src_b = _source_v("SRC-VI-B3")
    inst_a = _inst_v("INST-COLL-3", metadata_version="2026-01")
    inst_b = _inst_v("INST-COLL-3", metadata_version="2026-02")  # same ID, different metadata
    obs_a = _obs_v(src_a, inst_a, event_id="k")
    obs_b = _obs_v(src_b, inst_b, event_id="l")
    _assert_all_paths_reject(obs_a, obs_b)


# ---------------------------------------------------------------------------
# Valid repeated authority data
# ---------------------------------------------------------------------------


def test_frame_accepts_consistent_repeated_authority_data() -> None:
    """Same source_id with identical descriptor, same instrument_id with identical ref."""
    src = _source_v("SRC-SHARED")
    inst_a = _inst_v("INST-SHARED-A", raw_symbol="BTCUSDT")
    inst_b = _inst_v("INST-SHARED-B", raw_symbol="ETHUSDT")
    obs_a = _obs_v(src, inst_a, event_id="m")
    obs_b = _obs_v(src, inst_b, event_id="n")  # same source, different instrument

    # validate_market_frame_authority_consistency must NOT reject consistent refs
    validate_market_frame_authority_consistency(
        observations=(obs_a, obs_b),
        source_health=(),
    )

    frame = build_cross_venue_market_frame(
        logical_instrument="BTC/USDT",
        as_of=NOW,
        observations=(obs_a, obs_b),
        source_health=(),
    )
    assert len(frame.observations) == 2


def test_frame_accepts_exact_duplicate_observations_as_consistent_authority() -> None:
    """Exact duplicate observation objects share source+instrument: no collision."""
    src = _source_v("SRC-DUP")
    inst = _inst_v("INST-DUP")
    obs = _obs_v(src, inst, event_id="dup")

    validate_market_frame_authority_consistency(
        observations=(obs, obs),
        source_health=(),
    )

    frame = build_cross_venue_market_frame(
        logical_instrument="BTC/USDT",
        as_of=NOW,
        observations=(obs, obs),
        source_health=(),
    )
    # builder de-duplicates by stream key
    assert frame.observations == (obs,)
