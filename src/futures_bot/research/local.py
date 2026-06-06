"""Local research run recorder.

No filesystem writes. No plotting. No DB. No Kafka. No runtime loops.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    EvaluationArtifactMetadata,
    EvaluationPlan,
    ReplayDataSourceKind,
    ReplayPlan,
    ResearchRunManifest,
    ResearchRunStatus,
)
from futures_bot.ports.research import (
    EvaluationArtifactStorePort,
    EvaluationPlanStorePort,
    ReplayPlanStorePort,
    ResearchRunManifestStorePort,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LocalResearchRunRecorder:
    """Metadata-only local recorder for research/evaluation run reproducibility."""

    def __init__(
        self,
        *,
        manifest_store: ResearchRunManifestStorePort,
        artifact_store: EvaluationArtifactStorePort,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._manifest_store = manifest_store
        self._artifact_store = artifact_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def create_manifest(self, manifest: ResearchRunManifest) -> ResearchRunManifest:
        """Save a planned research run manifest."""
        self._manifest_store.save(manifest)
        return manifest

    def mark_running(self, run_id: RunId) -> ResearchRunManifest:
        """Mark a research run as running."""
        return self._update_status(run_id, ResearchRunStatus.RUNNING)

    def mark_completed(self, run_id: RunId) -> ResearchRunManifest:
        """Mark a research run as completed."""
        return self._update_status(run_id, ResearchRunStatus.COMPLETED)

    def mark_failed(self, run_id: RunId, reason: str) -> ResearchRunManifest:
        """Mark a research run as failed and include reason in notes."""
        return self._update_status(
            run_id,
            ResearchRunStatus.FAILED,
            reason=reason,
        )

    def invalidate(self, run_id: RunId, reason: str) -> ResearchRunManifest:
        """Mark a research run as invalidated and include reason in notes."""
        return self._update_status(
            run_id,
            ResearchRunStatus.INVALIDATED,
            reason=reason,
        )

    def record_artifact(
        self, artifact: EvaluationArtifactMetadata
    ) -> EvaluationArtifactMetadata:
        """Record artifact metadata only; does not write artifact files."""
        self._artifact_store.save(artifact)
        return artifact

    def artifacts_for_run(self, run_id: RunId) -> tuple[EvaluationArtifactMetadata, ...]:
        """Return recorded artifact metadata for run_id."""
        return self._artifact_store.list_for_run(run_id)

    def _update_status(
        self,
        run_id: RunId,
        status: ResearchRunStatus,
        *,
        reason: str | None = None,
    ) -> ResearchRunManifest:
        manifest = self._manifest_store.load(run_id)
        if manifest is None:
            raise KeyError(f"research run manifest not found: {run_id!s}")

        updated = manifest.model_copy(
            update={
                "status": status,
                "updated_at": self._now(),
                "notes": _append_reason(manifest.notes, reason),
            }
        )
        self._manifest_store.save(updated)
        return updated


def _append_reason(existing_notes: str | None, reason: str | None) -> str | None:
    if reason is None:
        return existing_notes
    if not reason or reason != reason.strip():
        raise ValueError("reason must be a non-empty trimmed string")
    if existing_notes is None:
        return reason
    return f"{existing_notes}\n{reason}"


class LocalResearchPlanner:
    """Metadata-only local planner for replay and evaluation plans."""

    def __init__(
        self,
        *,
        replay_plan_store: ReplayPlanStorePort,
        evaluation_plan_store: EvaluationPlanStorePort,
        manifest_store: ResearchRunManifestStorePort | None = None,
    ) -> None:
        self._replay_plan_store = replay_plan_store
        self._evaluation_plan_store = evaluation_plan_store
        self._manifest_store = manifest_store

    def create_replay_plan(self, plan: ReplayPlan) -> ReplayPlan:
        """Validate and save replay plan metadata."""
        self.validate_plan_against_manifest(plan)
        self._replay_plan_store.save(plan)
        return plan

    def create_evaluation_plan(self, plan: EvaluationPlan) -> EvaluationPlan:
        """Save evaluation plan metadata."""
        self._evaluation_plan_store.save(plan)
        return plan

    def replay_plans_for_run(self, run_id: RunId) -> tuple[ReplayPlan, ...]:
        """Return replay plans for run_id."""
        return self._replay_plan_store.list_for_run(run_id)

    def evaluation_plans_for_run(self, run_id: RunId) -> tuple[EvaluationPlan, ...]:
        """Return evaluation plans for run_id."""
        return self._evaluation_plan_store.list_for_run(run_id)

    def validate_plan_against_manifest(self, replay_plan: ReplayPlan) -> None:
        """Validate replay plan metadata against the run manifest, if available."""
        if self._manifest_store is None:
            return

        manifest = self._manifest_store.load(replay_plan.run_id)
        if manifest is None:
            raise KeyError(
                f"research run manifest not found: {replay_plan.run_id!s}"
            )

        if (
            replay_plan.data_source_kind is ReplayDataSourceKind.DATASET_SNAPSHOT
            and replay_plan.dataset_id != manifest.dataset.dataset_id
        ):
            raise ValueError(
                "replay plan dataset_id must match manifest dataset_id"
            )

        for window in replay_plan.temporal_windows:
            if (
                window.start_at < manifest.dataset.start_at
                or window.end_at > manifest.dataset.end_at
            ):
                raise ValueError(
                    "replay plan temporal windows must be within manifest dataset range"
                )
