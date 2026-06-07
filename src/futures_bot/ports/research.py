from __future__ import annotations

from typing import Protocol

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    EvaluationArtifactMetadata,
    EvaluationPlan,
    EvaluationResultSet,
    ReplayPlan,
    ResearchRunManifest,
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
