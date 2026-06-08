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


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _window(start_hour: int = 0, end_hour: int = 10) -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(start_hour),
        end_at=_utc(end_hour),
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
    kind: ReplayInputKind = ReplayInputKind.OHLCV_BAR,
    event_time: datetime | None = None,
    source_sequence: int = 0,
    order_index: int = 0,
    content_hash: str | None = None,
) -> ReplayTimelineEvent:
    return ReplayTimelineEvent(
        event_id=event_id,
        batch_id=batch_id,
        input_dataset_id=input_dataset_id,
        record_id=record_id,
        kind=kind,
        instrument=_instrument(),
        event_time=event_time or _utc(1),
        source_sequence=source_sequence,
        order_index=order_index,
        content_hash=content_hash,
    )


def _timeline(  # noqa: PLR0913
    events: tuple[ReplayTimelineEvent, ...] = (),
    *,
    timeline_id: str = "tl-1",
    replay_plan_id: str = "plan-1",
    ordering_policy: ReplayOrderingPolicy = ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
    status: ReplayTimelineStatus = ReplayTimelineStatus.PLANNED,
    input_batch_ids: tuple[str, ...] = (),
    input_dataset_ids: tuple[str, ...] = (),
    notes: str | None = None,
) -> ReplayTimeline:
    return ReplayTimeline(
        timeline_id=timeline_id,
        replay_plan_id=replay_plan_id,
        temporal_window=_window(),
        ordering_policy=ordering_policy,
        input_batch_ids=input_batch_ids,
        input_dataset_ids=input_dataset_ids,
        events=events,
        created_at=_utc(0),
        status=status,
        notes=notes,
    )


def _cursor(  # noqa: PLR0913
    *,
    cursor_id: str = "cursor-1",
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
        updated_at=updated_at or _utc(5),
        completed_at=completed_at,
        notes=notes,
    )


class TestReplayTimelineEvent:
    def test_valid_event(self) -> None:
        event = _event()
        assert event.event_id == "batch-1:record-1"
        assert event.order_index == 0
        assert event.source_sequence == 0
        assert event.content_hash is None

    def test_valid_event_with_content_hash(self) -> None:
        event = _event(content_hash="abc123")
        assert event.content_hash == "abc123"

    def test_rejects_bool_source_sequence(self) -> None:
        with pytest.raises(ValidationError, match="source_sequence"):
            ReplayTimelineEvent(
                event_id="e1",
                batch_id="b1",
                input_dataset_id="ds1",
                record_id="r1",
                kind=ReplayInputKind.OHLCV_BAR,
                instrument=_instrument(),
                event_time=_utc(1),
                source_sequence=True,
                order_index=0,
            )

    def test_rejects_string_source_sequence(self) -> None:
        with pytest.raises(ValidationError, match="source_sequence"):
            ReplayTimelineEvent(
                event_id="e1",
                batch_id="b1",
                input_dataset_id="ds1",
                record_id="r1",
                kind=ReplayInputKind.OHLCV_BAR,
                instrument=_instrument(),
                event_time=_utc(1),
                source_sequence="0",
                order_index=0,
            )

    def test_rejects_bool_order_index(self) -> None:
        with pytest.raises(ValidationError, match="order_index"):
            ReplayTimelineEvent(
                event_id="e1",
                batch_id="b1",
                input_dataset_id="ds1",
                record_id="r1",
                kind=ReplayInputKind.OHLCV_BAR,
                instrument=_instrument(),
                event_time=_utc(1),
                source_sequence=0,
                order_index=False,
            )

    def test_rejects_string_order_index(self) -> None:
        with pytest.raises(ValidationError, match="order_index"):
            ReplayTimelineEvent(
                event_id="e1",
                batch_id="b1",
                input_dataset_id="ds1",
                record_id="r1",
                kind=ReplayInputKind.OHLCV_BAR,
                instrument=_instrument(),
                event_time=_utc(1),
                source_sequence=0,
                order_index="0",
            )

    def test_rejects_negative_source_sequence(self) -> None:
        with pytest.raises(ValidationError, match="source_sequence"):
            _event(source_sequence=-1)

    def test_rejects_negative_order_index(self) -> None:
        with pytest.raises(ValidationError, match="order_index"):
            _event(order_index=-1)

    def test_rejects_empty_content_hash(self) -> None:
        with pytest.raises(ValidationError):
            _event(content_hash="")

    def test_rejects_naive_event_time(self) -> None:
        with pytest.raises(ValidationError):
            ReplayTimelineEvent(
                event_id="e1",
                batch_id="b1",
                input_dataset_id="ds1",
                record_id="r1",
                kind=ReplayInputKind.OHLCV_BAR,
                instrument=_instrument(),
                event_time=datetime(2026, 1, 1, 1),
                source_sequence=0,
                order_index=0,
            )

    def test_rejects_empty_event_id(self) -> None:
        with pytest.raises(ValidationError):
            _event(event_id="")

    def test_rejects_empty_batch_id(self) -> None:
        with pytest.raises(ValidationError):
            _event(batch_id="")


