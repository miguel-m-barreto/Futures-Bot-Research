from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from futures_bot.domain.ids import RunId
from futures_bot.domain.replay import (
    ReplayInputBatch,
    ReplayInputDataset,
    ReplayInputKind,
    ReplayInputQuality,
    ReplayInputRecord,
    ReplayInputSourceKind,
    ReplayInputValidationStatus,
    ReplayInstrumentRef,
    ReplayOrderingPolicy,
    ReplayTimeline,
    ReplayTimelineCursorStatus,
    ReplayTimelineStatus,
)
from futures_bot.domain.research import (
    ReplayDataSourceKind,
    ReplayPlan,
    TemporalWindow,
    TemporalWindowKind,
)
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayInputBatchStore,
    InMemoryReplayInputDatasetStore,
    InMemoryReplayTimelineCursorStore,
    InMemoryReplayTimelineStore,
)
from futures_bot.infrastructure.research.in_memory import InMemoryReplayPlanStore
from futures_bot.replay.local import LocalReplayTimelineBuilder


def _utc(day: int = 1, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def _create_flow_stores() -> tuple[
    InMemoryReplayInputDatasetStore,
    InMemoryReplayInputBatchStore,
    InMemoryReplayTimelineStore,
    InMemoryReplayTimelineCursorStore,
    InMemoryReplayPlanStore,
]:
    return (
        InMemoryReplayInputDatasetStore(),
        InMemoryReplayInputBatchStore(),
        InMemoryReplayTimelineStore(),
        InMemoryReplayTimelineCursorStore(),
        InMemoryReplayPlanStore(),
    )


def _create_flow_window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(2, 0),
        end_at=_utc(3, 0),
        window_id="test-window",
    )


def _create_flow_replay_plan(
    replay_plan_store: InMemoryReplayPlanStore, window: TemporalWindow
) -> ReplayPlan:
    plan = ReplayPlan(
        replay_plan_id="plan-contract-flow",
        run_id=RunId("run-1"),
        data_source_kind=ReplayDataSourceKind.SYNTHETIC_FIXTURE,
        temporal_windows=(window,),
        created_at=_utc(1, 0),
    )
    replay_plan_store.save(plan)
    return plan


def _create_flow_instrument() -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol="BTCUSDT",
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
        quote_asset="USDT",
        base_asset="BTC",
    )


def _create_flow_dataset(
    input_dataset_store: InMemoryReplayInputDatasetStore,
    instrument: ReplayInstrumentRef,
    window: TemporalWindow,
) -> ReplayInputDataset:
    dataset = ReplayInputDataset(
        input_dataset_id="input-ds-flow",
        dataset_id="ds-flow",
        source_kind=ReplayInputSourceKind.SYNTHETIC_FIXTURE,
        quality=ReplayInputQuality.SYNTHETIC_FIXTURE,
        instruments=(instrument,),
        start_at=_utc(2, 0),
        end_at=_utc(3, 0),
        created_at=_utc(1, 1),
        record_count=4,
    )
    input_dataset_store.save(dataset)
    return dataset


def _create_flow_batches(
    input_batch_store: InMemoryReplayInputBatchStore,
    replay_plan: ReplayPlan,
    instrument: ReplayInstrumentRef,
    window: TemporalWindow,
) -> None:
    ohlcv_records = (
        ReplayInputRecord(
            record_id="ohlcv-1",
            kind=ReplayInputKind.OHLCV_BAR,
            instrument=instrument,
            event_time=_utc(2, 0),
            source_sequence=0,
            payload={
                "open": Decimal("100"),
                "high": Decimal("101"),
                "low": Decimal("99"),
                "close": Decimal("100.5"),
                "volume": Decimal("12.5"),
            },
        ),
        ReplayInputRecord(
            record_id="ohlcv-2",
            kind=ReplayInputKind.OHLCV_BAR,
            instrument=instrument,
            event_time=_utc(2, 2),
            source_sequence=2,
            payload={
                "open": Decimal("100.5"),
                "high": Decimal("102"),
                "low": Decimal("100"),
                "close": Decimal("101"),
                "volume": Decimal("9.75"),
            },
        ),
    )
    mark_records = (
        ReplayInputRecord(
            record_id="mark-1",
            kind=ReplayInputKind.MARK_PRICE,
            instrument=instrument,
            event_time=_utc(2, 1),
            source_sequence=1,
            payload={"price": Decimal("100.2")},
        ),
        ReplayInputRecord(
            record_id="mark-2",
            kind=ReplayInputKind.MARK_PRICE,
            instrument=instrument,
            event_time=_utc(2, 3),
            source_sequence=3,
            payload={"price": Decimal("101.1")},
        ),
    )
    ohlcv_batch = ReplayInputBatch(
        batch_id="batch-ohlcv",
        replay_plan_id=replay_plan.replay_plan_id,
        input_dataset_id="input-ds-flow",
        temporal_window=window,
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        records=ohlcv_records,
        created_at=_utc(1, 2),
        validation_status=ReplayInputValidationStatus.VALIDATED,
    )
    mark_batch = ReplayInputBatch(
        batch_id="batch-mark",
        replay_plan_id=replay_plan.replay_plan_id,
        input_dataset_id="input-ds-flow",
        temporal_window=window,
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        records=mark_records,
        created_at=_utc(1, 3),
        validation_status=ReplayInputValidationStatus.VALIDATED,
    )
    input_batch_store.save(ohlcv_batch)
    input_batch_store.save(mark_batch)


