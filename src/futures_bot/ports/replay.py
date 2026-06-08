from __future__ import annotations

from typing import Protocol

from futures_bot.domain.replay import (
    ReplayInputBatch,
    ReplayInputDataset,
    ReplayTimeline,
    ReplayTimelineCursor,
)


class ReplayInputDatasetStorePort(Protocol):
    """Persistence abstraction for replay input dataset metadata."""

    def save(self, dataset: ReplayInputDataset) -> None:
        """Persist replay input dataset metadata."""
        ...

    def load(self, input_dataset_id: str) -> ReplayInputDataset | None:
        """Return replay input dataset by input_dataset_id, or None."""
        ...

    def list_for_dataset(self, dataset_id: str) -> tuple[ReplayInputDataset, ...]:
        """Return input datasets for dataset_id in deterministic order."""
        ...

    def list_all(self) -> tuple[ReplayInputDataset, ...]:
        """Return all input datasets in deterministic order."""
        ...


class ReplayInputBatchStorePort(Protocol):
    """Persistence abstraction for replay input batch metadata."""

    def save(self, batch: ReplayInputBatch) -> None:
        """Persist replay input batch metadata."""
        ...

    def load(self, batch_id: str) -> ReplayInputBatch | None:
        """Return replay input batch by batch_id, or None."""
        ...

    def list_for_replay_plan(self, replay_plan_id: str) -> tuple[ReplayInputBatch, ...]:
        """Return input batches for replay_plan_id in deterministic order."""
        ...

    def list_for_input_dataset(
        self, input_dataset_id: str
    ) -> tuple[ReplayInputBatch, ...]:
        """Return input batches for input_dataset_id in deterministic order."""
        ...


class ReplayTimelineStorePort(Protocol):
    """Persistence abstraction for replay timeline metadata."""

    def save(self, timeline: ReplayTimeline) -> None:
        """Persist replay timeline metadata."""
        ...

    def load(self, timeline_id: str) -> ReplayTimeline | None:
        """Return replay timeline by timeline_id, or None."""
        ...

    def list_for_replay_plan(self, replay_plan_id: str) -> tuple[ReplayTimeline, ...]:
        """Return replay timelines for replay_plan_id in deterministic order."""
        ...


class ReplayTimelineCursorStorePort(Protocol):
    """Persistence abstraction for replay timeline cursor metadata."""

    def save(self, cursor: ReplayTimelineCursor) -> None:
        """Persist replay timeline cursor metadata."""
        ...

    def load(self, cursor_id: str) -> ReplayTimelineCursor | None:
        """Return cursor by cursor_id, or None."""
        ...

    def list_for_timeline(self, timeline_id: str) -> tuple[ReplayTimelineCursor, ...]:
        """Return cursors for timeline_id in deterministic order."""
        ...
