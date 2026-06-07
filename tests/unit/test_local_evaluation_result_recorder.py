from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    CostScenario,
    EvaluationArtifactKind,
    EvaluationArtifactMetadata,
    EvaluationObjective,
    EvaluationPlan,
    EvaluationResultSet,
    EvaluationResultStatus,
    ExpectedOutcomeAssessment,
    ExpectedOutcomeAssessmentStatus,
    MetricDirection,
    MetricObservation,
    MetricSpec,
)
from futures_bot.infrastructure.research.in_memory import (
    InMemoryEvaluationArtifactStore,
    InMemoryEvaluationPlanStore,
    InMemoryEvaluationResultStore,
)
from futures_bot.research.local import LocalEvaluationResultRecorder


def _utc(day: int = 1, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def _evaluation_plan() -> EvaluationPlan:
    return EvaluationPlan(
        evaluation_plan_id="eval-1",
        run_id=RunId("run-1"),
        replay_plan_id="replay-1",
        objective=EvaluationObjective.BASELINE_COMPARISON,
        metric_specs=(
            MetricSpec(
                metric_id="pnl_after_costs",
                name="PnL after costs",
                direction=MetricDirection.MAXIMIZE,
                is_primary=True,
            ),
            MetricSpec(
                metric_id="turnover",
                name="Turnover",
                direction=MetricDirection.INFORMATION_ONLY,
            ),
        ),
        cost_scenarios=(CostScenario(scenario_id="baseline-costs"),),
        created_at=_utc(),
        expected_outcome_ids=("CONTROL/random",),
    )


def _result_set() -> EvaluationResultSet:
    return EvaluationResultSet(
        result_set_id="result-set-1",
        run_id=RunId("run-1"),
        evaluation_plan_id="eval-1",
        status=EvaluationResultStatus.DRAFT,
        created_at=_utc(2),
        updated_at=_utc(2),
    )


def _observation(
    observation_id: str = "obs-1",
    *,
    metric_id: str = "pnl_after_costs",
    cost_scenario_id: str | None = "baseline-costs",
) -> MetricObservation:
    return MetricObservation(
        observation_id=observation_id,
        run_id=RunId("run-1"),
        evaluation_plan_id="eval-1",
        metric_id=metric_id,
        observed_at=_utc(3),
        value=Decimal("-3.5"),
        unit="bps",
        cost_scenario_id=cost_scenario_id,
    )


def _assessment(setup_id: str = "CONTROL/random") -> ExpectedOutcomeAssessment:
    return ExpectedOutcomeAssessment(
        assessment_id="assessment-1",
        run_id=RunId("run-1"),
        evaluation_plan_id="eval-1",
        setup_id=setup_id,
        status=ExpectedOutcomeAssessmentStatus.CONFIRMED,
        assessed_at=_utc(3),
        rationale="Negative pnl after realistic costs supports the expectation.",
        related_observation_ids=("obs-1",),
    )


def _recorder(
    *,
    evaluation_plan_store: InMemoryEvaluationPlanStore | None = None,
    artifact_store: InMemoryEvaluationArtifactStore | None = None,
) -> tuple[LocalEvaluationResultRecorder, InMemoryEvaluationResultStore]:
    result_store = InMemoryEvaluationResultStore()
    recorder = LocalEvaluationResultRecorder(
        result_store=result_store,
        evaluation_plan_store=evaluation_plan_store,
        artifact_store=artifact_store,
        now=lambda: _utc(4),
    )
    return recorder, result_store


def test_create_result_set_saves_draft() -> None:
    recorder, result_store = _recorder()
    result_set = recorder.create_result_set(_result_set())
    assert result_store.load("result-set-1") == result_set
    assert result_set.status is EvaluationResultStatus.DRAFT


def test_record_observation_appends_observation() -> None:
    recorder, _ = _recorder()
    recorder.create_result_set(_result_set())
    updated = recorder.record_observation("result-set-1", _observation())
    assert updated.observations == (_observation(),)
    assert updated.updated_at == _utc(4)


def test_record_observation_rejects_result_set_context_mismatch() -> None:
    recorder, _ = _recorder()
    recorder.create_result_set(_result_set())

    with pytest.raises(ValueError, match="observation run_id"):
        recorder.record_observation(
            "result-set-1",
            _observation().model_copy(update={"run_id": RunId("other-run")}),
        )
    with pytest.raises(ValueError, match="observation evaluation_plan_id"):
        recorder.record_observation(
            "result-set-1",
            _observation().model_copy(update={"evaluation_plan_id": "other-plan"}),
        )


def test_record_observation_rejects_duplicate_observation_id() -> None:
    recorder, _ = _recorder()
    recorder.create_result_set(_result_set())
    recorder.record_observation("result-set-1", _observation())

    with pytest.raises(ValueError, match="duplicate observation_id"):
        recorder.record_observation("result-set-1", _observation())


def test_record_observation_validates_metric_id_against_plan() -> None:
    plan_store = InMemoryEvaluationPlanStore()
    plan_store.save(_evaluation_plan())
    recorder, _ = _recorder(evaluation_plan_store=plan_store)
    recorder.create_result_set(_result_set())
    with pytest.raises(ValueError, match="metric_id"):
        recorder.record_observation(
            "result-set-1", _observation(metric_id="undeclared_metric")
        )


def test_record_observation_validates_cost_scenario_id_against_plan() -> None:
    plan_store = InMemoryEvaluationPlanStore()
    plan_store.save(_evaluation_plan())
    recorder, _ = _recorder(evaluation_plan_store=plan_store)
    recorder.create_result_set(_result_set())
    with pytest.raises(ValueError, match="cost_scenario_id"):
        recorder.record_observation(
            "result-set-1", _observation(cost_scenario_id="undeclared-cost")
        )


def test_record_assessment_appends_assessment() -> None:
    recorder, _ = _recorder()
    recorder.create_result_set(_result_set())
    updated = recorder.record_assessment("result-set-1", _assessment())
    assert updated.assessments == (_assessment(),)


def test_record_assessment_rejects_result_set_context_mismatch() -> None:
    recorder, _ = _recorder()
    recorder.create_result_set(_result_set())

    with pytest.raises(ValueError, match="assessment run_id"):
        recorder.record_assessment(
            "result-set-1",
            _assessment().model_copy(update={"run_id": RunId("other-run")}),
        )
    with pytest.raises(ValueError, match="assessment evaluation_plan_id"):
        recorder.record_assessment(
            "result-set-1",
            _assessment().model_copy(update={"evaluation_plan_id": "other-plan"}),
        )


def test_record_assessment_rejects_duplicate_assessment_id() -> None:
    recorder, _ = _recorder()
    recorder.create_result_set(_result_set())
    recorder.record_assessment("result-set-1", _assessment())

    with pytest.raises(ValueError, match="duplicate assessment_id"):
        recorder.record_assessment("result-set-1", _assessment())


def test_record_assessment_validates_setup_id_against_expected_outcome_ids() -> None:
    plan_store = InMemoryEvaluationPlanStore()
    plan_store.save(_evaluation_plan())
    recorder, _ = _recorder(evaluation_plan_store=plan_store)
    recorder.create_result_set(_result_set())
    with pytest.raises(ValueError, match="setup_id"):
        recorder.record_assessment("result-set-1", _assessment("OTHER/setup"))


def test_attach_artifact_requires_existing_artifact_when_store_present() -> None:
    artifact_store = InMemoryEvaluationArtifactStore()
    artifact_store.save(
        EvaluationArtifactMetadata(
            artifact_id="artifact-1",
            run_id=RunId("run-1"),
            kind=EvaluationArtifactKind.REPORT,
            created_at=_utc(3),
            uri="memory://artifact-1",
        )
    )
    recorder, _ = _recorder(artifact_store=artifact_store)
    recorder.create_result_set(_result_set())
    updated = recorder.attach_artifact("result-set-1", "artifact-1")
    assert updated.artifact_ids == ("artifact-1",)
    with pytest.raises(KeyError, match="missing-artifact"):
        recorder.attach_artifact("result-set-1", "missing-artifact")


def test_status_updates_and_invalidate_notes() -> None:
    recorder, _ = _recorder()
    recorder.create_result_set(_result_set())
    recorded = recorder.mark_recorded("result-set-1")
    reviewed = recorder.mark_reviewed("result-set-1")
    assert recorded.status is EvaluationResultStatus.RECORDED
    assert reviewed.status is EvaluationResultStatus.REVIEWED

    recorder, _ = _recorder()
    recorder.create_result_set(_result_set())
    invalidated = recorder.invalidate("result-set-1", "Manual review found data issue.")
    assert invalidated.status is EvaluationResultStatus.INVALIDATED
    assert invalidated.notes is not None
    assert "Manual review" in invalidated.notes


def test_mark_reviewed_requires_recorded_status() -> None:
    recorder, _ = _recorder()
    recorder.create_result_set(_result_set())
    with pytest.raises(ValueError, match="RECORDED"):
        recorder.mark_reviewed("result-set-1")


def test_reviewed_result_set_can_be_invalidated_for_correction() -> None:
    recorder, _ = _recorder()
    recorder.create_result_set(_result_set())
    recorder.mark_recorded("result-set-1")
    recorder.mark_reviewed("result-set-1")

    invalidated = recorder.invalidate("result-set-1", "Post-review data issue.")

    assert invalidated.status is EvaluationResultStatus.INVALIDATED
    assert invalidated.notes is not None
    assert "Post-review data issue." in invalidated.notes


def test_terminal_result_sets_reject_new_observations_assessments_and_artifacts() -> None:
    recorder, _ = _recorder()
    recorder.create_result_set(_result_set())
    recorder.mark_recorded("result-set-1")
    recorder.mark_reviewed("result-set-1")

    with pytest.raises(ValueError, match="cannot be mutated"):
        recorder.record_observation("result-set-1", _observation())
    with pytest.raises(ValueError, match="cannot be mutated"):
        recorder.record_assessment("result-set-1", _assessment())
    with pytest.raises(ValueError, match="cannot be mutated"):
        recorder.attach_artifact("result-set-1", "artifact-1")

    recorder, _ = _recorder()
    recorder.create_result_set(_result_set())
    recorder.invalidate("result-set-1", "Invalid source data.")
    with pytest.raises(ValueError, match="cannot be mutated"):
        recorder.record_observation("result-set-1", _observation())
    with pytest.raises(ValueError, match="cannot be mutated"):
        recorder.record_assessment("result-set-1", _assessment())
    with pytest.raises(ValueError, match="cannot be mutated"):
        recorder.attach_artifact("result-set-1", "artifact-1")


def test_missing_result_set_id_raises() -> None:
    recorder, _ = _recorder()
    with pytest.raises(KeyError, match="missing-result"):
        recorder.mark_recorded("missing-result")


def test_attach_artifact_rejects_empty_artifact_id() -> None:
    recorder, _ = _recorder()
    recorder.create_result_set(_result_set())
    with pytest.raises(ValueError, match="artifact_id"):
        recorder.attach_artifact("result-set-1", "")
