"""In-memory replay input stores.

No DB. No filesystem. No Kafka. No market data loading.
"""
from __future__ import annotations

from futures_bot.domain.replay import (
    ReplayInputBatch,
    ReplayInputDataset,
    ReplayTimeline,
    ReplayTimelineCoverageReport,
    ReplayTimelineCursor,
    ReplayTimelineCursorStatus,
)

_CURSOR_ALLOWED_TRANSITIONS: dict[
    ReplayTimelineCursorStatus, frozenset[ReplayTimelineCursorStatus]
] = {
    ReplayTimelineCursorStatus.CREATED: frozenset({
        ReplayTimelineCursorStatus.ADVANCED,
        ReplayTimelineCursorStatus.COMPLETED,
        ReplayTimelineCursorStatus.INVALIDATED,
    }),
    ReplayTimelineCursorStatus.ADVANCED: frozenset({
        ReplayTimelineCursorStatus.ADVANCED,
        ReplayTimelineCursorStatus.COMPLETED,
        ReplayTimelineCursorStatus.INVALIDATED,
    }),
    ReplayTimelineCursorStatus.COMPLETED: frozenset({
        ReplayTimelineCursorStatus.INVALIDATED,
    }),
    ReplayTimelineCursorStatus.INVALIDATED: frozenset(),
}


class InMemoryReplayInputDatasetStore:
    """In-memory ReplayInputDatasetStorePort implementation."""

    def __init__(self) -> None:
        self._datasets: dict[str, ReplayInputDataset] = {}

    def save(self, dataset: ReplayInputDataset) -> None:
        """Save replay input dataset metadata, rejecting conflicting IDs."""
        dataset = ReplayInputDataset.model_validate(dataset.model_dump())
        existing = self._datasets.get(dataset.input_dataset_id)
        if existing is not None:
            if existing != dataset:
                raise ValueError(
                    f"input_dataset_id conflict for {dataset.input_dataset_id!r}"
                )
            return
        self._datasets[dataset.input_dataset_id] = dataset

    def load(self, input_dataset_id: str) -> ReplayInputDataset | None:
        """Return replay input dataset by input_dataset_id, or None."""
        return self._datasets.get(input_dataset_id)

    def list_for_dataset(self, dataset_id: str) -> tuple[ReplayInputDataset, ...]:
        """Return input datasets for dataset_id sorted by created_at then id."""
        return tuple(
            sorted(
                (
                    dataset
                    for dataset in self._datasets.values()
                    if dataset.dataset_id == dataset_id
                ),
                key=lambda dataset: (dataset.created_at, dataset.input_dataset_id),
            )
        )

    def list_all(self) -> tuple[ReplayInputDataset, ...]:
        """Return input datasets sorted by created_at then id."""
        return tuple(
            sorted(
                self._datasets.values(),
                key=lambda dataset: (dataset.created_at, dataset.input_dataset_id),
            )
        )


class InMemoryReplayInputBatchStore:
    """In-memory ReplayInputBatchStorePort implementation."""

    def __init__(self) -> None:
        self._batches: dict[str, ReplayInputBatch] = {}

    def save(self, batch: ReplayInputBatch) -> None:
        """Save replay input batch metadata, rejecting conflicting IDs."""
        batch = ReplayInputBatch.model_validate(batch.model_dump())
        existing = self._batches.get(batch.batch_id)
        if existing is not None:
            if existing != batch:
                raise ValueError(f"batch_id conflict for {batch.batch_id!r}")
            return
        self._batches[batch.batch_id] = batch

    def load(self, batch_id: str) -> ReplayInputBatch | None:
        """Return replay input batch by batch_id, or None."""
        return self._batches.get(batch_id)

    def list_for_replay_plan(self, replay_plan_id: str) -> tuple[ReplayInputBatch, ...]:
        """Return input batches for replay_plan_id sorted by created_at then id."""
        return tuple(
            sorted(
                (
                    batch
                    for batch in self._batches.values()
                    if batch.replay_plan_id == replay_plan_id
                ),
                key=lambda batch: (batch.created_at, batch.batch_id),
            )
        )

    def list_for_input_dataset(
        self, input_dataset_id: str
    ) -> tuple[ReplayInputBatch, ...]:
        """Return input batches for input_dataset_id sorted by created_at then id."""
        return tuple(
            sorted(
                (
                    batch
                    for batch in self._batches.values()
                    if batch.input_dataset_id == input_dataset_id
                ),
                key=lambda batch: (batch.created_at, batch.batch_id),
            )
        )


