from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import (
    MarketConnectionId,
    MarketDataSourceId,
    ReplayMarketBindingId,
    VenueInstrumentId,
)
from futures_bot.domain.instruments import VenueId
from futures_bot.domain.market_data import (
    AggressorSide,
    MarketDataSourceDescriptor,
    MarketDataSourceKind,
    MarketObservationKind,
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
    ReplayTimelineEvent,
)
from futures_bot.domain.replay_market_data import (
    ReplayMarketAdapterDescriptor,
    ReplayMarketDataBinding,
    ReplayMarketObservationProjection,
    ReplayMarketPayloadHashPolicy,
    ReplayMarketTimestampPolicy,
    build_replay_market_binding_authority,
    build_replay_market_connection_id,
    build_replay_market_connection_id_from_authority,
    build_replay_market_observation_projection,
    build_replay_market_observation_projection_id,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.market_data.replay_adapter import (
    project_replay_record_to_market_observation,
    resolve_replay_input_record,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
HASH = "sha256:" + "d" * 64


def replay_instrument(symbol: str = "BTCUSDT") -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol=symbol,
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
        quote_asset="USDT",
        base_asset=symbol[:-4],
    )


def record(  # noqa: PLR0913
    kind: ReplayInputKind = ReplayInputKind.TRADE,
    *,
    record_id: str = "record-1",
    payload: dict[str, object] | None = None,
    event_time: datetime = NOW,
    sequence: int = 1,
    instrument: ReplayInstrumentRef | None = None,
    content_hash: str | None = None,
) -> ReplayInputRecord:
    if payload is None:
        if kind is ReplayInputKind.OHLCV_BAR:
            payload = {
                "open": Decimal("1"),
                "high": Decimal("2"),
                "low": Decimal("1"),
                "close": Decimal("1.5"),
                "volume": Decimal("10"),
            }
        else:
            payload = {"price": Decimal("43000.10"), "quantity": Decimal("0.2500")}
    return ReplayInputRecord(
        record_id=record_id,
        kind=kind,
        instrument=instrument or replay_instrument(),
        event_time=event_time,
        source_sequence=sequence,
        payload=payload,
        content_hash=content_hash,
    )


def batch(
    records: tuple[ReplayInputRecord, ...],
    *,
    batch_id: str = "batch-1",
    dataset_id: str = "dataset-1",
    status: ReplayInputValidationStatus = ReplayInputValidationStatus.VALIDATED,
) -> ReplayInputBatch:
    return ReplayInputBatch(
        batch_id=batch_id,
        replay_plan_id="plan-1",
        input_dataset_id=dataset_id,
        temporal_window=TemporalWindow(
            kind=TemporalWindowKind.TEST,
            start_at=datetime(2026, 1, 1, 0, tzinfo=UTC),
            end_at=datetime(2026, 1, 2, 0, tzinfo=UTC),
            window_id="window-1",
        ),
        ordering_policy=ReplayOrderingPolicy.SOURCE_ORDER,
        records=records,
        created_at=NOW,
        validation_status=status,
    )


def event(  # noqa: PLR0913
    rec: ReplayInputRecord,
    *,
    event_id: str = "event-1",
    batch_id: str = "batch-1",
    dataset_id: str = "dataset-1",
    order_index: int = 0,
    content_hash: str | None = None,
) -> ReplayTimelineEvent:
    return ReplayTimelineEvent(
        event_id=event_id,
        batch_id=batch_id,
        input_dataset_id=dataset_id,
        record_id=rec.record_id,
        kind=rec.kind,
        instrument=rec.instrument,
        event_time=rec.event_time,
        source_sequence=rec.source_sequence,
        order_index=order_index,
        content_hash=content_hash if content_hash is not None else rec.content_hash,
    )


def binding(
    *,
    source_kind: MarketDataSourceKind = MarketDataSourceKind.REPLAY,
) -> ReplayMarketDataBinding:
    return ReplayMarketDataBinding(
        binding_id=ReplayMarketBindingId("binding-1"),
        input_dataset_id="dataset-1",
        replay_instrument=replay_instrument(),
        source=MarketDataSourceDescriptor(
            source_id=MarketDataSourceId("REPLAY_BINANCE"),
            source_kind=source_kind,
            provider="replay-fixture",
            transport=MarketTransportKind.IN_MEMORY,
            venue=VenueId(value="BINANCE"),
            source_version="v1",
        ),
        venue_instrument=VenueInstrumentRef(
            venue_instrument_id=VenueInstrumentId("binance-linear-btcusdt"),
            venue=VenueId(value="BINANCE"),
            raw_symbol="BTCUSDT",
            logical_instrument="BTC/USDT",
            market_kind=VenueMarketKind.LINEAR_PERPETUAL,
            settlement_asset="USDT",
            collateral_asset="USDT",
            metadata_version="2026-01",
        ),
        quote_semantics=QuoteSemantics.CENTRAL_LIMIT_ORDER_BOOK,
        binding_version="v1",
    )


def descriptor(
    hash_policy: ReplayMarketPayloadHashPolicy = (
        ReplayMarketPayloadHashPolicy.CANONICAL_REPLAY_RECORD
    ),
) -> ReplayMarketAdapterDescriptor:
    return ReplayMarketAdapterDescriptor(
        adapter_id="adapter",
        adapter_version="v1",
        supported_input_kinds=(
            ReplayInputKind.INDEX_PRICE,
            ReplayInputKind.MARK_PRICE,
            ReplayInputKind.ORDER_BOOK_TOP,
            ReplayInputKind.TRADE,
        ),
        timestamp_policy=ReplayMarketTimestampPolicy.EVENT_TIME_AS_SOURCE_AND_RECEIVED,
        payload_hash_policy=hash_policy,
    )


def projection_for(
    rec: ReplayInputRecord,
    *,
    desc: ReplayMarketAdapterDescriptor | None = None,
    replay_binding: ReplayMarketDataBinding | None = None,
) -> ReplayMarketObservationProjection:
    b = replay_binding or binding()
    d = desc or descriptor()
    authority = build_replay_market_binding_authority(descriptor=d, binding=b)
    return project_replay_record_to_market_observation(
        timeline_id="timeline-1",
        event=event(rec),
        record=rec,
        binding_authority=authority,
    )


def observation_with(
    projection: ReplayMarketObservationProjection,
    *,
    source_kind: MarketDataSourceKind | None = None,
    provenance: MarketObservationProvenance | None = None,
) -> NormalizedMarketObservation:
    source = projection.observation.source
    if source_kind is not None:
        source = source.model_copy(update={"source_kind": source_kind})
    return build_normalized_market_observation(
        source=source,
        instrument=projection.observation.instrument,
        provenance=provenance or projection.observation.provenance,
        payload=projection.observation.payload,
    )


def assert_projection_rejects_observation(
    projection: ReplayMarketObservationProjection,
    observation: NormalizedMarketObservation,
) -> None:
    with pytest.raises(ValueError):
        build_replay_market_observation_projection_id(
            timeline_id=projection.timeline_id,
            event_id=projection.event_id,
            event_order_index=projection.event_order_index,
            event_time=projection.event_time,
            batch_id=projection.batch_id,
            input_dataset_id=projection.input_dataset_id,
            record_id=projection.record_id,
            event_kind=projection.event_kind,
            binding_authority=projection.binding_authority,
            observation=observation,
        )
    with pytest.raises(ValueError):
        build_replay_market_observation_projection(
            timeline_id=projection.timeline_id,
            event_id=projection.event_id,
            event_order_index=projection.event_order_index,
            event_time=projection.event_time,
            batch_id=projection.batch_id,
            input_dataset_id=projection.input_dataset_id,
            record_id=projection.record_id,
            event_kind=projection.event_kind,
            binding_authority=projection.binding_authority,
            observation=observation,
        )
    with pytest.raises(ValidationError):
        ReplayMarketObservationProjection(
            projection_id=projection.projection_id,
            timeline_id=projection.timeline_id,
            event_id=projection.event_id,
            event_order_index=projection.event_order_index,
            event_time=projection.event_time,
            batch_id=projection.batch_id,
            input_dataset_id=projection.input_dataset_id,
            record_id=projection.record_id,
            event_kind=projection.event_kind,
            binding_authority=projection.binding_authority,
            observation=observation,
        )
    payload = projection.model_dump()
    payload["observation"] = observation
    with pytest.raises(ValidationError):
        ReplayMarketObservationProjection.model_validate(payload)


def assert_projection_rejects_binding(
    projection: ReplayMarketObservationProjection,
    replay_binding: ReplayMarketDataBinding,
) -> None:
    forged_authority = projection.binding_authority.model_dump()
    forged_authority["binding"] = replay_binding
    with pytest.raises((ValidationError, ValueError)):
        build_replay_market_observation_projection_id(
            timeline_id=projection.timeline_id,
            event_id=projection.event_id,
            event_order_index=projection.event_order_index,
            event_time=projection.event_time,
            batch_id=projection.batch_id,
            input_dataset_id=projection.input_dataset_id,
            record_id=projection.record_id,
            event_kind=projection.event_kind,
            binding_authority=forged_authority,  # type: ignore[arg-type]
            observation=projection.observation,
        )
    with pytest.raises((ValidationError, ValueError)):
        build_replay_market_observation_projection(
            timeline_id=projection.timeline_id,
            event_id=projection.event_id,
            event_order_index=projection.event_order_index,
            event_time=projection.event_time,
            batch_id=projection.batch_id,
            input_dataset_id=projection.input_dataset_id,
            record_id=projection.record_id,
            event_kind=projection.event_kind,
            binding_authority=forged_authority,  # type: ignore[arg-type]
            observation=projection.observation,
        )
    payload = projection.model_dump()
    payload["binding_authority"] = forged_authority
    with pytest.raises(ValidationError):
        ReplayMarketObservationProjection.model_validate(payload)


def test_resolve_replay_input_record_accepts_exact_event_record_match() -> None:
    rec = record()

    assert resolve_replay_input_record(event=event(rec), input_batches=(batch((rec,)),)) == rec


@pytest.mark.parametrize(
    "bad_batches",
    [
        (),
        (batch((record(),), batch_id="other"),),
        (batch((record(),), dataset_id="other"),),
        (
            batch(
                (record(),),
                status=ReplayInputValidationStatus.PLANNED,
            ),
        ),
    ],
)
def test_resolve_replay_input_record_rejects_batch_problems(
    bad_batches: tuple[ReplayInputBatch, ...],
) -> None:
    rec = record()
    with pytest.raises((ValidationError, ValueError)):
        resolve_replay_input_record(event=event(rec), input_batches=bad_batches)


def test_resolve_rejects_duplicate_batch_id_and_corrupted_duplicate_record() -> None:
    rec = record()
    with pytest.raises(ValueError):
        resolve_replay_input_record(
            event=event(rec),
            input_batches=(batch((rec,)), batch((rec,))),
        )
    corrupted = batch((rec,)).model_copy(update={"records": (rec, rec)})
    with pytest.raises(ValidationError):
        resolve_replay_input_record(event=event(rec), input_batches=(corrupted,))


@pytest.mark.parametrize(
    "field",
    ["record_id", "kind", "instrument", "event_time", "source_sequence", "content_hash"],
)
def test_resolve_rejects_event_record_mismatch(field: str) -> None:
    rec = record(content_hash=HASH)
    data = event(rec).model_dump()
    if field == "record_id":
        data[field] = "missing"
    elif field == "kind":
        data[field] = ReplayInputKind.MARK_PRICE
    elif field == "instrument":
        data[field] = replay_instrument("ETHUSDT")
    elif field == "event_time":
        data[field] = datetime(2026, 1, 1, 13, tzinfo=UTC)
    elif field == "source_sequence":
        data[field] = 2
    elif field == "content_hash":
        data[field] = "sha256:" + "e" * 64
    with pytest.raises((ValidationError, ValueError)):
        resolve_replay_input_record(
            event=ReplayTimelineEvent.model_validate(data),
            input_batches=(batch((rec,)),),
        )


def test_project_trade_payload_variants_and_deterministic_ids() -> None:
    buy = projection_for(
        record(payload={"price": Decimal("1.2300"), "quantity": Decimal("0.1000"), "side": "buy"})
    )
    sell = projection_for(
        record(payload={"price": Decimal("1"), "quantity": Decimal("2"), "side": "sell"})
    )
    unknown = projection_for(record(payload={"price": Decimal("1"), "quantity": Decimal("2")}))

    assert buy.observation.payload.kind is MarketObservationKind.TRADE
    assert buy.observation.payload.aggressor_side is AggressorSide.BUY
    assert sell.observation.payload.aggressor_side is AggressorSide.SELL
    assert unknown.observation.payload.aggressor_side is AggressorSide.UNKNOWN
    assert str(buy.observation.payload.price) == "1.2300"
    assert str(buy.observation.payload.quantity) == "0.1000"
    assert buy == projection_for(
        record(payload={"price": Decimal("1.2300"), "quantity": Decimal("0.1000"), "side": "buy"})
    )


def test_project_order_book_mark_and_index_payloads() -> None:
    book = projection_for(
        record(
            ReplayInputKind.ORDER_BOOK_TOP,
            payload={
                "bid_price": Decimal("10"),
                "bid_size": Decimal("1.5"),
                "ask_price": Decimal("11"),
                "ask_size": Decimal("2.5"),
            },
        )
    )
    mark = projection_for(record(ReplayInputKind.MARK_PRICE, payload={"price": Decimal("10")}))
    index = projection_for(record(ReplayInputKind.INDEX_PRICE, payload={"price": Decimal("10")}))

    assert book.observation.payload.kind is MarketObservationKind.TOP_OF_BOOK
    assert book.observation.payload.quote_semantics is QuoteSemantics.CENTRAL_LIMIT_ORDER_BOOK
    assert mark.observation.payload.kind is MarketObservationKind.MARK_PRICE
    assert index.observation.payload.kind is MarketObservationKind.INDEX_PRICE


def test_projection_accepts_replay_and_synthetic_provenance_policy() -> None:
    replay_projection = projection_for(record())
    synthetic_projection = projection_for(
        record(),
        replay_binding=binding(source_kind=MarketDataSourceKind.SYNTHETIC),
    )

    for projection in (replay_projection, synthetic_projection):
        provenance = projection.observation.provenance
        assert projection == ReplayMarketObservationProjection.model_validate(
            projection.model_dump()
        )
        assert projection.observation.source.source_kind in {
            MarketDataSourceKind.REPLAY,
            MarketDataSourceKind.SYNTHETIC,
        }
        assert provenance.source_event_time == projection.event_time
        assert provenance.received_at == projection.event_time
        assert provenance.engine_time is None
        assert provenance.received_monotonic_ns == 0
        assert provenance.source_sequence is not None
        assert provenance.reconnect_generation == 0
        assert provenance.connection_id == build_replay_market_connection_id_from_authority(
            input_dataset_id=projection.input_dataset_id,
            binding_authority_fingerprint=(
                projection.binding_authority.binding_authority_fingerprint
            ),
            binding_id=projection.binding_authority.binding.binding_id,
            source_id=projection.observation.source.source_id,
            venue_instrument_id=projection.observation.instrument.venue_instrument_id,
        )


@pytest.mark.parametrize(
    "source_kind",
    [
        MarketDataSourceKind.DIRECT_VENUE,
        MarketDataSourceKind.AGGREGATOR,
        MarketDataSourceKind.REFERENCE,
    ],
)
def test_projection_rejects_non_replay_source_kinds(
    source_kind: MarketDataSourceKind,
) -> None:
    projection = projection_for(record())

    assert_projection_rejects_observation(
        projection,
        observation_with(projection, source_kind=source_kind),
    )


def test_forged_binding_accepted_regression_rejected() -> None:
    projection = projection_for(record())
    mutations = (
        projection.binding_authority.binding.model_copy(
            update={"binding_id": ReplayMarketBindingId("binding-other")}
        ),
        projection.binding_authority.binding.model_copy(
            update={"input_dataset_id": "dataset-other"}
        ),
        projection.binding_authority.binding.model_copy(
            update={
                "source": projection.binding_authority.binding.source.model_copy(
                    update={"provider": "other"}
                )
            }
        ),
        projection.binding_authority.binding.model_copy(
            update={
                "source": projection.binding_authority.binding.source.model_copy(
                    update={"source_version": "v2"}
                )
            }
        ),
        projection.binding_authority.binding.model_copy(
            update={
                "venue_instrument": (
                    projection.binding_authority.binding.venue_instrument.model_copy(
                        update={"venue_instrument_id": VenueInstrumentId("other-instrument")}
                    )
                )
            }
        ),
        projection.binding_authority.binding.model_copy(
            update={
                "venue_instrument": (
                    projection.binding_authority.binding.venue_instrument.model_copy(
                        update={"metadata_version": "2026-02"}
                    )
                )
            }
        ),
    )

    for forged_binding in mutations:
        assert_projection_rejects_binding(projection, forged_binding)


def test_forged_source_accepted_regression_rejected() -> None:
    projection = projection_for(record())

    for update in (
        {"source_id": MarketDataSourceId("REPLAY_FORGED")},
        {"provider": "forged-provider"},
        {"source_version": "v2"},
    ):
        forged_source = projection.observation.source.model_copy(update=update)
        forged_observation = build_normalized_market_observation(
            source=forged_source,
            instrument=projection.observation.instrument,
            provenance=projection.observation.provenance,
            payload=projection.observation.payload,
        )
        assert_projection_rejects_observation(projection, forged_observation)


def test_forged_instrument_projection_accepted_regression_rejected() -> None:
    projection = projection_for(record())

    for update in (
        {"venue_instrument_id": VenueInstrumentId("forged-instrument")},
        {"raw_symbol": "BTC-USDT"},
        {"market_kind": VenueMarketKind.INVERSE_PERPETUAL},
        {"metadata_version": "2026-02"},
    ):
        forged_instrument = projection.observation.instrument.model_copy(update=update)
        forged_observation = build_normalized_market_observation(
            source=projection.observation.source,
            instrument=forged_instrument,
            provenance=projection.observation.provenance,
            payload=projection.observation.payload,
        )
        assert_projection_rejects_observation(projection, forged_observation)


def test_forged_provider_projection_accepted_regression_rejected() -> None:
    projection = projection_for(record())
    forged_source = projection.observation.source.model_copy(update={"provider": "forged"})
    forged_binding = projection.binding_authority.binding.model_copy(
        update={"source": forged_source}
    )
    forged_authority = build_replay_market_binding_authority(
        descriptor=projection.binding_authority.descriptor,
        binding=forged_binding,
    )
    forged_provenance = MarketObservationProvenance.model_validate(
        projection.observation.provenance.model_copy(
            update={
                "connection_id": build_replay_market_connection_id(
                    input_dataset_id=projection.input_dataset_id,
                    binding_authority=forged_authority,
                )
            }
        ).model_dump()
    )
    forged_observation = build_normalized_market_observation(
        source=forged_source,
        instrument=projection.observation.instrument,
        provenance=forged_provenance,
        payload=projection.observation.payload,
    )

    assert_projection_rejects_binding(projection, forged_binding)
    assert_projection_rejects_observation(projection, forged_observation)


def test_changed_matching_binding_authority_is_distinct_valid_projection() -> None:
    projection = projection_for(record())
    changed_source = projection.observation.source.model_copy(
        update={"provider": "changed-provider"}
    )
    changed_binding = projection.binding_authority.binding.model_copy(
        update={"source": changed_source}
    )
    changed_authority = build_replay_market_binding_authority(
        descriptor=projection.binding_authority.descriptor,
        binding=changed_binding,
    )
    changed_provenance = MarketObservationProvenance.model_validate(
        projection.observation.provenance.model_copy(
            update={
                "connection_id": build_replay_market_connection_id(
                    input_dataset_id=projection.input_dataset_id,
                    binding_authority=changed_authority,
                )
            }
        ).model_dump()
    )
    changed_observation = build_normalized_market_observation(
        source=changed_source,
        instrument=projection.observation.instrument,
        provenance=changed_provenance,
        payload=projection.observation.payload,
    )

    changed_projection = build_replay_market_observation_projection(
        timeline_id=projection.timeline_id,
        event_id=projection.event_id,
        event_order_index=projection.event_order_index,
        event_time=projection.event_time,
        batch_id=projection.batch_id,
        input_dataset_id=projection.input_dataset_id,
        record_id=projection.record_id,
        event_kind=projection.event_kind,
        binding_authority=changed_authority,
        observation=changed_observation,
    )

    assert changed_projection == ReplayMarketObservationProjection.model_validate(
        changed_projection.model_dump()
    )
    assert changed_authority.binding_authority_fingerprint != (
        projection.binding_authority.binding_authority_fingerprint
    )
    assert changed_observation.provenance.connection_id != (
        projection.observation.provenance.connection_id
    )
    assert changed_observation.observation_id != projection.observation.observation_id
    assert changed_projection.projection_id != projection.projection_id


def test_projection_rejects_descriptor_that_does_not_support_event_kind() -> None:
    projection = projection_for(record())
    unsupported_descriptor = ReplayMarketAdapterDescriptor(
        adapter_id="adapter",
        adapter_version="v1",
        supported_input_kinds=(ReplayInputKind.MARK_PRICE,),
        timestamp_policy=ReplayMarketTimestampPolicy.EVENT_TIME_AS_SOURCE_AND_RECEIVED,
        payload_hash_policy=ReplayMarketPayloadHashPolicy.CANONICAL_REPLAY_RECORD,
    )
    unsupported_authority = build_replay_market_binding_authority(
        descriptor=unsupported_descriptor,
        binding=projection.binding_authority.binding,
    )

    with pytest.raises(ValueError):
        build_replay_market_observation_projection(
            timeline_id=projection.timeline_id,
            event_id=projection.event_id,
            event_order_index=projection.event_order_index,
            event_time=projection.event_time,
            batch_id=projection.batch_id,
            input_dataset_id=projection.input_dataset_id,
            record_id=projection.record_id,
            event_kind=projection.event_kind,
            binding_authority=unsupported_authority,
            observation=projection.observation,
        )

    payload = projection.model_dump()
    payload["binding_authority"] = unsupported_authority
    with pytest.raises(ValidationError):
        ReplayMarketObservationProjection.model_validate(payload)


@pytest.mark.parametrize(
    "provenance_updates",
    [
        {"engine_time": datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC)},
        {"received_monotonic_ns": 1},
        {"received_monotonic_ns": 999},
        {"reconnect_generation": 1},
        {"reconnect_generation": 5},
        {"source_event_time": datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC)},
        {"received_at": datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC)},
        {"source_sequence": None},
    ],
)
def test_projection_rejects_fabricated_timing_provenance(
    provenance_updates: dict[str, object],
) -> None:
    projection = projection_for(record())
    provenance = MarketObservationProvenance.model_validate(
        projection.observation.provenance.model_copy(update=provenance_updates).model_dump()
    )

    assert_projection_rejects_observation(
        projection,
        observation_with(projection, provenance=provenance),
    )


