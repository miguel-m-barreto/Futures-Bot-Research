from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from futures_bot.domain.ids import RunId
from futures_bot.domain.replay import (
    ReplayInputBatch,
    ReplayInputKind,
    ReplayInputRecord,
    ReplayInputValidationStatus,
    ReplayInstrumentRef,
    ReplayOrderingPolicy,
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
    InMemoryReplayTimelineCursorStore,
    InMemoryReplayTimelineStore,
)
from futures_bot.infrastructure.research.in_memory import InMemoryReplayPlanStore
from futures_bot.replay.local import LocalReplayTimelineBuilder


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(0),
        end_at=_utc(10),
        window_id="tw-1",
    )


def _instrument(symbol: str = "BTCUSDT") -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol=symbol,
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
    )


def _ohlcv_record(
    record_id: str,
    *,
    event_time: datetime,
    source_sequence: int = 0,
    symbol: str = "BTCUSDT",
) -> ReplayInputRecord:
    return ReplayInputRecord(
        record_id=record_id,
        kind=ReplayInputKind.OHLCV_BAR,
        instrument=_instrument(symbol),
        event_time=event_time,
        source_sequence=source_sequence,
        payload={
            "open": Decimal("100"),
            "high": Decimal("101"),
            "low": Decimal("99"),
            "close": Decimal("100.5"),
            "volume": Decimal("10"),
        },
    )


def _mark_record(
    record_id: str,
    *,
    event_time: datetime,
    source_sequence: int = 0,
) -> ReplayInputRecord:
    return ReplayInputRecord(
        record_id=record_id,
        kind=ReplayInputKind.MARK_PRICE,
        instrument=_instrument(),
        event_time=event_time,
        source_sequence=source_sequence,
        payload={"price": Decimal("100")},
    )


def _validated_batch(  # noqa: PLR0913
    batch_id: str,
    *,
    replay_plan_id: str = "plan-1",
    input_dataset_id: str = "ds-1",
    records: tuple[ReplayInputRecord, ...],
    ordering_policy: ReplayOrderingPolicy = ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
    window: TemporalWindow | None = None,
) -> ReplayInputBatch:
    return ReplayInputBatch(
        batch_id=batch_id,
        replay_plan_id=replay_plan_id,
        input_dataset_id=input_dataset_id,
        temporal_window=window or _window(),
        ordering_policy=ordering_policy,
        records=records,
        created_at=_utc(11),
        validation_status=ReplayInputValidationStatus.VALIDATED,
    )


def _replay_plan(
    replay_plan_id: str = "plan-1",
    *,
    window: TemporalWindow | None = None,
) -> ReplayPlan:
    return ReplayPlan(
        replay_plan_id=replay_plan_id,
        run_id=RunId("run-1"),
        data_source_kind=ReplayDataSourceKind.SYNTHETIC_FIXTURE,
        temporal_windows=(window or _window(),),
        created_at=_utc(0),
    )


def _builder(
    batch_store: InMemoryReplayInputBatchStore,
    timeline_store: InMemoryReplayTimelineStore,
    *,
    cursor_store: InMemoryReplayTimelineCursorStore | None = None,
    replay_plan_store: InMemoryReplayPlanStore | None = None,
    now: datetime | None = None,
) -> LocalReplayTimelineBuilder:
    fixed_ts = now or _utc(12)
    return LocalReplayTimelineBuilder(
        input_batch_store=batch_store,
        timeline_store=timeline_store,
        cursor_store=cursor_store,
        replay_plan_store=replay_plan_store,
        now=lambda: fixed_ts,
    )