def _build_flow_timeline(  # noqa: PLR0913
    input_batch_store: InMemoryReplayInputBatchStore,
    timeline_store: InMemoryReplayTimelineStore,
    cursor_store: InMemoryReplayTimelineCursorStore,
    replay_plan_store: InMemoryReplayPlanStore,
    replay_plan: ReplayPlan,
    window: TemporalWindow,
) -> tuple[LocalReplayTimelineBuilder, ReplayTimeline]:
    builder = LocalReplayTimelineBuilder(
        input_batch_store=input_batch_store,
        timeline_store=timeline_store,
        cursor_store=cursor_store,
        replay_plan_store=replay_plan_store,
    )
    timeline = builder.build_timeline(
        "tl-contract-flow",
        replay_plan.replay_plan_id,
        ("batch-ohlcv", "batch-mark"),
        window,
        ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
    )
    return builder, timeline


def _assert_flow_timeline(timeline: ReplayTimeline) -> None:
    assert timeline.timeline_id == "tl-contract-flow"
    assert timeline.status is ReplayTimelineStatus.BUILT
    assert len(timeline.events) == 4
    assert [e.order_index for e in timeline.events] == [0, 1, 2, 3]
    assert timeline.events[0].event_id == "batch-ohlcv:ohlcv-1"
    assert timeline.events[1].event_id == "batch-mark:mark-1"
    assert timeline.events[2].event_id == "batch-ohlcv:ohlcv-2"
    assert timeline.events[3].event_id == "batch-mark:mark-2"
    assert timeline.events[0].batch_id == "batch-ohlcv"
    assert timeline.events[0].record_id == "ohlcv-1"
    assert timeline.events[1].batch_id == "batch-mark"
    assert timeline.events[1].record_id == "mark-1"
    for event in timeline.events:
        assert not hasattr(event, "payload")
    assert timeline.input_batch_ids == ("batch-ohlcv", "batch-mark")
    assert timeline.input_dataset_ids == ("input-ds-flow",)


def _assert_flow_cursor_lifecycle(
    builder: LocalReplayTimelineBuilder,
    cursor_store: InMemoryReplayTimelineCursorStore,
) -> None:
    cursor = builder.create_cursor("cursor-flow", "tl-contract-flow")
    assert cursor.status is ReplayTimelineCursorStatus.CREATED
    assert cursor.next_order_index == 0
    assert cursor.completed_at is None

    advanced = builder.advance_cursor("cursor-flow", 2)
    assert advanced.status is ReplayTimelineCursorStatus.ADVANCED
    assert advanced.next_order_index == 2
    assert advanced.completed_at is None

    completed = builder.complete_cursor("cursor-flow", 4)
    assert completed.status is ReplayTimelineCursorStatus.COMPLETED
    assert completed.next_order_index == 4
    assert completed.completed_at is not None

    assert not hasattr(completed, "metrics")
    assert not hasattr(completed, "evaluation_result")
    assert not hasattr(completed, "replay_output")
    assert not hasattr(builder, "run_replay")
    assert not hasattr(builder, "execute_strategy")
    assert not hasattr(builder, "calculate_metrics")

    persisted_cursor = cursor_store.load("cursor-flow")
    assert persisted_cursor == completed
    assert persisted_cursor.status is ReplayTimelineCursorStatus.COMPLETED  # type: ignore[union-attr]


def test_replay_timeline_contract_flow() -> None:
    (
        input_dataset_store,
        input_batch_store,
        timeline_store,
        cursor_store,
        replay_plan_store,
    ) = _create_flow_stores()
    window = _create_flow_window()
    replay_plan = _create_flow_replay_plan(replay_plan_store, window)
    instrument = _create_flow_instrument()
    _create_flow_dataset(input_dataset_store, instrument, window)
    _create_flow_batches(input_batch_store, replay_plan, instrument, window)
    builder, timeline = _build_flow_timeline(
        input_batch_store, timeline_store, cursor_store, replay_plan_store, replay_plan, window
    )
    _assert_flow_timeline(timeline)
    _assert_flow_cursor_lifecycle(builder, cursor_store)
    assert timeline_store.load("tl-contract-flow") == timeline
