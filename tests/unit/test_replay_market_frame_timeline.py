from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import (
    MarketDataSourceId,
    MarketObservationId,
    ReplayMarketBindingId,
    ReplayMarketFrameProjectionId,
    VenueInstrumentId,
)
from futures_bot.domain.instruments import VenueId
from futures_bot.domain.market_data import (
    MarketDataSourceDescriptor,
    MarketDataSourceKind,
    MarketObservationProvenance,
    MarketTransportKind,
    NormalizedMarketObservation,
    QuoteSemantics,
    VenueInstrumentRef,
    VenueMarketKind,
    build_normalized_market_observation,
)
from futures_bot.domain.replay import (
    ReplayInputBatch,
    ReplayInputKind,
    ReplayInputRecord,
    ReplayInputValidationStatus,
    ReplayInstrumentRef,
    ReplayOrderingPolicy,
    ReplayTimeline,
    ReplayTimelineEvent,
    ReplayTimelineStatus,
)
from futures_bot.domain.replay_market_data import (
    ReplayMarketAdapterDescriptor,
    ReplayMarketDataBinding,
    ReplayMarketFrameProjection,
    ReplayMarketFrameTimeline,
    ReplayMarketPayloadHashPolicy,
    ReplayMarketTimestampPolicy,
    build_replay_market_adapter_authority,
    build_replay_market_binding_authority,
    build_replay_market_connection_id,
    build_replay_market_frame_projection,
    build_replay_market_frame_projection_id,
    build_replay_market_frame_timeline_id,
    build_replay_market_observation_projection,
    build_replay_market_observation_projection_id,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.market_data.frame_builder import build_cross_venue_market_frame
from futures_bot.market_data.replay_adapter import build_replay_market_frame_timeline

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def replay_instrument(
    symbol: str,
    *,
    venue: str,
    market_type: str,
    base: str,
) -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue=venue,
        symbol=symbol,
        market_type=market_type,
        settlement_asset="USDT",
        quote_asset="USDT",
        base_asset=base,
    )


def record(
    record_id: str,
    instrument: ReplayInstrumentRef,
    *,
    kind: ReplayInputKind = ReplayInputKind.TRADE,
    sequence: int,
    price: str = "100",
) -> ReplayInputRecord:
    payload: dict[str, object]
    if kind is ReplayInputKind.OHLCV_BAR:
        payload = {
            "open": Decimal(price),
            "high": Decimal(price),
            "low": Decimal(price),
            "close": Decimal(price),
            "volume": Decimal("1"),
        }
    else:
        payload = {"price": Decimal(price), "quantity": Decimal("1")}
    return ReplayInputRecord(
        record_id=record_id,
        kind=kind,
        instrument=instrument,
        event_time=NOW,
        source_sequence=sequence,
        payload=payload,
    )


def event(rec: ReplayInputRecord, order_index: int) -> ReplayTimelineEvent:
    return ReplayTimelineEvent(
        event_id=f"event-{order_index}",
        batch_id="batch-1",
        input_dataset_id="dataset-1",
        record_id=rec.record_id,
        kind=rec.kind,
        instrument=rec.instrument,
        event_time=rec.event_time,
        source_sequence=rec.source_sequence,
        order_index=order_index,
        content_hash=rec.content_hash,
    )


def batch(records: tuple[ReplayInputRecord, ...]) -> ReplayInputBatch:
    return ReplayInputBatch(
        batch_id="batch-1",
        replay_plan_id="plan-1",
        input_dataset_id="dataset-1",
        temporal_window=TemporalWindow(
            kind=TemporalWindowKind.TEST,
            start_at=datetime(2026, 1, 1, 0, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, 0, tzinfo=UTC),
            window_id="window-1",
        ),
        ordering_policy=ReplayOrderingPolicy.SOURCE_ORDER,
        records=records,
        created_at=NOW,
        validation_status=ReplayInputValidationStatus.VALIDATED,
    )


