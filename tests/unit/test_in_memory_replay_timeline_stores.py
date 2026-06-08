from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.domain.replay import (
    ReplayInputKind,
    ReplayInstrumentRef,
    ReplayOrderingPolicy,
    ReplayTimeline,
    ReplayTimelineCursor,
    ReplayTimelineCursorStatus,
    ReplayTimelineEvent,
    ReplayTimelineStatus,
)
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayTimelineCursorStore,
    InMemoryReplayTimelineStore,
)
from futures_bot.ports.replay import (
    ReplayTimelineCursorStorePort,
    ReplayTimelineStorePort,
)


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(0),
        end_at=_utc(10),
        window_id="tw-1",
    )


def _instrument() -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol="BTCUSDT",
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
    )


def _event(  # noqa: PLR0913
    event_id: str = "batch-1:record-1",
    *,
    batch_id: str = "batch-1",
    input_dataset_id: str = "ds-1",
    record_id: str = "record-1",
    event_time: datetime | None = None,
    source_sequence: int = 0,
    order_index: int = 0,
) -> ReplayTimelineEvent:
    return ReplayTimelineEvent(
        event_id=event_id,
        batch_id=batch_id,
        input_dataset_id=input_dataset_id,
        record_id=record_id,
        kind=ReplayInputKind.OHLCV_BAR,
        instrument=_instrument(),
        event_time=event_time or _utc(1),
        source_sequence=source_sequence,
        order_index=order_index,
    )


def _timeline(  # noqa: PLR0913
    timeline_id: str = "tl-1",
    *,
    replay_plan_id: str = "plan-1",
    events: tuple[ReplayTimelineEvent, ...] = (),
    input_batch_ids: tuple[str, ...] = (),
    input_dataset_ids: tuple[str, ...] = (),
    status: ReplayTimelineStatus = ReplayTimelineStatus.PLANNED,
    created_at: datetime | None = None,
) -> ReplayTimeline:
    return ReplayTimeline(
        timeline_id=timeline_id,
        replay_plan_id=replay_plan_id,
        temporal_window=_window(),
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        input_batch_ids=input_batch_ids,
        input_dataset_ids=input_dataset_ids,
        events=events,
        created_at=created_at or _utc(0),
        status=status,
    )


def _built_timeline(
    timeline_id: str = "tl-1",
    *,
    replay_plan_id: str = "plan-1",
    created_at: datetime | None = None,
) -> ReplayTimeline:
    e = _event()
    return _timeline(
        timeline_id,
        replay_plan_id=replay_plan_id,
        events=(e,),
        input_batch_ids=("batch-1",),
        input_dataset_ids=("ds-1",),
        status=ReplayTimelineStatus.BUILT,
        created_at=created_at,
    )


def _cursor(  # noqa: PLR0913
    cursor_id: str = "cursor-1",
    *,
    timeline_id: str = "tl-1",
    replay_plan_id: str = "plan-1",
    status: ReplayTimelineCursorStatus = ReplayTimelineCursorStatus.CREATED,
    next_order_index: int = 0,
    updated_at: datetime | None = None,
    completed_at: datetime | None = None,
    notes: str | None = None,
) -> ReplayTimelineCursor:
    return ReplayTimelineCursor(
        cursor_id=cursor_id,
        timeline_id=timeline_id,
        replay_plan_id=replay_plan_id,
        status=status,
        next_order_index=next_order_index,
        updated_at=updated_at or _utc(1),
        completed_at=completed_at,
        notes=notes,
    )


class TestInMemoryReplayTimelineStoreConformance:
    def test_conforms_to_port(self) -> None:
        _: ReplayTimelineStorePort = InMemoryReplayTimelineStore()


