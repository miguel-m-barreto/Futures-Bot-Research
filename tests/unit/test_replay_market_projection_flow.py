from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal

from futures_bot.decision.replay_adapter import ReplayDecisionStackHandler
from futures_bot.domain.ids import MarketDataSourceId, ReplayMarketBindingId, VenueInstrumentId
from futures_bot.domain.instruments import VenueId
from futures_bot.domain.market_data import (
    MarketDataSourceDescriptor,
    MarketDataSourceKind,
    MarketTransportKind,
    QuoteSemantics,
    VenueInstrumentRef,
    VenueMarketKind,
)
from futures_bot.domain.replay import (
    ReplayDispatchContext,
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
    ReplayMarketPayloadHashPolicy,
    ReplayMarketTimestampPolicy,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.market_data.replay_adapter import build_replay_market_frame_timeline
from futures_bot.ports.decision import DecisionStackPort

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def test_replay_market_projection_flow_preserves_existing_boundaries() -> None:
    replay_instrument = ReplayInstrumentRef(
        venue="binance",
        symbol="BTCUSDT",
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
        quote_asset="USDT",
        base_asset="BTC",
    )
    record = ReplayInputRecord(
        record_id="record-1",
        kind=ReplayInputKind.TRADE,
        instrument=replay_instrument,
        event_time=NOW,
        source_sequence=1,
        payload={"price": Decimal("100"), "quantity": Decimal("1")},
    )
    replay_event = ReplayTimelineEvent(
        event_id="event-1",
        batch_id="batch-1",
        input_dataset_id="dataset-1",
        record_id="record-1",
        kind=ReplayInputKind.TRADE,
        instrument=replay_instrument,
        event_time=NOW,
        source_sequence=1,
        order_index=0,
    )
    window = TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=datetime(2026, 1, 1, 0, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, 0, tzinfo=UTC),
        window_id="window-1",
    )
    batch = ReplayInputBatch(
        batch_id="batch-1",
        replay_plan_id="plan-1",
        input_dataset_id="dataset-1",
        temporal_window=window,
        ordering_policy=ReplayOrderingPolicy.SOURCE_ORDER,
        records=(record,),
        created_at=NOW,
        validation_status=ReplayInputValidationStatus.VALIDATED,
    )
    timeline = ReplayTimeline(
        timeline_id="timeline-1",
        replay_plan_id="plan-1",
        temporal_window=window,
        ordering_policy=ReplayOrderingPolicy.SOURCE_ORDER,
        input_batch_ids=("batch-1",),
        input_dataset_ids=("dataset-1",),
        events=(replay_event,),
        created_at=NOW,
        status=ReplayTimelineStatus.VALIDATED,
    )
    binding = ReplayMarketDataBinding(
        binding_id=ReplayMarketBindingId("binding-1"),
        input_dataset_id="dataset-1",
        replay_instrument=replay_instrument,
        source=MarketDataSourceDescriptor(
            source_id=MarketDataSourceId("REPLAY_BINANCE"),
            source_kind=MarketDataSourceKind.REPLAY,
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
    descriptor = ReplayMarketAdapterDescriptor(
        adapter_id="adapter",
        adapter_version="v1",
        supported_input_kinds=(ReplayInputKind.TRADE,),
        timestamp_policy=ReplayMarketTimestampPolicy.EVENT_TIME_AS_SOURCE_AND_RECEIVED,
        payload_hash_policy=ReplayMarketPayloadHashPolicy.CANONICAL_REPLAY_RECORD,
    )

    projected = build_replay_market_frame_timeline(
        replay_timeline=timeline,
        input_batches=(batch,),
        descriptor=descriptor,
        bindings=(binding,),
    )

    assert len(projected.observation_projections) == 1
    assert len(projected.frame_projections) == 1
    assert projected.frame_projections[0].frame.source_health == ()
    assert not hasattr(replay_event, "payload")
    assert "payload" not in ReplayTimelineEvent.model_fields
    assert "market_frame" not in ReplayDispatchContext.model_fields
    assert replay_instrument.symbol == "BTCUSDT"
    assert "event" in inspect.signature(DecisionStackPort.decide).parameters
    assert "context" in inspect.signature(ReplayDecisionStackHandler.handle).parameters