def timeline(records: tuple[ReplayInputRecord, ...]) -> ReplayTimeline:
    events = tuple(event(rec, index) for index, rec in enumerate(records))
    return ReplayTimeline(
        timeline_id="timeline-1",
        replay_plan_id="plan-1",
        temporal_window=TemporalWindow(
            kind=TemporalWindowKind.TEST,
            start_at=datetime(2026, 1, 1, 0, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, 0, tzinfo=UTC),
            window_id="window-1",
        ),
        ordering_policy=ReplayOrderingPolicy.SOURCE_ORDER,
        input_batch_ids=("batch-1",),
        input_dataset_ids=("dataset-1",),
        events=events,
        created_at=NOW,
        status=ReplayTimelineStatus.VALIDATED,
    )


def binding(  # noqa: PLR0913
    binding_id: str,
    replay_ref: ReplayInstrumentRef,
    *,
    source_id: str,
    venue_instrument_id: str,
    venue: str,
    market_kind: VenueMarketKind,
    logical: str,
) -> ReplayMarketDataBinding:
    return ReplayMarketDataBinding(
        binding_id=ReplayMarketBindingId(binding_id),
        input_dataset_id="dataset-1",
        replay_instrument=replay_ref,
        source=MarketDataSourceDescriptor(
            source_id=MarketDataSourceId(source_id),
            source_kind=MarketDataSourceKind.REPLAY,
            provider="replay-fixture",
            transport=MarketTransportKind.IN_MEMORY,
            venue=VenueId(value=venue),
            source_version="v1",
        ),
        venue_instrument=VenueInstrumentRef(
            venue_instrument_id=VenueInstrumentId(venue_instrument_id),
            venue=VenueId(value=venue),
            raw_symbol=replay_ref.symbol,
            logical_instrument=logical,
            market_kind=market_kind,
            settlement_asset="USDT" if market_kind is not VenueMarketKind.SPOT else None,
            collateral_asset="USDT" if market_kind is not VenueMarketKind.SPOT else None,
            metadata_version="2026-01",
        ),
        quote_semantics=QuoteSemantics.CENTRAL_LIMIT_ORDER_BOOK,
        binding_version="v1",
    )


def descriptor(*, adapter_version: str = "v1") -> ReplayMarketAdapterDescriptor:
    return ReplayMarketAdapterDescriptor(
        adapter_id="adapter",
        adapter_version=adapter_version,
        supported_input_kinds=(
            ReplayInputKind.INDEX_PRICE,
            ReplayInputKind.MARK_PRICE,
            ReplayInputKind.ORDER_BOOK_TOP,
            ReplayInputKind.TRADE,
        ),
        timestamp_policy=ReplayMarketTimestampPolicy.EVENT_TIME_AS_SOURCE_AND_RECEIVED,
        payload_hash_policy=ReplayMarketPayloadHashPolicy.CANONICAL_REPLAY_RECORD,
    )


def fixture_records() -> tuple[
    ReplayInputRecord,
    ReplayInputRecord,
    ReplayInputRecord,
    ReplayInputRecord,
    ReplayInputRecord,
]:
    binance_spot = replay_instrument(
        "BTCUSDT",
        venue="binance",
        market_type="spot",
        base="BTC",
    )
    bybit_linear = replay_instrument(
        "BTCUSDT",
        venue="bybit",
        market_type="linear-perpetual",
        base="BTC",
    )
    binance_linear = replay_instrument(
        "BTCUSDT",
        venue="binance",
        market_type="linear-perpetual",
        base="BTC",
    )
    eth = replay_instrument("ETHUSDT", venue="binance", market_type="spot", base="ETH")
    return (
        record("binance-spot", binance_spot, sequence=0, price="100"),
        record("bybit-linear", bybit_linear, sequence=1, price="101"),
        record("eth-spot", eth, sequence=2, price="200"),
        record("binance-linear", binance_linear, sequence=3, price="102"),
        record("unsupported", binance_spot, kind=ReplayInputKind.OHLCV_BAR, sequence=4),
    )