class TestInMemoryReplayTimelineStore:
    def test_save_and_load_round_trip(self) -> None:
        store = InMemoryReplayTimelineStore()
        tl = _built_timeline()
        store.save(tl)
        loaded = store.load("tl-1")
        assert loaded == tl

    def test_load_returns_none_for_missing(self) -> None:
        store = InMemoryReplayTimelineStore()
        assert store.load("nonexistent") is None

    def test_idempotent_save_accepted(self) -> None:
        store = InMemoryReplayTimelineStore()
        tl = _built_timeline()
        store.save(tl)
        store.save(tl)
        assert store.load("tl-1") == tl

    def test_conflict_rejected(self) -> None:
        store = InMemoryReplayTimelineStore()
        tl1 = _built_timeline("tl-1", replay_plan_id="plan-1")
        tl2 = _built_timeline("tl-1", replay_plan_id="plan-2")
        store.save(tl1)
        with pytest.raises(ValueError, match="conflict"):
            store.save(tl2)

    def test_model_copy_invalid_timeline_rejected(self) -> None:
        store = InMemoryReplayTimelineStore()
        tl = _built_timeline()
        store.save(tl)

        # model_copy bypasses pydantic validation: BUILT with no events is invalid
        invalid = tl.model_copy(update={"events": (), "input_batch_ids": ()})
        with pytest.raises((ValidationError, ValueError)):
            store.save(invalid)

    def test_list_for_replay_plan_deterministic_order(self) -> None:
        store = InMemoryReplayTimelineStore()
        tl_b = _built_timeline("tl-b", replay_plan_id="plan-1", created_at=_utc(2))
        tl_a = _built_timeline("tl-a", replay_plan_id="plan-1", created_at=_utc(1))
        store.save(tl_b)
        store.save(tl_a)
        results = store.list_for_replay_plan("plan-1")
        assert [t.timeline_id for t in results] == ["tl-a", "tl-b"]

    def test_list_for_replay_plan_filters_by_plan(self) -> None:
        store = InMemoryReplayTimelineStore()
        tl1 = _built_timeline("tl-1", replay_plan_id="plan-1")
        tl2 = _built_timeline("tl-2", replay_plan_id="plan-2")
        store.save(tl1)
        store.save(tl2)
        results = store.list_for_replay_plan("plan-1")
        assert len(results) == 1
        assert results[0].timeline_id == "tl-1"

    def test_list_for_replay_plan_same_created_at_sorted_by_id(self) -> None:
        store = InMemoryReplayTimelineStore()
        tl_z = _built_timeline("tl-z", replay_plan_id="plan-1", created_at=_utc(1))
        tl_a = _built_timeline("tl-a", replay_plan_id="plan-1", created_at=_utc(1))
        store.save(tl_z)
        store.save(tl_a)
        results = store.list_for_replay_plan("plan-1")
        assert [t.timeline_id for t in results] == ["tl-a", "tl-z"]


class TestInMemoryReplayTimelineCursorStoreConformance:
    def test_conforms_to_port(self) -> None:
        _: ReplayTimelineCursorStorePort = InMemoryReplayTimelineCursorStore()