def test_projection_rejects_non_deterministic_connection_ids() -> None:
    projection = projection_for(record())
    expected = projection.observation.provenance.connection_id
    wrong_connection_ids = (
        MarketConnectionId(value="arbitrary-connection"),
        MarketConnectionId(value="replay-market-connection:" + "0" * 64),
        build_replay_market_connection_id_from_authority(
            input_dataset_id="dataset-other",
            binding_authority_fingerprint=(
                projection.binding_authority.binding_authority_fingerprint
            ),
            binding_id=projection.binding_authority.binding.binding_id,
            source_id=projection.observation.source.source_id,
            venue_instrument_id=projection.observation.instrument.venue_instrument_id,
        ),
        build_replay_market_connection_id_from_authority(
            input_dataset_id=projection.input_dataset_id,
            binding_authority_fingerprint=(
                projection.binding_authority.binding_authority_fingerprint
            ),
            binding_id=ReplayMarketBindingId("binding-other"),
            source_id=projection.observation.source.source_id,
            venue_instrument_id=projection.observation.instrument.venue_instrument_id,
        ),
        build_replay_market_connection_id_from_authority(
            input_dataset_id=projection.input_dataset_id,
            binding_authority_fingerprint=(
                projection.binding_authority.binding_authority_fingerprint
            ),
            binding_id=projection.binding_authority.binding.binding_id,
            source_id=MarketDataSourceId("REPLAY_OTHER"),
            venue_instrument_id=projection.observation.instrument.venue_instrument_id,
        ),
        build_replay_market_connection_id_from_authority(
            input_dataset_id=projection.input_dataset_id,
            binding_authority_fingerprint=(
                projection.binding_authority.binding_authority_fingerprint
            ),
            binding_id=projection.binding_authority.binding.binding_id,
            source_id=projection.observation.source.source_id,
            venue_instrument_id=VenueInstrumentId("other-instrument"),
        ),
        build_replay_market_connection_id_from_authority(
            input_dataset_id=projection.input_dataset_id,
            binding_authority_fingerprint="replay-market-binding-authority:" + "0" * 64,
            binding_id=projection.binding_authority.binding.binding_id,
            source_id=projection.observation.source.source_id,
            venue_instrument_id=projection.observation.instrument.venue_instrument_id,
        ),
    )

    for connection_id in wrong_connection_ids:
        assert connection_id != expected
        provenance = MarketObservationProvenance.model_validate(
            projection.observation.provenance.model_copy(
                update={"connection_id": connection_id}
            ).model_dump()
        )
        assert_projection_rejects_observation(
            projection,
            observation_with(projection, provenance=provenance),
        )


