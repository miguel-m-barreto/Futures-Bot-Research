"""Local metadata-only replay input planner.

No file IO. No market data loading. No replay execution.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from futures_bot.domain.ids import RunId
from futures_bot.domain.replay import ReplayInputBatch, ReplayInputDataset
from futures_bot.domain.research import ReplayDataSourceKind
from futures_bot.ports.replay import (
    ReplayInputBatchStorePort,
    ReplayInputDatasetStorePort,
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