class InMemoryReplayTimelineStore:
    """In-memory ReplayTimelineStorePort implementation."""

    def __init__(self) -> None:
        self._timelines: dict[str, ReplayTimeline] = {}

    def save(self, timeline: ReplayTimeline) -> None:
        """Save replay timeline metadata, rejecting conflicting IDs."""
        timeline = ReplayTimeline.model_validate(timeline.model_dump())
        existing = self._timelines.get(timeline.timeline_id)
        if existing is not None:
            if existing != timeline:
                raise ValueError(
                    f"timeline_id conflict for {timeline.timeline_id!r}"
                )
            return
        self._timelines[timeline.timeline_id] = timeline

    def load(self, timeline_id: str) -> ReplayTimeline | None:
        """Return replay timeline by timeline_id, or None."""
        return self._timelines.get(timeline_id)

    def list_for_replay_plan(self, replay_plan_id: str) -> tuple[ReplayTimeline, ...]:
        """Return timelines for replay_plan_id sorted by created_at then timeline_id."""
        return tuple(
            sorted(
                (t for t in self._timelines.values() if t.replay_plan_id == replay_plan_id),
                key=lambda t: (t.created_at, t.timeline_id),
            )
        )


class InMemoryReplayTimelineCursorStore:
    """In-memory ReplayTimelineCursorStorePort implementation."""

    def __init__(self) -> None:
        self._cursors: dict[str, ReplayTimelineCursor] = {}

    def save(self, cursor: ReplayTimelineCursor) -> None:
        """Save cursor, enforcing valid state transitions."""
        cursor = ReplayTimelineCursor.model_validate(cursor.model_dump())
        existing = self._cursors.get(cursor.cursor_id)
        if existing is None:
            self._cursors[cursor.cursor_id] = cursor
            return
        if existing.timeline_id != cursor.timeline_id:
            raise ValueError("cursor timeline_id cannot change")
        if existing.replay_plan_id != cursor.replay_plan_id:
            raise ValueError("cursor replay_plan_id cannot change")
        if cursor == existing:
            return
        if cursor.updated_at < existing.updated_at:
            raise ValueError("cursor updated_at cannot go backwards")
        if existing.status is ReplayTimelineCursorStatus.INVALIDATED:
            raise ValueError("INVALIDATED cursor is terminal")
        allowed = _CURSOR_ALLOWED_TRANSITIONS.get(existing.status, frozenset())
        if cursor.status not in allowed:
            raise ValueError(
                f"invalid cursor transition {existing.status!r} -> {cursor.status!r}"
            )
        if (
            existing.status is ReplayTimelineCursorStatus.ADVANCED
            and cursor.status is ReplayTimelineCursorStatus.ADVANCED
            and cursor.next_order_index < existing.next_order_index
        ):
            raise ValueError("next_order_index cannot decrease for ADVANCED -> ADVANCED")
        self._cursors[cursor.cursor_id] = cursor

    def load(self, cursor_id: str) -> ReplayTimelineCursor | None:
        """Return cursor by cursor_id, or None."""
        return self._cursors.get(cursor_id)

    def list_for_timeline(self, timeline_id: str) -> tuple[ReplayTimelineCursor, ...]:
        """Return cursors for timeline_id sorted by updated_at then cursor_id."""
        return tuple(
            sorted(
                (c for c in self._cursors.values() if c.timeline_id == timeline_id),
                key=lambda c: (c.updated_at, c.cursor_id),
            )
        )


class InMemoryReplayTimelineCoverageReportStore:
    """In-memory ReplayTimelineCoverageReportStorePort implementation."""

    def __init__(self) -> None:
        self._reports: dict[str, ReplayTimelineCoverageReport] = {}

    def save(self, report: ReplayTimelineCoverageReport) -> None:
        """Save coverage report metadata, rejecting conflicting IDs."""
        report = ReplayTimelineCoverageReport.model_validate(report.model_dump())
        existing = self._reports.get(report.report_id)
        if existing is not None:
            if existing != report:
                raise ValueError(f"report_id conflict for {report.report_id!r}")
            return
        self._reports[report.report_id] = report

    def load(self, report_id: str) -> ReplayTimelineCoverageReport | None:
        """Return coverage report by report_id, or None."""
        return self._reports.get(report_id)

    def list_for_timeline(
        self, timeline_id: str
    ) -> tuple[ReplayTimelineCoverageReport, ...]:
        """Return coverage reports for timeline_id sorted by generated_at then report_id."""
        return tuple(
            sorted(
                (r for r in self._reports.values() if r.timeline_id == timeline_id),
                key=lambda r: (r.generated_at, r.report_id),
            )
        )

    def list_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayTimelineCoverageReport, ...]:
        """Return coverage reports for replay_plan_id sorted by generated_at then report_id."""
        return tuple(
            sorted(
                (r for r in self._reports.values() if r.replay_plan_id == replay_plan_id),
                key=lambda r: (r.generated_at, r.report_id),
            )
        )