def fixture_bindings(records: tuple[ReplayInputRecord, ...]) -> tuple[ReplayMarketDataBinding, ...]:
    return (
        binding(
            "binding-binance-spot",
            records[0].instrument,
            source_id="REPLAY_BINANCE_SPOT",
            venue_instrument_id="binance-spot-btcusdt",
            venue="BINANCE",
            market_kind=VenueMarketKind.SPOT,
            logical="BTC/USDT",
        ),
        binding(
            "binding-bybit-linear",
            records[1].instrument,
            source_id="REPLAY_BYBIT_LINEAR",
            venue_instrument_id="bybit-linear-btcusdt",
            venue="BYBIT",
            market_kind=VenueMarketKind.LINEAR_PERPETUAL,
            logical="BTC/USDT",
        ),
        binding(
            "binding-eth-spot",
            records[2].instrument,
            source_id="REPLAY_BINANCE_ETH",
            venue_instrument_id="binance-spot-ethusdt",
            venue="BINANCE",
            market_kind=VenueMarketKind.SPOT,
            logical="ETH/USDT",
        ),
        binding(
            "binding-binance-linear",
            records[3].instrument,
            source_id="REPLAY_BINANCE_LINEAR",
            venue_instrument_id="binance-linear-btcusdt",
            venue="BINANCE",
            market_kind=VenueMarketKind.LINEAR_PERPETUAL,
            logical="BTC/USDT",
        ),
    )


def build_fixture_timeline(
    records: tuple[ReplayInputRecord, ...] | None = None,
    bindings: tuple[ReplayMarketDataBinding, ...] | None = None,
) -> ReplayMarketFrameTimeline:
    records = records or fixture_records()
    return build_replay_market_frame_timeline(
        replay_timeline=timeline(records),
        input_batches=(batch(records),),
        descriptor=descriptor(),
        bindings=bindings or fixture_bindings(records),
    )


def recomputed_timeline_payload(
    projected: ReplayMarketFrameTimeline,
    *,
    replay_timeline_id: str | None = None,
    adapter_authority: object | None = None,
    observation_projections: tuple[object, ...] | None = None,
    frame_projections: tuple[object, ...] | None = None,
) -> dict[str, object]:
    observations = observation_projections or projected.observation_projections
    frames = frame_projections or projected.frame_projections
    timeline_id = replay_timeline_id or projected.replay_timeline_id
    authority = adapter_authority or projected.adapter_authority
    market_timeline_id = build_replay_market_frame_timeline_id(
        replay_timeline_id=timeline_id,
        replay_plan_id=projected.replay_plan_id,
        adapter_authority=authority,  # type: ignore[arg-type]
        observation_projections=observations,  # type: ignore[arg-type]
        frame_projections=frames,  # type: ignore[arg-type]
    )
    payload = projected.model_dump()
    payload["market_timeline_id"] = market_timeline_id
    payload["replay_timeline_id"] = timeline_id
    payload["adapter_authority"] = authority
    payload["observation_projections"] = observations
    payload["frame_projections"] = frames
    return payload


def replace_first_timeline_observation(
    projected: ReplayMarketFrameTimeline,
    observation: NormalizedMarketObservation,
) -> dict[str, object]:
    payload = projected.model_dump()
    first_projection = payload["observation_projections"][0]
    first_projection["observation"] = observation
    first_frame = payload["frame_projections"][0]
    first_frame["frame"]["observations"] = (observation,)
    return payload


def self_verified_replacement_for_first_projection(
    projected: ReplayMarketFrameTimeline,
    changed_binding: ReplayMarketDataBinding,
) -> tuple[object, object]:
    first_projection = projected.observation_projections[0]
    binding_authority = build_replay_market_binding_authority(
        descriptor=first_projection.binding_authority.descriptor,
        binding=changed_binding,
    )
    provenance = MarketObservationProvenance.model_validate(
        first_projection.observation.provenance.model_copy(
            update={
                "connection_id": build_replay_market_connection_id(
                    input_dataset_id=first_projection.input_dataset_id,
                    binding_authority=binding_authority,
                )
            }
        ).model_dump()
    )
    observation = build_normalized_market_observation(
        source=changed_binding.source,
        instrument=changed_binding.venue_instrument,
        provenance=provenance,
        payload=first_projection.observation.payload,
    )
    observation_projection = build_replay_market_observation_projection(
        timeline_id=first_projection.timeline_id,
        event_id=first_projection.event_id,
        event_order_index=first_projection.event_order_index,
        event_time=first_projection.event_time,
        batch_id=first_projection.batch_id,
        input_dataset_id=first_projection.input_dataset_id,
        record_id=first_projection.record_id,
        event_kind=first_projection.event_kind,
        binding_authority=binding_authority,
        observation=observation,
    )
    frame = build_cross_venue_market_frame(
        logical_instrument=observation.instrument.logical_instrument,
        as_of=first_projection.event_time,
        observations=(observation,),
        source_health=(),
    )
    frame_projection = build_replay_market_frame_projection(
        timeline_id=first_projection.timeline_id,
        event_id=first_projection.event_id,
        event_order_index=first_projection.event_order_index,
        event_time=first_projection.event_time,
        triggering_observation_projection_id=observation_projection.projection_id,
        triggering_observation_id=observation.observation_id,
        frame=frame,
    )
    return observation_projection, frame_projection


