"""In-memory research stores for local tests and contract validation.

No DB. No filesystem. No Kafka. No ML/data libraries.
"""
from __future__ import annotations

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    EvaluationArtifactMetadata,
    EvaluationPlan,
    EvaluationResultSet,
    EvaluationResultStatus,
    ReplayPlan,
    ResearchRunManifest,
    ResearchRunStatus,
)

_TERMINAL_STATUSES = frozenset(
    {
        ResearchRunStatus.COMPLETED,
        ResearchRunStatus.FAILED,
        ResearchRunStatus.INVALIDATED,
    }
)
_NON_TERMINAL_STATUSES = frozenset(
    {
        ResearchRunStatus.PLANNED,
        ResearchRunStatus.RUNNING,
    }
)

class InMemoryResearchRunManifestStore:
    """In-memory ResearchRunManifestStorePort implementation."""

    def __init__(self) -> None:
        self._manifests: dict[str, ResearchRunManifest] = {}

    def save(self, manifest: ResearchRunManifest) -> None:
        """Save manifest, enforcing updated_at and terminal status rules."""
        key = str(manifest.run_id)
        existing = self._manifests.get(key)
        if existing is not None:
            if manifest.updated_at < existing.updated_at:
                raise ValueError(
                    "manifest updated_at regression: "
                    f"existing {existing.updated_at.isoformat()}, "
                    f"new {manifest.updated_at.isoformat()}"
                )
            if (
                existing.status in _TERMINAL_STATUSES
                and manifest.status in _NON_TERMINAL_STATUSES
            ):
                raise ValueError(
                    f"invalid research run status transition: "
                    f"{existing.status} -> {manifest.status}"
                )
        self._manifests[key] = manifest

    def load(self, run_id: RunId) -> ResearchRunManifest | None:
        """Return manifest by run_id, or None."""
        return self._manifests.get(str(run_id))

    def list_all(self) -> tuple[ResearchRunManifest, ...]:
        """Return manifests sorted by created_at then run_id."""
        return tuple(
            sorted(
                self._manifests.values(),
                key=lambda manifest: (manifest.created_at, str(manifest.run_id)),
            )
        )


class InMemoryEvaluationArtifactStore:
    """In-memory EvaluationArtifactStorePort implementation."""

    def __init__(self) -> None:
        self._artifacts: dict[str, EvaluationArtifactMetadata] = {}

    def save(self, artifact: EvaluationArtifactMetadata) -> None:
        """Save artifact metadata, rejecting conflicting artifact IDs."""
        existing = self._artifacts.get(artifact.artifact_id)
        if existing is not None:
            if (
                existing.run_id != artifact.run_id
                or existing.kind != artifact.kind
                or existing.uri != artifact.uri
                or existing.content_hash != artifact.content_hash
            ):
                raise ValueError(
                    f"artifact_id conflict for {artifact.artifact_id!r}"
                )
            return
        self._artifacts[artifact.artifact_id] = artifact

    def load(self, artifact_id: str) -> EvaluationArtifactMetadata | None:
        """Return artifact metadata by artifact_id, or None."""
        return self._artifacts.get(artifact_id)

    def list_for_run(self, run_id: RunId) -> tuple[EvaluationArtifactMetadata, ...]:
        """Return artifacts for run_id sorted by created_at then artifact_id."""
        return tuple(
            sorted(
                (
                    artifact
                    for artifact in self._artifacts.values()
                    if artifact.run_id == run_id
                ),
                key=lambda artifact: (artifact.created_at, artifact.artifact_id),
            )
        )


class InMemoryReplayPlanStore:
    """In-memory ReplayPlanStorePort implementation."""

    def __init__(self) -> None:
        self._plans: dict[str, ReplayPlan] = {}

    def save(self, plan: ReplayPlan) -> None:
        """Save replay plan metadata, rejecting conflicting plan IDs."""
        existing = self._plans.get(plan.replay_plan_id)
        if existing is not None:
            if existing != plan:
                raise ValueError(
                    f"replay_plan_id conflict for {plan.replay_plan_id!r}"
                )
            return
        self._plans[plan.replay_plan_id] = plan

    def load(self, replay_plan_id: str) -> ReplayPlan | None:
        """Return replay plan by replay_plan_id, or None."""
        return self._plans.get(replay_plan_id)

    def list_for_run(self, run_id: RunId) -> tuple[ReplayPlan, ...]:
        """Return replay plans for run_id sorted by created_at then id."""
        return tuple(
            sorted(
                (
                    plan
                    for plan in self._plans.values()
                    if plan.run_id == run_id
                ),
                key=lambda plan: (plan.created_at, plan.replay_plan_id),
            )
        )


