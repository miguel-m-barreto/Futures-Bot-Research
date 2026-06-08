"""Local metadata-only replay input planner.

No file IO. No market data loading. No replay execution.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from futures_bot.domain.ids import RunId
from futures_bot.domain.replay import (
    ReplayInputBatch,
    ReplayInputDataset,
    ReplayInputRecord,
    ReplayInputValidationStatus,
    ReplayOrderingPolicy,
    ReplayTimeline,
    ReplayTimelineCursor,
    ReplayTimelineCursorStatus,
    ReplayTimelineEvent,
    ReplayTimelineStatus,
)
from futures_bot.domain.research import ReplayDataSourceKind, TemporalWindow
from futures_bot.ports.replay import (
    ReplayInputBatchStorePort,
    ReplayInputDatasetStorePort,
    ReplayTimelineCursorStorePort,
    ReplayTimelineStorePort,
)
from futures_bot.ports.research import (
    ReplayPlanStorePort,
    ResearchRunManifestStorePort,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LocalReplayInputPlanner:
    """Register and validate replay input metadata contracts."""

    def __init__(
        self,
        *,
        input_dataset_store: ReplayInputDatasetStorePort,
        input_batch_store: ReplayInputBatchStorePort,
        replay_plan_store: ReplayPlanStorePort | None = None,
        manifest_store: ResearchRunManifestStorePort | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._input_dataset_store = input_dataset_store
        self._input_batch_store = input_batch_store
        self._replay_plan_store = replay_plan_store
        self._manifest_store = manifest_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def register_input_dataset(
        self, dataset: ReplayInputDataset
    ) -> ReplayInputDataset:
        """Save replay input dataset metadata."""
        self._input_dataset_store.save(dataset)
        return dataset

    def create_input_batch(self, batch: ReplayInputBatch) -> ReplayInputBatch:
        """Validate and save replay input batch metadata."""
        self.validate_batch_against_replay_plan(batch)
        self._input_batch_store.save(batch)
        return batch

    def input_datasets_for_dataset(
        self, dataset_id: str
    ) -> tuple[ReplayInputDataset, ...]:
        """Return input datasets for dataset_id."""
        return self._input_dataset_store.list_for_dataset(dataset_id)

    def batches_for_replay_plan(
        self, replay_plan_id: str
    ) -> tuple[ReplayInputBatch, ...]:
        """Return input batches for replay_plan_id."""
        return self._input_batch_store.list_for_replay_plan(replay_plan_id)

    def validate_dataset_against_manifest(
        self, dataset: ReplayInputDataset, run_id: RunId
    ) -> None:
        """Validate replay input dataset metadata against a manifest, if available."""
        if self._manifest_store is None:
            return
        manifest = self._manifest_store.load(run_id)
        if manifest is None:
            raise KeyError(f"research run manifest not found: {run_id!s}")
        if dataset.dataset_id != manifest.dataset.dataset_id:
            raise ValueError("input dataset dataset_id must match manifest dataset_id")
        if (
            dataset.start_at < manifest.dataset.start_at
            or dataset.end_at > manifest.dataset.end_at
        ):
            raise ValueError("input dataset time range must be within manifest dataset")
        manifest_symbols = set(manifest.dataset.symbols)
        for instrument in dataset.instruments:
            if instrument.symbol not in manifest_symbols:
                raise ValueError("input dataset instrument symbol is not in manifest")

    def validate_batch_against_replay_plan(self, batch: ReplayInputBatch) -> None:
        """Validate replay input batch metadata against replay plan, if available."""
        if self._replay_plan_store is None:
            return
        replay_plan = self._replay_plan_store.load(batch.replay_plan_id)
        if replay_plan is None:
            raise KeyError(f"replay plan not found: {batch.replay_plan_id}")
        input_dataset = self._input_dataset_store.load(batch.input_dataset_id)
        if input_dataset is None:
            raise KeyError(f"replay input dataset not found: {batch.input_dataset_id}")
        if (
            replay_plan.data_source_kind is ReplayDataSourceKind.DATASET_SNAPSHOT
            and input_dataset.dataset_id != replay_plan.dataset_id
        ):
            raise ValueError("input dataset dataset_id must match replay plan dataset_id")
        if batch.temporal_window not in replay_plan.temporal_windows:
            raise ValueError("input batch temporal_window must exactly match replay plan")


class LocalReplayTimelineBuilder:
    """Build and manage replay timeline metadata contracts.

    No file IO. No market data loading. No replay execution.
    """

    def __init__(
        self,
        *,
        input_batch_store: ReplayInputBatchStorePort,
        timeline_store: ReplayTimelineStorePort,
        cursor_store: ReplayTimelineCursorStorePort | None = None,
        replay_plan_store: ReplayPlanStorePort | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._input_batch_store = input_batch_store
        self._timeline_store = timeline_store
        self._cursor_store = cursor_store
        self._replay_plan_store = replay_plan_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def build_timeline(  # noqa: PLR0913 — explicit sprint contract boundary
        self,
        timeline_id: str,
        replay_plan_id: str,
        input_batch_ids: tuple[str, ...],
        temporal_window: TemporalWindow,
        ordering_policy: ReplayOrderingPolicy,
        status: ReplayTimelineStatus = ReplayTimelineStatus.BUILT,
        notes: str | None = None,
    ) -> ReplayTimeline:
        """Build a deterministic replay timeline from validated input batches."""
        if len(set(input_batch_ids)) != len(input_batch_ids):
            raise ValueError("duplicate input_batch_ids are not allowed")

        if self._replay_plan_store is not None:
            replay_plan = self._replay_plan_store.load(replay_plan_id)
            if replay_plan is None:
                raise ValueError(f"replay plan not found: {replay_plan_id!r}")
            if temporal_window not in replay_plan.temporal_windows:
                raise ValueError(
                    "temporal_window must exactly match one of replay_plan.temporal_windows"
                )

        batches: list[ReplayInputBatch] = []
        for batch_id in input_batch_ids:
            batch = self._input_batch_store.load(batch_id)
            if batch is None:
                raise ValueError(f"replay input batch not found: {batch_id!r}")
            if batch.replay_plan_id != replay_plan_id:
                raise ValueError(
                    f"batch {batch_id!r} replay_plan_id does not match"
                )
            if batch.temporal_window != temporal_window:
                raise ValueError(
                    f"batch {batch_id!r} temporal_window does not match"
                )
            if batch.ordering_policy != ordering_policy:
                raise ValueError(
                    f"batch {batch_id!r} ordering_policy does not match"
                )
            if batch.validation_status is not ReplayInputValidationStatus.VALIDATED:
                raise ValueError(
                    f"batch {batch_id!r} must be VALIDATED, got {batch.validation_status!r}"
                )
            batches.append(batch)

        raw: list[tuple[ReplayInputRecord, str, str]] = [
            (record, batch.batch_id, batch.input_dataset_id)
            for batch in batches
            for record in batch.records
        ]

        if ordering_policy is ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE:
            raw.sort(
                key=lambda x: (
                    x[0].event_time,
                    x[0].source_sequence,
                    f"{x[1]}:{x[0].record_id}",
                )
            )
        elif ordering_policy is ReplayOrderingPolicy.EVENT_TIME_THEN_KIND_THEN_SEQUENCE:
            raw.sort(
                key=lambda x: (
                    x[0].event_time,
                    x[0].kind.value,
                    x[0].source_sequence,
                    f"{x[1]}:{x[0].record_id}",
                )
            )

        events = tuple(
            ReplayTimelineEvent(
                event_id=f"{batch_id}:{record.record_id}",
                batch_id=batch_id,
                input_dataset_id=input_dataset_id,
                record_id=record.record_id,
                kind=record.kind,
                instrument=record.instrument,
                event_time=record.event_time,
                source_sequence=record.source_sequence,
                order_index=i,
                content_hash=record.content_hash,
            )
            for i, (record, batch_id, input_dataset_id) in enumerate(raw)
        )

        input_dataset_ids = tuple(sorted({batch.input_dataset_id for batch in batches}))

        timeline = ReplayTimeline(
            timeline_id=timeline_id,
            replay_plan_id=replay_plan_id,
            temporal_window=temporal_window,
            ordering_policy=ordering_policy,
            input_batch_ids=input_batch_ids,
            input_dataset_ids=input_dataset_ids,
            events=events,
            created_at=self._now(),
            status=status,
            notes=notes,
        )
        self._timeline_store.save(timeline)
        return timeline

    def create_cursor(self, cursor_id: str, timeline_id: str) -> ReplayTimelineCursor:
        """Create a metadata cursor for a timeline, starting at order_index 0."""
        if self._cursor_store is None:
            raise ValueError("cursor_store is required for cursor operations")
        timeline = self._timeline_store.load(timeline_id)
        if timeline is None:
            raise ValueError(f"timeline not found: {timeline_id!r}")
        cursor = ReplayTimelineCursor(
            cursor_id=cursor_id,
            timeline_id=timeline_id,
            replay_plan_id=timeline.replay_plan_id,
            status=ReplayTimelineCursorStatus.CREATED,
            next_order_index=0,
            updated_at=self._now(),
        )
        self._cursor_store.save(cursor)
        return cursor

    def advance_cursor(self, cursor_id: str, next_order_index: int) -> ReplayTimelineCursor:
        """Advance cursor metadata to next_order_index (no replay execution)."""
        if self._cursor_store is None:
            raise ValueError("cursor_store is required for cursor operations")
        cursor = self._cursor_store.load(cursor_id)
        if cursor is None:
            raise ValueError(f"cursor not found: {cursor_id!r}")
        if next_order_index < cursor.next_order_index:
            raise ValueError("next_order_index cannot decrease")
        timeline = self._timeline_store.load(cursor.timeline_id)
        if timeline is not None and next_order_index > len(timeline.events):
            raise ValueError("next_order_index cannot exceed timeline event count")
        new_cursor = ReplayTimelineCursor(
            cursor_id=cursor.cursor_id,
            timeline_id=cursor.timeline_id,
            replay_plan_id=cursor.replay_plan_id,
            status=ReplayTimelineCursorStatus.ADVANCED,
            next_order_index=next_order_index,
            updated_at=self._now(),
        )
        self._cursor_store.save(new_cursor)
        return new_cursor

    def complete_cursor(self, cursor_id: str, next_order_index: int) -> ReplayTimelineCursor:
        """Mark cursor as COMPLETED when next_order_index equals timeline length."""
        if self._cursor_store is None:
            raise ValueError("cursor_store is required for cursor operations")
        cursor = self._cursor_store.load(cursor_id)
        if cursor is None:
            raise ValueError(f"cursor not found: {cursor_id!r}")
        timeline = self._timeline_store.load(cursor.timeline_id)
        if timeline is not None and next_order_index != len(timeline.events):
            raise ValueError("next_order_index must equal timeline event count to complete")
        now_ts = self._now()
        new_cursor = ReplayTimelineCursor(
            cursor_id=cursor.cursor_id,
            timeline_id=cursor.timeline_id,
            replay_plan_id=cursor.replay_plan_id,
            status=ReplayTimelineCursorStatus.COMPLETED,
            next_order_index=next_order_index,
            updated_at=now_ts,
            completed_at=now_ts,
        )
        self._cursor_store.save(new_cursor)
        return new_cursor

    def invalidate_cursor(self, cursor_id: str, reason: str) -> ReplayTimelineCursor:
        """Invalidate a cursor, storing the reason in notes."""
        if self._cursor_store is None:
            raise ValueError("cursor_store is required for cursor operations")
        cursor = self._cursor_store.load(cursor_id)
        if cursor is None:
            raise ValueError(f"cursor not found: {cursor_id!r}")
        new_cursor = ReplayTimelineCursor(
            cursor_id=cursor.cursor_id,
            timeline_id=cursor.timeline_id,
            replay_plan_id=cursor.replay_plan_id,
            status=ReplayTimelineCursorStatus.INVALIDATED,
            next_order_index=cursor.next_order_index,
            updated_at=self._now(),
            notes=reason,
        )
        self._cursor_store.save(new_cursor)
        return new_cursor