def test_same_timestamp_replay_order_controls_frame_contents_and_skips_unsupported() -> None:
    projected = build_fixture_timeline()

    assert len(projected.observation_projections) == 4
    assert len(projected.frame_projections) == 4
    assert all(frame.frame.source_health == () for frame in projected.frame_projections)

    first_frame = projected.frame_projections[0].frame
    second_frame = projected.frame_projections[1].frame
    eth_frame = projected.frame_projections[2].frame
    fourth_frame = projected.frame_projections[3].frame

    assert len(first_frame.observations) == 1
    assert len(second_frame.observations) == 2
    assert {str(obs.instrument.venue_instrument_id) for obs in second_frame.observations} == {
        "binance-spot-btcusdt",
        "bybit-linear-btcusdt",
    }
    assert str(eth_frame.logical_instrument) == "ETH/USDT"
    assert len(eth_frame.observations) == 1
    assert len(fourth_frame.observations) == 3
    assert {obs.instrument.market_kind for obs in fourth_frame.observations} == {
        VenueMarketKind.SPOT,
        VenueMarketKind.LINEAR_PERPETUAL,
    }


def test_timeline_projection_is_deterministic_and_input_order_independent() -> None:
    records = fixture_records()
    bindings = fixture_bindings(records)
    projected = build_fixture_timeline(records, bindings)
    reordered = build_replay_market_frame_timeline(
        replay_timeline=timeline(records),
        input_batches=(batch(records),),
        descriptor=descriptor(),
        bindings=tuple(reversed(bindings)),
    )

    assert projected == reordered
    assert ReplayMarketFrameTimeline.model_validate(projected.model_dump()) == projected
    assert projected.market_timeline_id == reordered.market_timeline_id


def test_changing_payload_changes_observation_frame_and_timeline_ids() -> None:
    records = fixture_records()
    changed_records = (
        record("binance-spot", records[0].instrument, sequence=0, price="999"),
        *records[1:],
    )
    original = build_fixture_timeline(records)
    changed = build_fixture_timeline(changed_records, fixture_bindings(changed_records))

    assert original.observation_projections[0].projection_id != (
        changed.observation_projections[0].projection_id
    )
    assert original.frame_projections[0].frame.frame_id != (
        changed.frame_projections[0].frame.frame_id
    )
    assert original.market_timeline_id != changed.market_timeline_id


def test_missing_or_ambiguous_binding_rejected() -> None:
    records = fixture_records()
    bindings = fixture_bindings(records)
    with pytest.raises(ValueError):
        build_fixture_timeline(records, bindings[1:])
    with pytest.raises(ValueError):
        build_fixture_timeline(
            records,
            (
                *bindings,
                binding(
                    "conflicting",
                    records[0].instrument,
                    source_id="REPLAY_CONFLICT",
                    venue_instrument_id="conflict",
                    venue="BINANCE",
                    market_kind=VenueMarketKind.SPOT,
                    logical="BTC/USDT",
                ),
            ),
        )


def test_timeline_model_copy_tampering_rejected() -> None:
    projected = build_fixture_timeline()
    tampered_frame = projected.frame_projections[0].model_copy(
        update={"event_order_index": 99}
    )
    with pytest.raises(ValidationError):
        ReplayMarketFrameTimeline.model_validate(
            projected.model_copy(
                update={"frame_projections": (tampered_frame, *projected.frame_projections[1:])}
            ).model_dump()
        )