class TestReplayTimeline:
    def test_valid_planned_timeline_empty(self) -> None:
        tl = _timeline(status=ReplayTimelineStatus.PLANNED)
        assert tl.status is ReplayTimelineStatus.PLANNED
        assert tl.events == ()
        assert tl.input_batch_ids == ()

    def test_valid_built_timeline_with_events(self) -> None:
        e = _event()
        tl = _timeline(
            events=(e,),
            status=ReplayTimelineStatus.BUILT,
            input_batch_ids=("batch-1",),
            input_dataset_ids=("ds-1",),
        )
        assert len(tl.events) == 1
        assert tl.events[0].order_index == 0

    def test_valid_two_event_timeline(self) -> None:
        e1 = _event("batch-1:record-1", event_time=_utc(1), source_sequence=0, order_index=0)
        e2 = _event(
            "batch-1:record-2",
            record_id="record-2",
            event_time=_utc(2),
            source_sequence=1,
            order_index=1,
        )
        tl = _timeline(
            events=(e1, e2),
            status=ReplayTimelineStatus.BUILT,
            input_batch_ids=("batch-1",),
            input_dataset_ids=("ds-1",),
        )
        assert tl.events[0].order_index == 0
        assert tl.events[1].order_index == 1

    def test_rejects_built_with_no_events(self) -> None:
        with pytest.raises(ValidationError, match="events can be empty only for PLANNED"):
            _timeline(
                events=(),
                status=ReplayTimelineStatus.BUILT,
                input_batch_ids=("batch-1",),
                input_dataset_ids=("ds-1",),
            )

    def test_rejects_validated_with_no_events(self) -> None:
        with pytest.raises(ValidationError, match="events can be empty only for PLANNED"):
            _timeline(
                events=(),
                status=ReplayTimelineStatus.VALIDATED,
                input_batch_ids=("batch-1",),
                input_dataset_ids=("ds-1",),
            )

    def test_rejects_duplicate_event_id(self) -> None:
        e1 = _event("batch-1:record-1", order_index=0)
        e2 = _event("batch-1:record-1", record_id="record-2", order_index=1)
        with pytest.raises(ValidationError, match="duplicate event_id"):
            _timeline(
                events=(e1, e2),
                status=ReplayTimelineStatus.BUILT,
                input_batch_ids=("batch-1",),
                input_dataset_ids=("ds-1",),
            )

    def test_rejects_duplicate_batch_record_pair(self) -> None:
        e1 = _event("ev-1", batch_id="batch-1", record_id="record-1", order_index=0)
        e2 = _event(
            "ev-2",
            batch_id="batch-1",
            record_id="record-1",
            event_time=_utc(2),
            source_sequence=1,
            order_index=1,
        )
        with pytest.raises(ValidationError, match=r"duplicate.*batch_id.*record_id"):
            _timeline(
                events=(e1, e2),
                status=ReplayTimelineStatus.BUILT,
                input_batch_ids=("batch-1",),
                input_dataset_ids=("ds-1",),
            )

    def test_rejects_event_outside_temporal_window(self) -> None:
        e = _event(event_time=_utc(11))
        with pytest.raises(ValidationError, match="temporal_window"):
            _timeline(
                events=(e,),
                status=ReplayTimelineStatus.BUILT,
                input_batch_ids=("batch-1",),
                input_dataset_ids=("ds-1",),
            )

    def test_rejects_event_at_window_end_boundary(self) -> None:
        e = _event(event_time=_utc(10))
        with pytest.raises(ValidationError, match="temporal_window"):
            _timeline(
                events=(e,),
                status=ReplayTimelineStatus.BUILT,
                input_batch_ids=("batch-1",),
                input_dataset_ids=("ds-1",),
            )

    def test_rejects_non_contiguous_order_index(self) -> None:
        e1 = _event("ev-1", order_index=0)
        e2 = _event("ev-2", record_id="record-2", event_time=_utc(2), order_index=2)
        with pytest.raises(ValidationError, match="order_index"):
            _timeline(
                events=(e1, e2),
                ordering_policy=ReplayOrderingPolicy.SOURCE_ORDER,
                status=ReplayTimelineStatus.BUILT,
                input_batch_ids=("batch-1",),
                input_dataset_ids=("ds-1",),
            )

    def test_rejects_events_not_sorted_by_order_index(self) -> None:
        e1 = _event("ev-1", event_time=_utc(1), order_index=1)
        e2 = _event("ev-2", record_id="record-2", event_time=_utc(2), order_index=0)
        with pytest.raises(ValidationError, match="order_index"):
            _timeline(
                events=(e1, e2),
                ordering_policy=ReplayOrderingPolicy.SOURCE_ORDER,
                status=ReplayTimelineStatus.BUILT,
                input_batch_ids=("batch-1",),
                input_dataset_ids=("ds-1",),
            )

    def test_rejects_event_time_then_sequence_out_of_order(self) -> None:
        e1 = _event("ev-1", event_time=_utc(2), source_sequence=1, order_index=0)
        e2 = _event(
            "ev-2", record_id="record-2", event_time=_utc(1), source_sequence=0, order_index=1,
        )
        with pytest.raises(ValidationError, match="EVENT_TIME_THEN_SEQUENCE"):
            _timeline(
                events=(e1, e2),
                ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
                status=ReplayTimelineStatus.BUILT,
                input_batch_ids=("batch-1",),
                input_dataset_ids=("ds-1",),
            )

    def test_rejects_event_time_then_kind_then_sequence_out_of_order(self) -> None:
        # MARK_PRICE < OHLCV_BAR alphabetically (M < O), so OHLCV_BAR first is wrong
        e1 = _event("ev-1", kind=ReplayInputKind.OHLCV_BAR, event_time=_utc(1), order_index=0)
        e2 = _event(
            "ev-2",
            record_id="record-2",
            kind=ReplayInputKind.MARK_PRICE,
            event_time=_utc(1),
            source_sequence=0,
            order_index=1,
        )
        with pytest.raises(ValidationError, match="EVENT_TIME_THEN_KIND_THEN_SEQUENCE"):
            _timeline(
                events=(e1, e2),
                ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_KIND_THEN_SEQUENCE,
                status=ReplayTimelineStatus.BUILT,
                input_batch_ids=("batch-1",),
                input_dataset_ids=("ds-1",),
            )

    def test_source_order_allows_custom_event_order(self) -> None:
        # SOURCE_ORDER only requires contiguous order_index
        e1 = _event("ev-1", event_time=_utc(5), source_sequence=1, order_index=0)
        e2 = _event(
            "ev-2", record_id="record-2", event_time=_utc(1), source_sequence=0, order_index=1,
        )
        tl = _timeline(
            events=(e1, e2),
            ordering_policy=ReplayOrderingPolicy.SOURCE_ORDER,
            status=ReplayTimelineStatus.BUILT,
            input_batch_ids=("batch-1",),
            input_dataset_ids=("ds-1",),
        )
        assert len(tl.events) == 2
        assert tl.events[0].event_time == _utc(5)

    def test_other_policy_allows_custom_event_order(self) -> None:
        e1 = _event("ev-1", event_time=_utc(5), order_index=0)
        e2 = _event("ev-2", record_id="record-2", event_time=_utc(1), order_index=1)
        tl = _timeline(
            events=(e1, e2),
            ordering_policy=ReplayOrderingPolicy.OTHER,
            status=ReplayTimelineStatus.BUILT,
            input_batch_ids=("batch-1",),
            input_dataset_ids=("ds-1",),
        )
        assert len(tl.events) == 2

    def test_rejects_duplicate_input_batch_ids(self) -> None:
        e = _event()
        with pytest.raises(ValidationError, match="duplicate input_batch_ids"):
            _timeline(
                events=(e,),
                status=ReplayTimelineStatus.BUILT,
                input_batch_ids=("batch-1", "batch-1"),
                input_dataset_ids=("ds-1",),
            )

    def test_rejects_batch_id_set_mismatch(self) -> None:
        e = _event(batch_id="batch-1")
        with pytest.raises(ValidationError, match="input_batch_ids"):
            _timeline(
                events=(e,),
                status=ReplayTimelineStatus.BUILT,
                input_batch_ids=("batch-2",),
                input_dataset_ids=("ds-1",),
            )

    def test_rejects_empty_notes(self) -> None:
        with pytest.raises(ValidationError):
            _timeline(notes="")

    def test_valid_notes(self) -> None:
        tl = _timeline(notes="some note")
        assert tl.notes == "some note"


