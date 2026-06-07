from __future__ import annotations

from typing import Protocol

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    ConfigSnapshot,
    ConfigSnapshotKind,
    EvaluationArtifactMetadata,
    EvaluationPlan,
    EvaluationResultSet,
    ExperimentDefinition,
    ReplayPlan,
    ResearchRunManifest,
    RunLineageRecord,
)


class ResearchRunManifestStorePort(Protocol):
    """Persistence abstraction for research run manifests."""

    def save(self, manifest: ResearchRunManifest) -> None:
        """Persist a research run manifest."""
        ...

    def load(self, run_id: RunId) -> ResearchRunManifest | None:
        """Return manifest by run_id, or None."""
        ...

    def list_all(self) -> tuple[ResearchRunManifest, ...]:
        """Return all manifests in deterministic order."""
        ...


class EvaluationArtifactStorePort(Protocol):
    """Persistence abstraction for evaluation artifact metadata."""

    def save(self, artifact: EvaluationArtifactMetadata) -> None:
        """Persist evaluation artifact metadata."""
        ...

    def load(self, artifact_id: str) -> EvaluationArtifactMetadata | None:
        """Return artifact metadata by artifact_id, or None."""
        ...

    def list_for_run(self, run_id: RunId) -> tuple[EvaluationArtifactMetadata, ...]:
        """Return artifact metadata for run_id in deterministic order."""
        ...


class ReplayPlanStorePort(Protocol):
    """Persistence abstraction for replay plan metadata."""

    def save(self, plan: ReplayPlan) -> None:
        """Persist replay plan metadata."""
        ...

    def load(self, replay_plan_id: str) -> ReplayPlan | None:
        """Return replay plan by replay_plan_id, or None."""
        ...

    def list_for_run(self, run_id: RunId) -> tuple[ReplayPlan, ...]:
        """Return replay plans for run_id in deterministic order."""
        ...


class EvaluationPlanStorePort(Protocol):
    """Persistence abstraction for evaluation plan metadata."""

    def save(self, plan: EvaluationPlan) -> None:
        """Persist evaluation plan metadata."""
        ...

    def load(self, evaluation_plan_id: str) -> EvaluationPlan | None:
        """Return evaluation plan by evaluation_plan_id, or None."""
        ...

    def list_for_run(self, run_id: RunId) -> tuple[EvaluationPlan, ...]:
        """Return evaluation plans for run_id in deterministic order."""
        ...


class EvaluationResultStorePort(Protocol):
    """Persistence abstraction for evaluation result set metadata."""

    def save(self, result_set: EvaluationResultSet) -> None:
        """Persist evaluation result set metadata."""
        ...

    def load(self, result_set_id: str) -> EvaluationResultSet | None:
        """Return result set by result_set_id, or None."""
        ...

    def list_for_run(self, run_id: RunId) -> tuple[EvaluationResultSet, ...]:
        """Return result sets for run_id in deterministic order."""
        ...

    def list_for_evaluation_plan(
        self, evaluation_plan_id: str
    ) -> tuple[EvaluationResultSet, ...]:
        """Return result sets for evaluation_plan_id in deterministic order."""
        ...


class ExperimentDefinitionStorePort(Protocol):
    """Persistence abstraction for experiment definitions."""

    def save(self, experiment: ExperimentDefinition) -> None:
        """Persist experiment metadata."""
        ...

    def load(self, experiment_id: str) -> ExperimentDefinition | None:
        """Return experiment by experiment_id, or None."""
        ...

    def list_all(self) -> tuple[ExperimentDefinition, ...]:
        """Return experiments in deterministic order."""
        ...


class ConfigSnapshotStorePort(Protocol):
    """Persistence abstraction for canonical config snapshots."""

    def save(self, snapshot: ConfigSnapshot) -> None:
        """Persist config snapshot metadata."""
        ...

    def load(self, config_id: str) -> ConfigSnapshot | None:
        """Return config snapshot by config_id, or None."""
        ...

    def list_by_kind(self, kind: ConfigSnapshotKind) -> tuple[ConfigSnapshot, ...]:
        """Return config snapshots by kind in deterministic order."""
        ...

    def list_all(self) -> tuple[ConfigSnapshot, ...]:
        """Return config snapshots in deterministic order."""
        ...


class RunLineageStorePort(Protocol):
    """Persistence abstraction for run lineage records."""

    def save(self, record: RunLineageRecord) -> None:
        """Persist lineage metadata."""
        ...

    def load(self, lineage_id: str) -> RunLineageRecord | None:
        """Return lineage record by lineage_id, or None."""
        ...

    def list_for_run(self, run_id: RunId) -> tuple[RunLineageRecord, ...]:
        """Return lineage records for run_id in deterministic order."""
        ...

    def list_for_experiment(
        self, experiment_id: str
    ) -> tuple[RunLineageRecord, ...]:
        """Return lineage records for experiment_id in deterministic order."""
        ...
