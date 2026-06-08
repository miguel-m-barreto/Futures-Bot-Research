"""In-memory replay input stores.

No DB. No filesystem. No Kafka. No market data loading.
"""
from __future__ import annotations

from futures_bot.domain.replay import ReplayInputBatch, ReplayInputDataset


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