def test_timeline_rejects_top_level_lineage_change_with_recomputed_id() -> None:
    projected = build_fixture_timeline()

    with pytest.raises((ValidationError, ValueError)):
        ReplayMarketFrameTimeline.model_validate(
            recomputed_timeline_payload(projected, replay_timeline_id="timeline-other")
        )


def test_timeline_rejects_projection_lineage_change_with_recomputed_ids() -> None:
    projected = build_fixture_timeline()
    first_observation = projected.observation_projections[0]
    first_frame = projected.frame_projections[0]
    tampered_observation = build_replay_market_observation_projection(
        timeline_id="timeline-other",
        event_id=first_observation.event_id,
        event_order_index=first_observation.event_order_index,
        event_time=first_observation.event_time,
        batch_id=first_observation.batch_id,
        input_dataset_id=first_observation.input_dataset_id,
        record_id=first_observation.record_id,
        event_kind=first_observation.event_kind,
        binding_authority=first_observation.binding_authority,
        observation=first_observation.observation,
    )
    tampered_frame = build_replay_market_frame_projection(
        timeline_id="timeline-other",
        event_id=first_frame.event_id,
        event_order_index=first_frame.event_order_index,
        event_time=first_frame.event_time,
        triggering_observation_projection_id=first_frame.triggering_observation_projection_id,
        triggering_observation_id=first_frame.triggering_observation_id,
        frame=first_frame.frame,
    )

    with pytest.raises((ValidationError, ValueError)):
        ReplayMarketFrameTimeline.model_validate(
            recomputed_timeline_payload(
                projected,
                observation_projections=(
                    tampered_observation,
                    *projected.observation_projections[1:],
                ),
            )
        )
    with pytest.raises((ValidationError, ValueError)):
        ReplayMarketFrameTimeline.model_validate(
            recomputed_timeline_payload(
                projected,
                frame_projections=(tampered_frame, *projected.frame_projections[1:]),
            )
        )


def test_frame_projection_rejects_unrelated_triggering_observation_with_recomputed_id() -> None:
    projected = build_fixture_timeline()
    first_frame = projected.frame_projections[0]
    unrelated_observation_id = MarketObservationId(value="market-observation:" + "0" * 64)
    with pytest.raises(ValueError):
        build_replay_market_frame_projection_id(
            timeline_id=first_frame.timeline_id,
            event_id=first_frame.event_id,
            event_order_index=first_frame.event_order_index,
            event_time=first_frame.event_time,
            triggering_observation_projection_id=first_frame.triggering_observation_projection_id,
            triggering_observation_id=unrelated_observation_id,
            frame=first_frame.frame,
        )
    payload = first_frame.model_dump()
    payload["projection_id"] = ReplayMarketFrameProjectionId(
        value="replay-market-frame-projection:" + "0" * 64
    )
    payload["triggering_observation_id"] = unrelated_observation_id

    with pytest.raises(ValidationError):
        ReplayMarketFrameProjection.model_validate(payload)

    malformed_payload = first_frame.model_dump()
    malformed_payload["triggering_observation_projection_id"] = "not-a-projection-id"
    with pytest.raises(ValidationError):
        ReplayMarketFrameProjection.model_validate(malformed_payload)


def test_timeline_rejects_triggering_observation_from_different_projection() -> None:
    projected = build_fixture_timeline()
    first_observation = projected.observation_projections[0]
    second_observation = projected.observation_projections[1]
    first_frame = projected.frame_projections[0]
    second_frame = projected.frame_projections[1]
    wrong_trigger = build_replay_market_frame_projection(
        timeline_id=first_frame.timeline_id,
        event_id=first_frame.event_id,
        event_order_index=first_frame.event_order_index,
        event_time=first_frame.event_time,
        triggering_observation_projection_id=first_observation.projection_id,
        triggering_observation_id=second_observation.observation.observation_id,
        frame=second_frame.frame,
    )

    with pytest.raises(ValueError):
        recomputed_timeline_payload(
            projected,
            frame_projections=(wrong_trigger, *projected.frame_projections[1:]),
        )


