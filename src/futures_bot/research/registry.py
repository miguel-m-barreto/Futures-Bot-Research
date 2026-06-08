"""Local metadata-only experiment registry service."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    ConfigBundle,
    ConfigSnapshot,
    ConfigSnapshotKind,
    ExperimentDefinition,
    RunLineageRecord,
)
from futures_bot.ports.research import (
    ConfigBundleStorePort,
    ConfigSnapshotStorePort,
    EvaluationPlanStorePort,
    ExperimentDefinitionStorePort,
    ReplayPlanStorePort,
    ResearchRunManifestStorePort,
    RunLineageStorePort,
)
from futures_bot.research.config_fingerprint import CanonicalConfigFingerprinter


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LocalExperimentRegistry:
    """Register experiments, config snapshots, and run lineage metadata."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        experiment_store: ExperimentDefinitionStorePort,
        config_store: ConfigSnapshotStorePort,
        lineage_store: RunLineageStorePort,
        config_bundle_store: ConfigBundleStorePort | None = None,
        fingerprinter: CanonicalConfigFingerprinter | None = None,
        manifest_store: ResearchRunManifestStorePort | None = None,
        replay_plan_store: ReplayPlanStorePort | None = None,
        evaluation_plan_store: EvaluationPlanStorePort | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._experiment_store = experiment_store
        self._config_store = config_store
        self._lineage_store = lineage_store
        self._config_bundle_store = config_bundle_store
        self._fingerprinter = (
            fingerprinter if fingerprinter is not None else CanonicalConfigFingerprinter()
        )
        self._manifest_store = manifest_store
        self._replay_plan_store = replay_plan_store
        self._evaluation_plan_store = evaluation_plan_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def register_experiment(
        self, experiment: ExperimentDefinition
    ) -> ExperimentDefinition:
        """Save experiment metadata."""
        self._experiment_store.save(experiment)
        return experiment

    def register_config_snapshot(self, snapshot: ConfigSnapshot) -> ConfigSnapshot:
        """Save canonical config snapshot metadata."""
        self._config_store.save(snapshot)
        return snapshot

    def register_config_bundle(self, bundle: ConfigBundle) -> ConfigBundle:
        """Save composed config bundle metadata."""
        self._require_config_bundle_store().save(bundle)
        return bundle

    def fingerprint_config(
        self,
        *,
        config_id: str,
        kind: ConfigSnapshotKind,
        payload: Mapping[str, object],
        description: str | None = None,
    ) -> ConfigSnapshot:
        """Create and save a deterministic config snapshot from payload metadata."""
        snapshot = self._fingerprinter.snapshot(
            config_id=config_id,
            kind=kind,
            payload=payload,
            created_at=self._now(),
            description=description,
        )
        self._config_store.save(snapshot)
        return snapshot

    def compose_config_bundle(
        self,
        *,
        bundle_id: str,
        config_ids: tuple[str, ...],
        description: str | None = None,
    ) -> ConfigBundle:
        """Compose and save a deterministic bundle from stored config snapshots."""
        bundle_store = self._require_config_bundle_store()
        if not config_ids:
            raise ValueError("config_ids must be non-empty")
        if len(set(config_ids)) != len(config_ids):
            raise ValueError("duplicate config_id values are not allowed")
        snapshots: list[ConfigSnapshot] = []
        for config_id in config_ids:
            snapshot = self._config_store.load(config_id)
            if snapshot is None:
                raise KeyError(f"config snapshot not found: {config_id}")
            snapshots.append(snapshot)
        bundle = self._fingerprinter.bundle(
            bundle_id=bundle_id,
            snapshots=tuple(snapshots),
            created_at=self._now(),
            description=description,
        )
        bundle_store.save(bundle)
        return bundle

    def load_config_bundle(self, bundle_id: str) -> ConfigBundle | None:
        """Return stored config bundle metadata by bundle_id."""
        return self._require_config_bundle_store().load(bundle_id)

    def register_lineage(self, record: RunLineageRecord) -> RunLineageRecord:
        """Validate references and save run lineage metadata."""
        self.validate_lineage_references(record)
        self._lineage_store.save(record)
        return record

    def lineage_for_run(self, run_id: RunId) -> tuple[RunLineageRecord, ...]:
        """Return lineage records for run_id."""
        return self._lineage_store.list_for_run(run_id)

    def lineage_for_experiment(
        self, experiment_id: str
    ) -> tuple[RunLineageRecord, ...]:
        """Return lineage records for experiment_id."""
        return self._lineage_store.list_for_experiment(experiment_id)

    def configs_for_lineage(self, lineage_id: str) -> tuple[ConfigSnapshot, ...]:
        """Return config snapshots in the order recorded by lineage metadata."""
        record = self._lineage_store.load(lineage_id)
        if record is None:
            raise KeyError(f"run lineage record not found: {lineage_id}")
        snapshots: list[ConfigSnapshot] = []
        for config_id in record.config_ids:
            snapshot = self._config_store.load(config_id)
            if snapshot is None:
                raise KeyError(f"config snapshot not found: {config_id}")
            snapshots.append(snapshot)
        return tuple(snapshots)

    def validate_lineage_references(self, record: RunLineageRecord) -> None:
        """Validate metadata references without executing replay or reading files."""
        if self._experiment_store.load(record.experiment_id) is None:
            raise KeyError(f"experiment not found: {record.experiment_id}")
        for config_id in record.config_ids:
            if self._config_store.load(config_id) is None:
                raise KeyError(f"config snapshot not found: {config_id}")
        if (
            record.config_bundle_id is not None
            and self._config_bundle_store is not None
            and self._config_bundle_store.load(record.config_bundle_id) is None
        ):
            raise KeyError(f"config bundle not found: {record.config_bundle_id}")
        if (
            self._manifest_store is not None
            and self._manifest_store.load(record.run_id) is None
        ):
            raise KeyError(f"research run manifest not found: {record.run_id!s}")
        if (
            record.replay_plan_id is not None
            and self._replay_plan_store is not None
            and self._replay_plan_store.load(record.replay_plan_id) is None
        ):
            raise KeyError(f"replay plan not found: {record.replay_plan_id}")
        if (
            record.evaluation_plan_id is not None
            and self._evaluation_plan_store is not None
            and self._evaluation_plan_store.load(record.evaluation_plan_id) is None
        ):
            raise KeyError(f"evaluation plan not found: {record.evaluation_plan_id}")

    def _require_config_bundle_store(self) -> ConfigBundleStorePort:
        if self._config_bundle_store is None:
            raise ValueError("config_bundle_store is required")
        return self._config_bundle_store