class TestBuildTimeline:
    def test_build_from_single_validated_batch(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        batch = _validated_batch(
            "batch-1",
            records=(
                _ohlcv_record("r1", event_time=_utc(1)),
                _ohlcv_record("r2", event_time=_utc(2), source_sequence=1),
            ),
        )
        batch_store.save(batch)
        builder = _builder(batch_store, timeline_store)

        tl = builder.build_timeline(
            "tl-1",
            "plan-1",
            ("batch-1",),
            _window(),
            ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        )

        assert tl.timeline_id == "tl-1"
        assert tl.status is ReplayTimelineStatus.BUILT
        assert len(tl.events) == 2
        assert tl.events[0].order_index == 0
        assert tl.events[1].order_index == 1
        assert tl.events[0].event_time == _utc(1)
        assert tl.events[1].event_time == _utc(2)
        assert timeline_store.load("tl-1") == tl

    def test_deterministic_event_ids(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        batch = _validated_batch(
            "batch-abc",
            records=(_ohlcv_record("rec-xyz", event_time=_utc(1)),),
        )
        batch_store.save(batch)
        builder = _builder(batch_store, timeline_store)

        tl = builder.build_timeline(
            "tl-1", "plan-1", ("batch-abc",), _window(),
            ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        )

        assert tl.events[0].event_id == "batch-abc:rec-xyz"
        assert tl.events[0].batch_id == "batch-abc"
        assert tl.events[0].record_id == "rec-xyz"

    def test_build_from_multiple_batches_sorts_globally(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        # batch-1 has records at hours 1 and 3; batch-2 has record at hour 2
        batch1 = _validated_batch(
            "batch-1",
            input_dataset_id="ds-1",
            records=(
                _ohlcv_record("r1", event_time=_utc(1), source_sequence=0),
                _ohlcv_record("r3", event_time=_utc(3), source_sequence=2),
            ),
        )
        batch2 = _validated_batch(
            "batch-2",
            input_dataset_id="ds-2",
            records=(_ohlcv_record("r2", event_time=_utc(2), source_sequence=1),),
        )
        batch_store.save(batch1)
        batch_store.save(batch2)
        builder = _builder(batch_store, timeline_store)

        tl = builder.build_timeline(
            "tl-1", "plan-1", ("batch-1", "batch-2"), _window(),
            ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        )

        assert len(tl.events) == 3
        assert tl.events[0].event_id == "batch-1:r1"
        assert tl.events[1].event_id == "batch-2:r2"
        assert tl.events[2].event_id == "batch-1:r3"
        assert [e.order_index for e in tl.events] == [0, 1, 2]

    def test_deterministic_input_dataset_ids(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        batch1 = _validated_batch(
            "b1", input_dataset_id="ds-z", records=(_ohlcv_record("r1", event_time=_utc(1)),),
        )
        batch2 = _validated_batch(
            "b2", input_dataset_id="ds-a",
            records=(_ohlcv_record("r2", event_time=_utc(2), source_sequence=1),),
        )
        batch_store.save(batch1)
        batch_store.save(batch2)
        builder = _builder(batch_store, timeline_store)

        tl = builder.build_timeline(
            "tl-1", "plan-1", ("b1", "b2"), _window(),
            ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        )
        # sorted unique dataset ids
        assert tl.input_dataset_ids == ("ds-a", "ds-z")

    def test_rejects_missing_batch(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        builder = _builder(batch_store, timeline_store)

        with pytest.raises(ValueError, match="not found"):
            builder.build_timeline(
                "tl-1", "plan-1", ("nonexistent",), _window(),
                ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
            )

    def test_rejects_replay_plan_id_mismatch(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        batch = _validated_batch(
            "b1", replay_plan_id="plan-other", records=(_ohlcv_record("r1", event_time=_utc(1)),),
        )
        batch_store.save(batch)
        builder = _builder(batch_store, timeline_store)

        with pytest.raises(ValueError, match="replay_plan_id"):
            builder.build_timeline(
                "tl-1", "plan-1", ("b1",), _window(),
                ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
            )

    def test_rejects_temporal_window_mismatch(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        other_window = TemporalWindow(
            kind=TemporalWindowKind.TEST,
            start_at=_utc(0),
            end_at=_utc(5),
            window_id="tw-other",
        )
        batch = _validated_batch(
            "b1", records=(_ohlcv_record("r1", event_time=_utc(1)),), window=other_window,
        )
        batch_store.save(batch)
        builder = _builder(batch_store, timeline_store)

        with pytest.raises(ValueError, match="temporal_window"):
            builder.build_timeline(
                "tl-1", "plan-1", ("b1",), _window(),
                ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
            )

    def test_rejects_ordering_policy_mismatch(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        batch = _validated_batch(
            "b1",
            ordering_policy=ReplayOrderingPolicy.SOURCE_ORDER,
            records=(_ohlcv_record("r1", event_time=_utc(1)),),
        )
        batch_store.save(batch)
        builder = _builder(batch_store, timeline_store)

        with pytest.raises(ValueError, match="ordering_policy"):
            builder.build_timeline(
                "tl-1", "plan-1", ("b1",), _window(),
                ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
            )

    def test_rejects_non_validated_batch(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        planned_batch = ReplayInputBatch(
            batch_id="b1",
            replay_plan_id="plan-1",
            input_dataset_id="ds-1",
            temporal_window=_window(),
            ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
            records=(),
            created_at=_utc(11),
            validation_status=ReplayInputValidationStatus.PLANNED,
        )
        batch_store.save(planned_batch)
        builder = _builder(batch_store, timeline_store)

        with pytest.raises(ValueError, match="VALIDATED"):
            builder.build_timeline(
                "tl-1", "plan-1", ("b1",), _window(),
                ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
            )

    def test_rejects_duplicate_input_batch_ids(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        batch = _validated_batch("b1", records=(_ohlcv_record("r1", event_time=_utc(1)),))
        batch_store.save(batch)
        builder = _builder(batch_store, timeline_store)

        with pytest.raises(ValueError, match="duplicate input_batch_ids"):
            builder.build_timeline(
                "tl-1", "plan-1", ("b1", "b1"), _window(),
                ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
            )

    def test_validates_replay_plan_window_when_store_provided(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        replay_plan_store = InMemoryReplayPlanStore()
        other_window = TemporalWindow(
            kind=TemporalWindowKind.TEST,
            start_at=_utc(0),
            end_at=_utc(5),
            window_id="tw-other",
        )
        replay_plan_store.save(_replay_plan("plan-1", window=other_window))
        batch = _validated_batch("b1", records=(_ohlcv_record("r1", event_time=_utc(1)),))
        batch_store.save(batch)
        builder = _builder(batch_store, timeline_store, replay_plan_store=replay_plan_store)

        # _window() is [0, 10), plan has [0, 5) — mismatch
        with pytest.raises(ValueError, match="temporal_window"):
            builder.build_timeline(
                "tl-1", "plan-1", ("b1",), _window(),
                ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
            )

    def test_validates_replay_plan_must_exist(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        replay_plan_store = InMemoryReplayPlanStore()
        batch = _validated_batch("b1", records=(_ohlcv_record("r1", event_time=_utc(1)),))
        batch_store.save(batch)
        builder = _builder(batch_store, timeline_store, replay_plan_store=replay_plan_store)

        with pytest.raises(ValueError, match="not found"):
            builder.build_timeline(
                "tl-1", "plan-1", ("b1",), _window(),
                ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
            )

    def test_no_payload_data_in_timeline_events(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        batch = _validated_batch("b1", records=(_ohlcv_record("r1", event_time=_utc(1)),))
        batch_store.save(batch)
        builder = _builder(batch_store, timeline_store)

        tl = builder.build_timeline(
            "tl-1", "plan-1", ("b1",), _window(),
            ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        )
        # Events have no payload field
        assert not hasattr(tl.events[0], "payload")


class TestCursorMethods:
    def _setup(
        self,
        records: tuple[ReplayInputRecord, ...] | None = None,
    ) -> tuple[
        InMemoryReplayTimelineStore, InMemoryReplayTimelineCursorStore, LocalReplayTimelineBuilder
    ]:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        cursor_store = InMemoryReplayTimelineCursorStore()
        if records is None:
            records = (
                _ohlcv_record("r1", event_time=_utc(1)),
                _ohlcv_record("r2", event_time=_utc(2), source_sequence=1),
                _ohlcv_record("r3", event_time=_utc(3), source_sequence=2),
        )
        batch = _validated_batch("b1", records=records)
        batch_store.save(batch)
        builder = _builder(batch_store, timeline_store, cursor_store=cursor_store)
        builder.build_timeline(
            "tl-1", "plan-1", ("b1",), _window(),
            ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        )
        return timeline_store, cursor_store, builder

    def test_create_cursor(self) -> None:
        _, cursor_store, builder = self._setup()
        cursor = builder.create_cursor("c1", "tl-1")
        assert cursor.cursor_id == "c1"
        assert cursor.timeline_id == "tl-1"
        assert cursor.replay_plan_id == "plan-1"
        assert cursor.status is ReplayTimelineCursorStatus.CREATED
        assert cursor.next_order_index == 0
        assert cursor.completed_at is None
        assert cursor_store.load("c1") == cursor

    def test_create_cursor_requires_cursor_store(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        batch = _validated_batch("b1", records=(_ohlcv_record("r1", event_time=_utc(1)),))
        batch_store.save(batch)
        builder = _builder(batch_store, timeline_store, cursor_store=None)
        builder.build_timeline(
            "tl-1", "plan-1", ("b1",), _window(),
            ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        )
        with pytest.raises(ValueError, match="cursor_store is required"):
            builder.create_cursor("c1", "tl-1")

    def test_create_cursor_rejects_missing_timeline(self) -> None:
        batch_store = InMemoryReplayInputBatchStore()
        timeline_store = InMemoryReplayTimelineStore()
        cursor_store = InMemoryReplayTimelineCursorStore()
        builder = _builder(batch_store, timeline_store, cursor_store=cursor_store)
        with pytest.raises(ValueError, match="not found"):
            builder.create_cursor("c1", "nonexistent-tl")

    def test_advance_cursor(self) -> None:
        _, _, builder = self._setup()
        builder.create_cursor("c1", "tl-1")
        advanced = builder.advance_cursor("c1", 2)
        assert advanced.status is ReplayTimelineCursorStatus.ADVANCED
        assert advanced.next_order_index == 2
        assert advanced.completed_at is None

    def test_advance_cursor_rejects_regression(self) -> None:
        _, _, builder = self._setup()
        builder.create_cursor("c1", "tl-1")
        builder.advance_cursor("c1", 2)
        with pytest.raises(ValueError, match="cannot decrease"):
            builder.advance_cursor("c1", 1)

    def test_advance_cursor_rejects_beyond_timeline_length(self) -> None:
        _, _, builder = self._setup()
        builder.create_cursor("c1", "tl-1")
        # timeline has 3 events, so max advance index is 3
        with pytest.raises(ValueError, match="cannot exceed"):
            builder.advance_cursor("c1", 4)

    def test_complete_cursor_at_timeline_length(self) -> None:
        _, cursor_store, builder = self._setup()
        builder.create_cursor("c1", "tl-1")
        builder.advance_cursor("c1", 2)
        completed = builder.complete_cursor("c1", 3)
        assert completed.status is ReplayTimelineCursorStatus.COMPLETED
        assert completed.next_order_index == 3
        assert completed.completed_at is not None
        assert cursor_store.load("c1") == completed

    def test_complete_cursor_before_end_rejected(self) -> None:
        _, _, builder = self._setup()
        builder.create_cursor("c1", "tl-1")
        builder.advance_cursor("c1", 1)
        with pytest.raises(ValueError, match="must equal"):
            builder.complete_cursor("c1", 2)

    def test_complete_cursor_beyond_end_rejected(self) -> None:
        _, _, builder = self._setup()
        builder.create_cursor("c1", "tl-1")
        with pytest.raises(ValueError, match="must equal"):
            builder.complete_cursor("c1", 4)

    def test_invalidate_cursor_stores_reason(self) -> None:
        _, cursor_store, builder = self._setup()
        builder.create_cursor("c1", "tl-1")
        invalidated = builder.invalidate_cursor("c1", "data quality issue")
        assert invalidated.status is ReplayTimelineCursorStatus.INVALIDATED
        assert invalidated.notes == "data quality issue"
        assert cursor_store.load("c1") == invalidated

    def test_no_replay_result_or_artifact_created(self) -> None:
        _, _, builder = self._setup()
        builder.create_cursor("c1", "tl-1")
        advanced = builder.advance_cursor("c1", 1)
        completed = builder.complete_cursor("c1", 3)
        # Cursors are metadata only
        assert not hasattr(advanced, "metrics")
        assert not hasattr(completed, "evaluation_result")
        assert not hasattr(builder, "run_replay")
        assert not hasattr(builder, "execute_strategy")
