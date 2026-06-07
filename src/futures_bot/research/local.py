"""Local research run recorder.

No filesystem writes. No plotting. No DB. No Kafka. No runtime loops.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    EvaluationArtifactMetadata,
    EvaluationPlan,
    EvaluationResultSet,
    EvaluationResultStatus,
    ExpectedOutcomeAssessment,
    MetricObservation,
    ReplayDataSourceKind,
    ReplayPlan,
    ResearchRunManifest,
    ResearchRunStatus,
)
from futures_bot.ports.research import (
    EvaluationArtifactStorePort,
    EvaluationPlanStorePort,
    EvaluationResultStorePort,
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


class LocalEvaluationResultRecorder:
    """Metadata-only local recorder for evaluation observations and assessments."""

    def __init__(
        self,
        *,
        result_store: EvaluationResultStorePort,
        evaluation_plan_store: EvaluationPlanStorePort | None = None,
        artifact_store: EvaluationArtifactStorePort | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._result_store = result_store
        self._evaluation_plan_store = evaluation_plan_store
        self._artifact_store = artifact_store
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def create_result_set(self, result_set: EvaluationResultSet) -> EvaluationResultSet:
        """Save an evaluation result set."""
        self._result_store.save(result_set)
        return result_set

    def record_observation(
        self, result_set_id: str, observation: MetricObservation
    ) -> EvaluationResultSet:
        """Append a manually observed metric value; does not calculate metrics."""
        result_set = self._load_result_set(result_set_id)
        _ensure_result_set_mutable(result_set)
        _validate_observation_for_result_set(result_set, observation)
        self._validate_observation_against_plan(observation)
        updated = _rebuild_result_set(
            result_set,
            {
                "observations": (*result_set.observations, observation),
                "updated_at": self._now(),
            },
        )
        self._result_store.save(updated)
        return updated

    def record_assessment(
        self,
        result_set_id: str,
        assessment: ExpectedOutcomeAssessment,
    ) -> EvaluationResultSet:
        """Append a manual expected-vs-observed assessment."""
        result_set = self._load_result_set(result_set_id)
        _ensure_result_set_mutable(result_set)
        _validate_assessment_for_result_set(result_set, assessment)
        self._validate_assessment_against_plan(assessment)
        updated = _rebuild_result_set(
            result_set,
            {
                "assessments": (*result_set.assessments, assessment),
                "updated_at": self._now(),
            },
        )
        self._result_store.save(updated)
        return updated

    def attach_artifact(self, result_set_id: str, artifact_id: str) -> EvaluationResultSet:
        """Attach existing artifact metadata by ID."""
        if not artifact_id or artifact_id != artifact_id.strip():
            raise ValueError("artifact_id must be a non-empty trimmed string")
        if self._artifact_store is not None and self._artifact_store.load(artifact_id) is None:
            raise KeyError(f"evaluation artifact not found: {artifact_id}")

        result_set = self._load_result_set(result_set_id)
        _ensure_result_set_mutable(result_set)
        artifact_ids = result_set.artifact_ids
        if artifact_id not in artifact_ids:
            artifact_ids = (*artifact_ids, artifact_id)
        updated = _rebuild_result_set(
            result_set,
            {
                "artifact_ids": artifact_ids,
                "updated_at": self._now(),
            },
        )
        self._result_store.save(updated)
        return updated

    def mark_recorded(self, result_set_id: str) -> EvaluationResultSet:
        """Mark a result set as recorded."""
        return self._update_status(result_set_id, EvaluationResultStatus.RECORDED)

    def mark_reviewed(self, result_set_id: str) -> EvaluationResultSet:
        """Mark a result set as reviewed."""
        return self._update_status(result_set_id, EvaluationResultStatus.REVIEWED)

    def invalidate(self, result_set_id: str, reason: str) -> EvaluationResultSet:
        """Invalidate a result set and preserve the reason in notes."""
        return self._update_status(
            result_set_id,
            EvaluationResultStatus.INVALIDATED,
            reason=reason,
        )

    def result_sets_for_run(self, run_id: RunId) -> tuple[EvaluationResultSet, ...]:
        """Return result sets for run_id."""
        return self._result_store.list_for_run(run_id)

    def result_sets_for_evaluation_plan(
        self, evaluation_plan_id: str
    ) -> tuple[EvaluationResultSet, ...]:
        """Return result sets for evaluation_plan_id."""
        return self._result_store.list_for_evaluation_plan(evaluation_plan_id)

    def _update_status(
        self,
        result_set_id: str,
        status: EvaluationResultStatus,
        *,
        reason: str | None = None,
    ) -> EvaluationResultSet:
        result_set = self._load_result_set(result_set_id)
        _validate_result_status_transition(result_set.status, status)
        updated = _rebuild_result_set(
            result_set,
            {
                "status": status,
                "updated_at": self._now(),
                "notes": _append_reason(result_set.notes, reason),
            },
        )
        self._result_store.save(updated)
        return updated

    def _load_result_set(self, result_set_id: str) -> EvaluationResultSet:
        result_set = self._result_store.load(result_set_id)
        if result_set is None:
            raise KeyError(f"evaluation result set not found: {result_set_id}")
        return result_set

    def _load_evaluation_plan(self, evaluation_plan_id: str) -> EvaluationPlan | None:
        if self._evaluation_plan_store is None:
            return None
        plan = self._evaluation_plan_store.load(evaluation_plan_id)
        if plan is None:
            raise KeyError(f"evaluation plan not found: {evaluation_plan_id}")
        return plan

    def _validate_observation_against_plan(
        self, observation: MetricObservation
    ) -> None:
        plan = self._load_evaluation_plan(observation.evaluation_plan_id)
        if plan is None:
            return
        metric_ids = {metric.metric_id for metric in plan.metric_specs}
        if observation.metric_id not in metric_ids:
            raise ValueError("observation metric_id is not declared in EvaluationPlan")
        if observation.cost_scenario_id is not None:
            scenario_ids = {scenario.scenario_id for scenario in plan.cost_scenarios}
            if observation.cost_scenario_id not in scenario_ids:
                raise ValueError(
                    "observation cost_scenario_id is not declared in EvaluationPlan"
                )

    def _validate_assessment_against_plan(
        self, assessment: ExpectedOutcomeAssessment
    ) -> None:
        plan = self._load_evaluation_plan(assessment.evaluation_plan_id)
        if plan is None or not plan.expected_outcome_ids:
            return
        if assessment.setup_id not in plan.expected_outcome_ids:
            raise ValueError(
                "assessment setup_id is not declared in EvaluationPlan expected outcomes"
            )


def _rebuild_result_set(
    result_set: EvaluationResultSet,
    updates: Mapping[str, object],
) -> EvaluationResultSet:
    """Recreate result sets through Pydantic validation after local mutations."""
    payload: dict[str, object] = {
        "result_set_id": result_set.result_set_id,
        "run_id": result_set.run_id,
        "evaluation_plan_id": result_set.evaluation_plan_id,
        "status": result_set.status,
        "created_at": result_set.created_at,
        "updated_at": result_set.updated_at,
        "observations": result_set.observations,
        "assessments": result_set.assessments,
        "artifact_ids": result_set.artifact_ids,
        "notes": result_set.notes,
    }
    payload.update(updates)
    return EvaluationResultSet.model_validate(payload)


def _ensure_result_set_mutable(result_set: EvaluationResultSet) -> None:
    if result_set.status in {
        EvaluationResultStatus.REVIEWED,
        EvaluationResultStatus.INVALIDATED,
    }:
        raise ValueError(
            "reviewed or invalidated evaluation result sets cannot be mutated"
        )


def _validate_observation_for_result_set(
    result_set: EvaluationResultSet,
    observation: MetricObservation,
) -> None:
    if observation.run_id != result_set.run_id:
        raise ValueError("observation run_id must match result set run_id")
    if observation.evaluation_plan_id != result_set.evaluation_plan_id:
        raise ValueError(
            "observation evaluation_plan_id must match result set evaluation_plan_id"
        )
    if any(
        existing.observation_id == observation.observation_id
        for existing in result_set.observations
    ):
        raise ValueError("duplicate observation_id values are not allowed")


def _validate_assessment_for_result_set(
    result_set: EvaluationResultSet,
    assessment: ExpectedOutcomeAssessment,
) -> None:
    if assessment.run_id != result_set.run_id:
        raise ValueError("assessment run_id must match result set run_id")
    if assessment.evaluation_plan_id != result_set.evaluation_plan_id:
        raise ValueError(
            "assessment evaluation_plan_id must match result set evaluation_plan_id"
        )
    if any(
        existing.assessment_id == assessment.assessment_id
        for existing in result_set.assessments
    ):
        raise ValueError("duplicate assessment_id values are not allowed")


def _validate_result_status_transition(
    current: EvaluationResultStatus,
    target: EvaluationResultStatus,
) -> None:
    if current is target:
        return
    if current is EvaluationResultStatus.INVALIDATED:
        raise ValueError(
            f"invalid evaluation result status transition: {current} -> {target}"
        )
    if current is EvaluationResultStatus.REVIEWED:
        if target is EvaluationResultStatus.INVALIDATED:
            return
        raise ValueError(
            f"invalid evaluation result status transition: {current} -> {target}"
        )
    if target is EvaluationResultStatus.REVIEWED:
        if current is EvaluationResultStatus.RECORDED:
            return
        raise ValueError(
            "evaluation result sets must be RECORDED before they can be REVIEWED"
        )
    if target is EvaluationResultStatus.DRAFT:
        raise ValueError(
            f"invalid evaluation result status transition: {current} -> {target}"
        )