class InMemoryEvaluationPlanStore:
    """In-memory EvaluationPlanStorePort implementation."""

    def __init__(self) -> None:
        self._plans: dict[str, EvaluationPlan] = {}

    def save(self, plan: EvaluationPlan) -> None:
        """Save evaluation plan metadata, rejecting conflicting plan IDs."""
        existing = self._plans.get(plan.evaluation_plan_id)
        if existing is not None:
            if existing != plan:
                raise ValueError(
                    f"evaluation_plan_id conflict for {plan.evaluation_plan_id!r}"
                )
            return
        self._plans[plan.evaluation_plan_id] = plan

    def load(self, evaluation_plan_id: str) -> EvaluationPlan | None:
        """Return evaluation plan by evaluation_plan_id, or None."""
        return self._plans.get(evaluation_plan_id)

    def list_for_run(self, run_id: RunId) -> tuple[EvaluationPlan, ...]:
        """Return evaluation plans for run_id sorted by created_at then id."""
        return tuple(
            sorted(
                (
                    plan
                    for plan in self._plans.values()
                    if plan.run_id == run_id
                ),
                key=lambda plan: (plan.created_at, plan.evaluation_plan_id),
            )
        )


class InMemoryEvaluationResultStore:
    """In-memory EvaluationResultStorePort implementation."""

    def __init__(self) -> None:
        self._result_sets: dict[str, EvaluationResultSet] = {}

    def save(self, result_set: EvaluationResultSet) -> None:
        """Save result set metadata with timestamp and terminal status rules."""
        result_set = EvaluationResultSet.model_validate(result_set.model_dump())
        existing = self._result_sets.get(result_set.result_set_id)
        if existing is not None:
            if result_set.run_id != existing.run_id:
                raise ValueError("result_set_id conflict: run_id mismatch")
            if result_set.evaluation_plan_id != existing.evaluation_plan_id:
                raise ValueError("result_set_id conflict: evaluation_plan_id mismatch")
            if result_set.updated_at < existing.updated_at:
                raise ValueError(
                    "result set updated_at regression: "
                    f"existing {existing.updated_at.isoformat()}, "
                    f"new {result_set.updated_at.isoformat()}"
                )
            _validate_result_status_transition(existing.status, result_set.status)
            _validate_terminal_content_immutability(existing, result_set)
        self._result_sets[result_set.result_set_id] = result_set

    def load(self, result_set_id: str) -> EvaluationResultSet | None:
        """Return result set by result_set_id, or None."""
        return self._result_sets.get(result_set_id)

    def list_for_run(self, run_id: RunId) -> tuple[EvaluationResultSet, ...]:
        """Return result sets for run_id sorted by created_at then id."""
        return tuple(
            sorted(
                (
                    result_set
                    for result_set in self._result_sets.values()
                    if result_set.run_id == run_id
                ),
                key=lambda result_set: (result_set.created_at, result_set.result_set_id),
            )
        )

    def list_for_evaluation_plan(
        self, evaluation_plan_id: str
    ) -> tuple[EvaluationResultSet, ...]:
        """Return result sets for evaluation_plan_id sorted by created_at then id."""
        return tuple(
            sorted(
                (
                    result_set
                    for result_set in self._result_sets.values()
                    if result_set.evaluation_plan_id == evaluation_plan_id
                ),
                key=lambda result_set: (result_set.created_at, result_set.result_set_id),
            )
        )


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


def _validate_terminal_content_immutability(
    existing: EvaluationResultSet,
    candidate: EvaluationResultSet,
) -> None:
    if existing.status is EvaluationResultStatus.INVALIDATED:
        if candidate != existing:
            raise ValueError("invalidated evaluation result sets are immutable")
        return

    if existing.status is not EvaluationResultStatus.REVIEWED:
        return

    if candidate.status is EvaluationResultStatus.REVIEWED:
        if candidate != existing:
            raise ValueError("reviewed evaluation result sets are immutable")
        return

    if (
        candidate.status is EvaluationResultStatus.INVALIDATED
        and not _same_result_payload_except_status_notes_and_updated_at(
            existing, candidate
        )
    ):
        raise ValueError(
            "reviewed evaluation result sets can only be invalidated "
            "without changing observations, assessments, or artifacts"
        )


def _same_result_payload_except_status_notes_and_updated_at(
    left: EvaluationResultSet,
    right: EvaluationResultSet,
) -> bool:
    return (
        left.result_set_id == right.result_set_id
        and left.run_id == right.run_id
        and left.evaluation_plan_id == right.evaluation_plan_id
        and left.created_at == right.created_at
        and left.observations == right.observations
        and left.assessments == right.assessments
        and left.artifact_ids == right.artifact_ids
    )
