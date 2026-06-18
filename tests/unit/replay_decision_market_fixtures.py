from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from futures_bot.domain.decisions import DecisionSourceKind
from futures_bot.domain.ids import (
    BotId,
    MarketDataSourceId,
    ReplayMarketBindingId,
    VenueInstrumentId,
)
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
    build_replay_dispatcher_fingerprint,
)
from futures_bot.domain.replay_decisions import (
    ReplayDecisionStackContext,
    ReplayDecisionStackDescriptor,
    build_replay_decision_handler_fingerprint,
    build_replay_decision_intent_id,
    build_replay_decision_market_context_reference,
    build_replay_decision_stack_context,
)
from futures_bot.domain.replay_market_data import (
    ReplayMarketAdapterDescriptor,
    ReplayMarketDataBinding,
    ReplayMarketFrameTimeline,
    ReplayMarketPayloadHashPolicy,
    ReplayMarketTimestampPolicy,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.market_data.replay_adapter import build_replay_market_frame_timeline
from futures_bot.market_data.replay_lookup import LocalReplayMarketFrameLookup

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


@dataclass(frozen=True)
class ReplayDecisionMarketFixture:
    record: ReplayInputRecord
    event: ReplayTimelineEvent
    batch: ReplayInputBatch
    replay_timeline: ReplayTimeline
    market_timeline: ReplayMarketFrameTimeline
    lookup: LocalReplayMarketFrameLookup
    stack_descriptor: ReplayDecisionStackDescriptor
    dispatch_context: ReplayDispatchContext
    decision_context: ReplayDecisionStackContext
    handler_fingerprint: str


def replay_instrument(symbol: str = "BTCUSDT") -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol=symbol,
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
        quote_asset="USDT",
        base_asset=symbol[:-4],
    )


def stack_descriptor(
    *,
    stack_id: str = "stack-1",
    stack_version: str = "1",
    bot_id: BotId | None = None,
    source_kind: DecisionSourceKind = DecisionSourceKind.ML_MODEL,
    supported_event_kinds: tuple[ReplayInputKind, ...] = (ReplayInputKind.MARK_PRICE,),
) -> ReplayDecisionStackDescriptor:
    return ReplayDecisionStackDescriptor(
        stack_id=stack_id,
        stack_version=stack_version,
        bot_id=bot_id or BotId("bot-1"),
        source_kind=source_kind,
        supported_event_kinds=supported_event_kinds,
    )