def test_timeline_reconstructs_cumulative_frames_and_rejects_leakage_or_omission() -> None:
    projected = build_fixture_timeline()
    first_observation = projected.observation_projections[0]
    second_observation = projected.observation_projections[1]
    first_frame = projected.frame_projections[0]
    second_frame = projected.frame_projections[1]
    leaky_first_frame = build_replay_market_frame_projection(
        timeline_id=first_frame.timeline_id,
        event_id=first_frame.event_id,
        event_order_index=first_frame.event_order_index,
        event_time=first_frame.event_time,
        triggering_observation_projection_id=first_observation.projection_id,
        triggering_observation_id=first_observation.observation.observation_id,
        frame=second_frame.frame,
    )
    omitted_prior_frame = build_cross_venue_market_frame(
        logical_instrument=second_observation.observation.instrument.logical_instrument,
        as_of=second_observation.event_time,
        observations=(second_observation.observation,),
        source_health=(),
    )
    omitted_prior_projection = build_replay_market_frame_projection(
        timeline_id=second_frame.timeline_id,
        event_id=second_frame.event_id,
        event_order_index=second_frame.event_order_index,
        event_time=second_frame.event_time,
        triggering_observation_projection_id=second_observation.projection_id,
        triggering_observation_id=second_observation.observation.observation_id,
        frame=omitted_prior_frame,
    )

    with pytest.raises((ValidationError, ValueError)):
        ReplayMarketFrameTimeline.model_validate(
            recomputed_timeline_payload(
                projected,
                frame_projections=(leaky_first_frame, *projected.frame_projections[1:]),
            )
        )
    with pytest.raises((ValidationError, ValueError)):
        ReplayMarketFrameTimeline.model_validate(
            recomputed_timeline_payload(
                projected,
                frame_projections=(
                    projected.frame_projections[0],
                    omitted_prior_projection,
                    *projected.frame_projections[2:],
                ),
            )
        )


def test_timeline_rejects_nested_fabricated_replay_provenance() -> None:
    projected = build_fixture_timeline()
    first_projection = projected.observation_projections[0]
    bad_provenance = MarketObservationProvenance.model_validate(
        first_projection.observation.provenance.model_copy(
            update={"engine_time": datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC)}
        ).model_dump()
    )
    bad_observation = build_normalized_market_observation(
        source=first_projection.observation.source,
        instrument=first_projection.observation.instrument,
        provenance=bad_provenance,
        payload=first_projection.observation.payload,
    )

    with pytest.raises(ValueError):
        build_replay_market_observation_projection_id(
            timeline_id=first_projection.timeline_id,
            event_id=first_projection.event_id,
            event_order_index=first_projection.event_order_index,
            event_time=first_projection.event_time,
            batch_id=first_projection.batch_id,
            input_dataset_id=first_projection.input_dataset_id,
            record_id=first_projection.record_id,
            event_kind=first_projection.event_kind,
            binding_authority=first_projection.binding_authority,
            observation=bad_observation,
        )
    with pytest.raises(ValidationError):
        ReplayMarketFrameTimeline.model_validate(
            replace_first_timeline_observation(projected, bad_observation)
        )


def test_timeline_rejects_nested_live_source_impersonation() -> None:
    projected = build_fixture_timeline()
    first_projection = projected.observation_projections[0]
    live_source = first_projection.observation.source.model_copy(
        update={"source_kind": MarketDataSourceKind.DIRECT_VENUE}
    )
    bad_observation = build_normalized_market_observation(
        source=live_source,
        instrument=first_projection.observation.instrument,
        provenance=first_projection.observation.provenance,
        payload=first_projection.observation.payload,
    )

    with pytest.raises(ValueError):
        build_replay_market_observation_projection_id(
            timeline_id=first_projection.timeline_id,
            event_id=first_projection.event_id,
            event_order_index=first_projection.event_order_index,
            event_time=first_projection.event_time,
            batch_id=first_projection.batch_id,
            input_dataset_id=first_projection.input_dataset_id,
            record_id=first_projection.record_id,
            event_kind=first_projection.event_kind,
            binding_authority=first_projection.binding_authority,
            observation=bad_observation,
        )
    with pytest.raises(ValidationError):
        ReplayMarketFrameTimeline.model_validate(
            replace_first_timeline_observation(projected, bad_observation)
        )


