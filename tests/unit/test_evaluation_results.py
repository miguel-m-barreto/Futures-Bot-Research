from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    EvaluationResultSet,
    EvaluationResultStatus,
    ExpectedOutcomeAssessment,
    ExpectedOutcomeAssessmentStatus,
    MetricObservation,
    ObservationScope,
)


def _utc(day: int = 1) -> datetime:
    return datetime(2026, 1, day, tzinfo=UTC)


def _observation(
    observation_id: str = "obs-1",
    *,
    run_id: str = "run-1",
    evaluation_plan_id: str = "eval-1",
    metric_id: str = "pnl_after_costs",
    value: Decimal | str | int = Decimal("-12.5"),
) -> MetricObservation:
    return MetricObservation(
        observation_id=observation_id,
        run_id=RunId(run_id),
        evaluation_plan_id=evaluation_plan_id,
        metric_id=metric_id,
        observed_at=_utc(),
        value=value,
        unit="bps",
        scope=ObservationScope.COST_SCENARIO,
        cost_scenario_id="baseline-costs",
        fold_id="fold-001",
    )


def _assessment(
    assessment_id: str = "assessment-1",
    *,
    run_id: str = "run-1",
    evaluation_plan_id: str = "eval-1",
    status: ExpectedOutcomeAssessmentStatus = ExpectedOutcomeAssessmentStatus.CONFIRMED,
) -> ExpectedOutcomeAssessment:
    return ExpectedOutcomeAssessment(
        assessment_id=assessment_id,
        run_id=RunId(run_id),
        evaluation_plan_id=evaluation_plan_id,
        setup_id="CONTROL/random",
        status=status,
        assessed_at=_utc(),
        rationale="The manually recorded observations match the pre-declared expectation.",
        related_observation_ids=("obs-1",),
    )


def _result_set(
    *,
    observations: tuple[MetricObservation, ...] = (),
    assessments: tuple[ExpectedOutcomeAssessment, ...] = (),
    status: EvaluationResultStatus = EvaluationResultStatus.DRAFT,
) -> EvaluationResultSet:
    return EvaluationResultSet(
        result_set_id="result-set-1",
        run_id=RunId("run-1"),
        evaluation_plan_id="eval-1",
        status=status,
        created_at=_utc(),
        updated_at=_utc(),
        observations=observations,
        assessments=assessments,
    )


def test_valid_metric_observation_with_decimal_value() -> None:
    observation = _observation(value=Decimal("-1.25"))
    assert observation.value == Decimal("-1.25")


def test_metric_observation_rejects_float_value() -> None:
    with pytest.raises(ValidationError, match="not float"):
        _observation(value=1.25)


def test_metric_observation_rejects_empty_ids() -> None:
    with pytest.raises(ValidationError, match="field"):
        _observation(observation_id="")
    with pytest.raises(ValidationError, match="field"):
        _observation(evaluation_plan_id="")
    with pytest.raises(ValidationError, match="field"):
        _observation(metric_id="")


def test_expected_outcome_assessment_statuses_represent_result_quality() -> None:
    for status in (
        ExpectedOutcomeAssessmentStatus.CONFIRMED,
        ExpectedOutcomeAssessmentStatus.PARTIAL,
        ExpectedOutcomeAssessmentStatus.REJECTED,
        ExpectedOutcomeAssessmentStatus.INCONCLUSIVE,
    ):
        assessment = _assessment(status=status)
        assert assessment.status is status


def test_expected_outcome_assessment_rejects_empty_rationale() -> None:
    with pytest.raises(ValidationError, match="field"):
        ExpectedOutcomeAssessment(
            assessment_id="assessment-1",
            run_id=RunId("run-1"),
            evaluation_plan_id="eval-1",
            setup_id="CONTROL/random",
            status=ExpectedOutcomeAssessmentStatus.INCONCLUSIVE,
            assessed_at=_utc(),
            rationale="",
        )


def test_result_set_rejects_mismatched_observation_run_or_plan() -> None:
    with pytest.raises(ValidationError, match="observation run_id"):
        _result_set(observations=(_observation(run_id="other-run"),))
    with pytest.raises(ValidationError, match="observation evaluation_plan_id"):
        _result_set(observations=(_observation(evaluation_plan_id="other-plan"),))


def test_result_set_rejects_duplicate_observation_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate observation_id"):
        _result_set(observations=(_observation("obs-1"), _observation("obs-1")))


def test_result_set_rejects_duplicate_assessment_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate assessment_id"):
        _result_set(assessments=(_assessment("a-1"), _assessment("a-1")))


def test_result_set_allows_empty_observations_in_draft_status() -> None:
    result_set = _result_set(status=EvaluationResultStatus.DRAFT)
    assert result_set.observations == ()


def test_result_set_recorded_can_contain_observations_and_assessments() -> None:
    result_set = _result_set(
        observations=(_observation(),),
        assessments=(_assessment(),),
        status=EvaluationResultStatus.RECORDED,
    )
    assert len(result_set.observations) == 1
    assert len(result_set.assessments) == 1