def replay_decision_market_fixture(  # noqa: PLR0913 - explicit scenario fixture
    *,
    replay_plan_id: str = "plan-1",
    timeline_id: str = "timeline-1",
    run_id: str = "run-1",
    event_id: str = "event-1",
    event_order_index: int = 0,
    event_kind: ReplayInputKind = ReplayInputKind.MARK_PRICE,
    price: str = "100",
    descriptor: ReplayDecisionStackDescriptor | None = None,
) -> ReplayDecisionMarketFixture:
    instrument = replay_instrument()
    payload: dict[str, object]
    if event_kind is ReplayInputKind.TRADE:
        payload = {"price": Decimal(price), "quantity": Decimal("1")}
    elif event_kind is ReplayInputKind.ORDER_BOOK_TOP:
        payload = {
            "bid_price": Decimal(price),
            "bid_size": Decimal("1"),
            "ask_price": Decimal(price) + Decimal("1"),
            "ask_size": Decimal("1"),
        }
    else:
        payload = {"price": Decimal(price)}
    record = ReplayInputRecord(
        record_id="record-1",
        kind=event_kind,
        instrument=instrument,
        event_time=NOW,
        source_sequence=event_order_index,
        payload=payload,
        content_hash="sha256:" + "a" * 64,
    )
    event = ReplayTimelineEvent(
        event_id=event_id,
        batch_id="batch-1",
        input_dataset_id="dataset-1",
        record_id=record.record_id,
        kind=record.kind,
        instrument=record.instrument,
        event_time=record.event_time,
        source_sequence=record.source_sequence,
        order_index=event_order_index,
        content_hash=record.content_hash,
    )
    window = TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=datetime(2026, 1, 1, 0, tzinfo=UTC),
        end_at=datetime(2026, 1, 2, 0, tzinfo=UTC),
        window_id="window-1",
    )
    batch = ReplayInputBatch(
        batch_id="batch-1",
        replay_plan_id=replay_plan_id,
        input_dataset_id="dataset-1",
        temporal_window=window,
        ordering_policy=ReplayOrderingPolicy.SOURCE_ORDER,
        records=(record,),
        created_at=NOW,
        validation_status=ReplayInputValidationStatus.VALIDATED,
    )
    replay_timeline = ReplayTimeline(
        timeline_id=timeline_id,
        replay_plan_id=replay_plan_id,
        temporal_window=window,
        ordering_policy=ReplayOrderingPolicy.SOURCE_ORDER,
        input_batch_ids=("batch-1",),
        input_dataset_ids=("dataset-1",),
        events=(event,),
        created_at=NOW,
        status=ReplayTimelineStatus.VALIDATED,
    )
    market_timeline = build_replay_market_frame_timeline(
        replay_timeline=replay_timeline,
        input_batches=(batch,),
        descriptor=ReplayMarketAdapterDescriptor(
            adapter_id="adapter",
            adapter_version="v1",
            supported_input_kinds=tuple(sorted((event_kind,), key=lambda kind: kind.value)),
            timestamp_policy=ReplayMarketTimestampPolicy.EVENT_TIME_AS_SOURCE_AND_RECEIVED,
            payload_hash_policy=ReplayMarketPayloadHashPolicy.CANONICAL_REPLAY_RECORD,
        ),
        bindings=(
            ReplayMarketDataBinding(
                binding_id=ReplayMarketBindingId("binding-1"),
                input_dataset_id="dataset-1",
                replay_instrument=instrument,
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
                    raw_symbol=instrument.symbol,
                    logical_instrument="BTC/USDT",
                    market_kind=VenueMarketKind.LINEAR_PERPETUAL,
                    settlement_asset="USDT",
                    collateral_asset="USDT",
                    metadata_version="2026-01",
                ),
                quote_semantics=QuoteSemantics.CENTRAL_LIMIT_ORDER_BOOK,
                binding_version="v1",
            ),
        ),
    )
    lookup = LocalReplayMarketFrameLookup(market_timeline)
    stack = descriptor or stack_descriptor(supported_event_kinds=(event_kind,))
    handler_fingerprint = build_replay_decision_handler_fingerprint(
        stack_descriptor=stack,
        market_lookup_descriptor=lookup.descriptor,
    )
    dispatch_context = ReplayDispatchContext(
        run_id=run_id,
        manifest_id="manifest-1",
        replay_plan_id=replay_plan_id,
        timeline_id=timeline_id,
        timeline_fingerprint_id="fp-1",
        dispatcher_fingerprint=build_replay_dispatcher_fingerprint(()),
        event_id=event.event_id,
        event_order_index=event.order_index,
        event_time=event.event_time,
        event_kind=event.kind,
    )
    market = lookup.lookup(dispatch_context, event)
    decision_context = build_replay_decision_stack_context(
        dispatch_context=dispatch_context,
        event=event,
        market=market,
    )
    return ReplayDecisionMarketFixture(
        record=record,
        event=event,
        batch=batch,
        replay_timeline=replay_timeline,
        market_timeline=market_timeline,
        lookup=lookup,
        stack_descriptor=stack,
        dispatch_context=dispatch_context,
        decision_context=decision_context,
        handler_fingerprint=handler_fingerprint,
    )


def decision_id(
    fixture: ReplayDecisionMarketFixture,
    decision_index: int = 0,
) -> object:
    context = fixture.dispatch_context
    return build_replay_decision_intent_id(
        run_id=context.run_id,
        event_order_index=context.event_order_index,
        event_id=context.event_id,
        decision_handler_fingerprint=fixture.handler_fingerprint,
        market_context_reference_id=build_replay_decision_market_context_reference(
            fixture.decision_context
        ).reference_id,
        decision_index=decision_index,
    )