class TestInMemoryReplayTimelineCursorStore:
    def test_save_and_load_round_trip(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        c = _cursor()
        store.save(c)
        loaded = store.load("cursor-1")
        assert loaded == c

    def test_load_returns_none_for_missing(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        assert store.load("nonexistent") is None

    def test_idempotent_save_accepted(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        c = _cursor()
        store.save(c)
        store.save(c)
        assert store.load("cursor-1") == c

    def test_created_to_advanced_allowed(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        store.save(_cursor(updated_at=_utc(1)))
        advanced = _cursor(
            status=ReplayTimelineCursorStatus.ADVANCED,
            next_order_index=3,
            updated_at=_utc(2),
        )
        store.save(advanced)
        assert store.load("cursor-1") == advanced

    def test_created_to_completed_allowed(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        store.save(_cursor(updated_at=_utc(1)))
        completed = _cursor(
            status=ReplayTimelineCursorStatus.COMPLETED,
            next_order_index=1,
            updated_at=_utc(2),
            completed_at=_utc(2),
        )
        store.save(completed)
        assert store.load("cursor-1") == completed

    def test_advanced_to_advanced_allowed_non_decreasing(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        store.save(_cursor(
            status=ReplayTimelineCursorStatus.ADVANCED, next_order_index=2, updated_at=_utc(1),
        ))
        advanced2 = _cursor(
            status=ReplayTimelineCursorStatus.ADVANCED,
            next_order_index=5,
            updated_at=_utc(2),
        )
        store.save(advanced2)
        assert store.load("cursor-1")
        assert store.load("cursor-1").next_order_index == 5  # type: ignore[union-attr]

    def test_advanced_to_advanced_same_index_allowed(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        store.save(_cursor(
            status=ReplayTimelineCursorStatus.ADVANCED, next_order_index=3, updated_at=_utc(1),
        ))
        same = _cursor(
            status=ReplayTimelineCursorStatus.ADVANCED,
            next_order_index=3,
            updated_at=_utc(2),
        )
        store.save(same)

    def test_advanced_to_advanced_regression_rejected(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        store.save(_cursor(
            status=ReplayTimelineCursorStatus.ADVANCED, next_order_index=5, updated_at=_utc(1),
        ))
        regressed = _cursor(
            status=ReplayTimelineCursorStatus.ADVANCED,
            next_order_index=3,
            updated_at=_utc(2),
        )
        with pytest.raises(ValueError, match="next_order_index cannot decrease"):
            store.save(regressed)

    def test_advanced_to_completed_allowed(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        store.save(_cursor(
            status=ReplayTimelineCursorStatus.ADVANCED, next_order_index=3, updated_at=_utc(1),
        ))
        completed = _cursor(
            status=ReplayTimelineCursorStatus.COMPLETED,
            next_order_index=5,
            updated_at=_utc(2),
            completed_at=_utc(2),
        )
        store.save(completed)

    def test_created_to_invalidated_allowed(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        store.save(_cursor(updated_at=_utc(1)))
        invalidated = _cursor(
            status=ReplayTimelineCursorStatus.INVALIDATED,
            updated_at=_utc(2),
            notes="bad data",
        )
        store.save(invalidated)

    def test_completed_to_invalidated_allowed(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        store.save(_cursor(
            status=ReplayTimelineCursorStatus.COMPLETED,
            next_order_index=3,
            updated_at=_utc(1),
            completed_at=_utc(1),
        ))
        invalidated = _cursor(
            status=ReplayTimelineCursorStatus.INVALIDATED,
            next_order_index=3,
            updated_at=_utc(2),
            notes="invalidated after completion",
        )
        store.save(invalidated)

    def test_invalidated_is_terminal(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        store.save(_cursor(
            status=ReplayTimelineCursorStatus.INVALIDATED, updated_at=_utc(1), notes="err",
        ))
        with pytest.raises(ValueError, match=r"INVALIDATED.*terminal"):
            store.save(_cursor(
                status=ReplayTimelineCursorStatus.ADVANCED,
                next_order_index=1,
                updated_at=_utc(2),
            ))

    def test_completed_to_advanced_rejected(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        store.save(_cursor(
            status=ReplayTimelineCursorStatus.COMPLETED,
            next_order_index=3,
            updated_at=_utc(1),
            completed_at=_utc(1),
        ))
        with pytest.raises(ValueError, match="invalid cursor transition"):
            store.save(_cursor(
                status=ReplayTimelineCursorStatus.ADVANCED,
                next_order_index=4,
                updated_at=_utc(2),
            ))

    def test_older_updated_at_rejected(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        store.save(_cursor(
            status=ReplayTimelineCursorStatus.ADVANCED,
            next_order_index=3,
            updated_at=_utc(5),
        ))
        with pytest.raises(ValueError, match="updated_at cannot go backwards"):
            store.save(_cursor(
                status=ReplayTimelineCursorStatus.ADVANCED,
                next_order_index=4,
                updated_at=_utc(3),
            ))

    def test_timeline_id_change_rejected(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        store.save(_cursor(timeline_id="tl-1", updated_at=_utc(1)))
        with pytest.raises(ValueError, match="timeline_id cannot change"):
            store.save(_cursor(
                timeline_id="tl-2",
                status=ReplayTimelineCursorStatus.ADVANCED,
                updated_at=_utc(2),
            ))

    def test_replay_plan_id_change_rejected(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        store.save(_cursor(replay_plan_id="plan-1", updated_at=_utc(1)))
        with pytest.raises(ValueError, match="replay_plan_id cannot change"):
            store.save(_cursor(
                replay_plan_id="plan-2",
                status=ReplayTimelineCursorStatus.ADVANCED,
                updated_at=_utc(2),
            ))

    def test_list_for_timeline_deterministic(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        c1 = _cursor("cursor-b", timeline_id="tl-1", updated_at=_utc(2))
        c2 = _cursor("cursor-a", timeline_id="tl-1", updated_at=_utc(1))
        store.save(c1)
        store.save(c2)
        results = store.list_for_timeline("tl-1")
        assert [c.cursor_id for c in results] == ["cursor-a", "cursor-b"]

    def test_list_for_timeline_filters_by_timeline(self) -> None:
        store = InMemoryReplayTimelineCursorStore()
        c1 = _cursor("cursor-1", timeline_id="tl-1")
        c2 = _cursor("cursor-2", timeline_id="tl-2")
        store.save(c1)
        store.save(c2)
        results = store.list_for_timeline("tl-1")
        assert len(results) == 1
        assert results[0].cursor_id == "cursor-1"