def test_projection_rejects_replay_kind_payload_mismatch() -> None:
    trade = projection_for(record(ReplayInputKind.TRADE))
    book = projection_for(
        record(
            ReplayInputKind.ORDER_BOOK_TOP,
            payload={
                "bid_price": Decimal("10"),
                "bid_size": Decimal("1"),
                "ask_price": Decimal("11"),
                "ask_size": Decimal("1"),
            },
        )
    )
    mark = projection_for(record(ReplayInputKind.MARK_PRICE, payload={"price": Decimal("10")}))
    index = projection_for(record(ReplayInputKind.INDEX_PRICE, payload={"price": Decimal("10")}))
    cases = (
        (ReplayInputKind.TRADE, book),
        (ReplayInputKind.ORDER_BOOK_TOP, trade),
        (ReplayInputKind.MARK_PRICE, index),
        (ReplayInputKind.INDEX_PRICE, mark),
    )

    for event_kind, projection in cases:
        with pytest.raises(ValueError):
            build_replay_market_observation_projection(
                timeline_id=projection.timeline_id,
                event_id=projection.event_id,
                event_order_index=projection.event_order_index,
                event_time=projection.event_time,
                batch_id=projection.batch_id,
                input_dataset_id=projection.input_dataset_id,
                record_id=projection.record_id,
                event_kind=event_kind,
                binding_authority=projection.binding_authority,
                observation=projection.observation,
            )

        payload = projection.model_dump()
        payload["event_kind"] = event_kind
        with pytest.raises(ValidationError):
            ReplayMarketObservationProjection.model_validate(payload)


def test_project_rejects_unknown_side_unsupported_kind_and_float_payload() -> None:
    with pytest.raises(ValidationError):
        record(payload={"price": Decimal("1"), "quantity": Decimal("2"), "side": "hold"})
    with pytest.raises(ValueError):
        projection_for(record(ReplayInputKind.OHLCV_BAR))
    with pytest.raises(ValidationError):
        record(payload={"price": 1.2, "quantity": Decimal("2")})  # type: ignore[dict-item]


def test_payload_hash_policies_and_connection_id() -> None:
    supplied = record(content_hash=HASH)
    desc = descriptor(ReplayMarketPayloadHashPolicy.REQUIRE_SUPPLIED_SHA256)
    projection = projection_for(supplied, desc=desc)

    assert projection.observation.provenance.raw_payload_sha256 == HASH
    assert str(
        build_replay_market_connection_id(
            input_dataset_id="dataset-1",
            binding_authority=projection.binding_authority,
        )
    ).startswith("replay-market-connection:")

    with pytest.raises(ValueError):
        projection_for(record(), desc=desc)
    with pytest.raises(ValueError):
        projection_for(record(content_hash="abc"), desc=desc)