def test_timeline_rejects_projection_binding_absent_or_changed_in_authority() -> None:
    projected = build_fixture_timeline()
    records = fixture_records()
    bindings = fixture_bindings(records)
    missing_first_authority = build_replay_market_adapter_authority(
        descriptor=descriptor(),
        bindings=bindings[1:],
    )
    payload = projected.model_dump()
    payload["adapter_authority"] = missing_first_authority

    with pytest.raises((ValidationError, ValueError)):
        build_replay_market_frame_timeline_id(
            replay_timeline_id=projected.replay_timeline_id,
            replay_plan_id=projected.replay_plan_id,
            adapter_authority=missing_first_authority,
            observation_projections=projected.observation_projections,
            frame_projections=projected.frame_projections,
        )
    with pytest.raises(ValidationError):
        ReplayMarketFrameTimeline.model_validate(payload)

    changed_binding = projected.observation_projections[0].binding_authority.binding.model_copy(
        update={"binding_version": "v2"}
    )
    changed_projection_payload = projected.model_dump()
    changed_projection_payload["observation_projections"][0]["binding_authority"][
        "binding"
    ] = changed_binding
    with pytest.raises(ValidationError):
        ReplayMarketFrameTimeline.model_validate(changed_projection_payload)


def test_timeline_rejects_self_verified_projection_binding_not_in_authority() -> None:
    projected = build_fixture_timeline()
    first_binding = projected.observation_projections[0].binding_authority.binding

    changed_source = first_binding.source.model_copy(update={"provider": "changed-provider"})
    changed_same_id_and_key = first_binding.model_copy(update={"source": changed_source})
    changed_projection, changed_frame = self_verified_replacement_for_first_projection(
        projected,
        changed_same_id_and_key,
    )

    with pytest.raises((ValidationError, ValueError)):
        ReplayMarketFrameTimeline.model_validate(
            recomputed_timeline_payload(
                projected,
                observation_projections=(
                    changed_projection,
                    *projected.observation_projections[1:],
                ),
                frame_projections=(changed_frame, *projected.frame_projections[1:]),
            )
        )

    changed_binding_id = first_binding.model_copy(
        update={"binding_id": ReplayMarketBindingId("binding-forged")}
    )
    absent_projection, absent_frame = self_verified_replacement_for_first_projection(
        projected,
        changed_binding_id,
    )

    with pytest.raises((ValidationError, ValueError)):
        ReplayMarketFrameTimeline.model_validate(
            recomputed_timeline_payload(
                projected,
                observation_projections=(
                    absent_projection,
                    *projected.observation_projections[1:],
                ),
                frame_projections=(absent_frame, *projected.frame_projections[1:]),
            )
        )


def test_timeline_rejects_projection_descriptor_different_from_authority() -> None:
    projected = build_fixture_timeline()
    payload = projected.model_dump()
    payload["observation_projections"][0]["binding_authority"]["descriptor"] = descriptor(
        adapter_version="v2"
    )

    with pytest.raises(ValidationError):
        ReplayMarketFrameTimeline.model_validate(payload)


def test_changed_valid_adapter_authority_creates_distinct_timeline() -> None:
    records = fixture_records()
    original = build_fixture_timeline(records)
    bindings = fixture_bindings(records)
    changed_source = bindings[0].source.model_copy(update={"provider": "changed-provider"})
    changed_bindings = (
        bindings[0].model_copy(update={"source": changed_source}),
        *bindings[1:],
    )
    changed = build_fixture_timeline(records, changed_bindings)

    assert changed == ReplayMarketFrameTimeline.model_validate(changed.model_dump())
    assert changed.adapter_authority.adapter_fingerprint != (
        original.adapter_authority.adapter_fingerprint
    )
    assert changed.observation_projections[0].binding_authority.binding_authority_fingerprint != (
        original.observation_projections[0].binding_authority.binding_authority_fingerprint
    )
    assert changed.observation_projections[0].projection_id != (
        original.observation_projections[0].projection_id
    )
    assert changed.market_timeline_id != original.market_timeline_id