class TestReplayTimelineCursor:
    def test_valid_created_cursor(self) -> None:
        c = _cursor()
        assert c.status is ReplayTimelineCursorStatus.CREATED
        assert c.next_order_index == 0
        assert c.completed_at is None

    def test_valid_advanced_cursor(self) -> None:
        c = _cursor(status=ReplayTimelineCursorStatus.ADVANCED, next_order_index=3)
        assert c.status is ReplayTimelineCursorStatus.ADVANCED
        assert c.next_order_index == 3
        assert c.completed_at is None

    def test_valid_completed_cursor(self) -> None:
        c = _cursor(
            status=ReplayTimelineCursorStatus.COMPLETED,
            next_order_index=5,
            updated_at=_utc(5),
            completed_at=_utc(5),
        )
        assert c.completed_at is not None

    def test_valid_invalidated_cursor_with_notes(self) -> None:
        c = _cursor(status=ReplayTimelineCursorStatus.INVALIDATED, notes="data error")
        assert c.status is ReplayTimelineCursorStatus.INVALIDATED
        assert c.notes == "data error"

    def test_rejects_bool_next_order_index(self) -> None:
        with pytest.raises(ValidationError, match="next_order_index"):
            ReplayTimelineCursor(
                cursor_id="c1",
                timeline_id="tl1",
                replay_plan_id="plan1",
                status=ReplayTimelineCursorStatus.CREATED,
                next_order_index=True,
                updated_at=_utc(1),
            )

    def test_rejects_string_next_order_index(self) -> None:
        with pytest.raises(ValidationError, match="next_order_index"):
            ReplayTimelineCursor(
                cursor_id="c1",
                timeline_id="tl1",
                replay_plan_id="plan1",
                status=ReplayTimelineCursorStatus.CREATED,
                next_order_index="0",
                updated_at=_utc(1),
            )

    def test_rejects_negative_next_order_index(self) -> None:
        with pytest.raises(ValidationError, match="next_order_index"):
            _cursor(next_order_index=-1)

    def test_completed_requires_completed_at(self) -> None:
        with pytest.raises(ValidationError, match="completed_at is required"):
            _cursor(status=ReplayTimelineCursorStatus.COMPLETED, completed_at=None)

    def test_non_completed_rejects_completed_at(self) -> None:
        with pytest.raises(ValidationError, match="completed_at must be None"):
            _cursor(
                status=ReplayTimelineCursorStatus.ADVANCED,
                completed_at=_utc(6),
            )

    def test_invalidated_rejects_completed_at(self) -> None:
        with pytest.raises(ValidationError, match="completed_at must be None"):
            _cursor(
                status=ReplayTimelineCursorStatus.INVALIDATED,
                completed_at=_utc(6),
            )

    def test_completed_at_must_be_gte_updated_at(self) -> None:
        with pytest.raises(ValidationError, match="completed_at must be >="):
            _cursor(
                status=ReplayTimelineCursorStatus.COMPLETED,
                updated_at=_utc(6),
                completed_at=_utc(5),
            )

    def test_completed_at_equal_to_updated_at_is_valid(self) -> None:
        c = _cursor(
            status=ReplayTimelineCursorStatus.COMPLETED,
            updated_at=_utc(5),
            completed_at=_utc(5),
        )
        assert c.completed_at == c.updated_at

    def test_rejects_naive_updated_at(self) -> None:
        with pytest.raises(ValidationError):
            ReplayTimelineCursor(
                cursor_id="c1",
                timeline_id="tl1",
                replay_plan_id="plan1",
                status=ReplayTimelineCursorStatus.CREATED,
                next_order_index=0,
                updated_at=datetime(2026, 1, 1),
            )

    def test_rejects_empty_cursor_id(self) -> None:
        with pytest.raises(ValidationError):
            _cursor(cursor_id="")

    def test_rejects_empty_notes(self) -> None:
        with pytest.raises(ValidationError):
            _cursor(notes="")
