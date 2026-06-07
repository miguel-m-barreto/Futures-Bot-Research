from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    CostScenario,
    DatasetSnapshot,
    EvaluationObjective,
    EvaluationPlan,
    EvaluationResultSet,
    EvaluationResultStatus,
    ExecutionAssumptions,
    ExecutionMode,
    ExpectedOutcome,
    ExpectedOutcomeAssessment,
    ExpectedOutcomeAssessmentStatus,
    MetricDirection,
    MetricObservation,
    MetricSpec,
    ReplayDataSourceKind,
    ReplayPlan,
    ResearchRunManifest,
    ResearchRunStatus,
    TemporalWindow,
    TemporalWindowKind,
)
from futures_bot.infrastructure.research.in_memory import (
    InMemoryEvaluationArtifactStore,
    InMemoryEvaluationPlanStore,
    InMemoryEvaluationResultStore,
    InMemoryReplayPlanStore,
    InMemoryResearchRunManifestStore,
)
from futures_bot.research.local import (
    LocalEvaluationResultRecorder,
    LocalResearchPlanner,
    LocalResearchRunRecorder,
)


def _utc(month: int, day: int) -> datetime:
    return datetime(2026, month, day, tzinfo=UTC)


def test_expected_vs_observed_metadata_flow_with_negative_result() -> None:
    manifest_store = InMemoryResearchRunManifestStore()
    artifact_store = InMemoryEvaluationArtifactStore()
    replay_store = InMemoryReplayPlanStore()
    eval_plan_store = InMemoryEvaluationPlanStore()
    result_store = InMemoryEvaluationResultStore()
    run_recorder = LocalResearchRunRecorder(
        manifest_store=manifest_store,
        artifact_store=artifact_store,
        now=lambda: _utc(5, 1),
    )
    planner = LocalResearchPlanner(
        replay_plan_store=replay_store,
        evaluation_plan_store=eval_plan_store,
        manifest_store=manifest_store,
    )
    result_recorder = LocalEvaluationResultRecorder(
        result_store=result_store,
        evaluation_plan_store=eval_plan_store,
        artifact_store=artifact_store,
        now=lambda: _utc(5, 2),
    )

    dataset = DatasetSnapshot(
        dataset_id="stablecoin-futures-v1",
        source="curated-bars",
        market_type="stablecoin-collateral-futures",
        symbols=("BTCUSDT",),
        timeframe="1m",
        start_at=_utc(1, 1),
        end_at=_utc(4, 1),
        created_at=_utc(4, 2),
    )
    windows = (
        TemporalWindow(
            kind=TemporalWindowKind.TRAIN,
            start_at=_utc(1, 1),
            end_at=_utc(2, 1),
            window_id="train-1",
        ),
        TemporalWindow(
            kind=TemporalWindowKind.TEST,
            start_at=_utc(2, 1),
            end_at=_utc(4, 1),
            window_id="test-1",
        ),
    )
    expected = ExpectedOutcome(
        setup_id="CONTROL/random",
        expectation="Expected to degrade after realistic costs.",
        primary_measurements=("pnl_after_costs", "turnover"),
        failure_criteria=("random control remains profitable after costs",),
    )
    manifest = run_recorder.create_manifest(
        ResearchRunManifest(
            run_id=RunId("research-run-1"),
            experiment_id="control-random-cost-check",
            status=ResearchRunStatus.PLANNED,
            execution_mode=ExecutionMode.BACKTEST,
            created_at=_utc(4, 3),
            updated_at=_utc(4, 3),
            git_commit="abc123",
            code_branch="main",
            config_hash="cfg123",
            dataset=dataset,
            temporal_windows=windows,
            execution_assumptions=ExecutionAssumptions(mode=ExecutionMode.BACKTEST),
            expected_outcomes=(expected,),
        )
    )
    replay_plan = planner.create_replay_plan(
        ReplayPlan(
            replay_plan_id="replay-1",
            run_id=RunId("research-run-1"),
            data_source_kind=ReplayDataSourceKind.DATASET_SNAPSHOT,
            dataset_id="stablecoin-futures-v1",
            temporal_windows=windows,
            created_at=_utc(4, 4),
        )
    )
    evaluation_plan = planner.create_evaluation_plan(
        EvaluationPlan(
            evaluation_plan_id="eval-1",
            run_id=RunId("research-run-1"),
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
            created_at=_utc(4, 5),
            expected_outcome_ids=("CONTROL/random",),
        )
    )
    result_recorder.create_result_set(
        EvaluationResultSet(
            result_set_id="result-set-1",
            run_id=RunId("research-run-1"),
            evaluation_plan_id="eval-1",
            status=EvaluationResultStatus.DRAFT,
            created_at=_utc(5, 1),
            updated_at=_utc(5, 1),
        )
    )

    pnl = MetricObservation(
        observation_id="obs-pnl",
        run_id=RunId("research-run-1"),
        evaluation_plan_id="eval-1",
        metric_id="pnl_after_costs",
        observed_at=_utc(5, 2),
        value=Decimal("-42.5"),
        unit="bps",
        cost_scenario_id="baseline-costs",
    )
    turnover = MetricObservation(
        observation_id="obs-turnover",
        run_id=RunId("research-run-1"),
        evaluation_plan_id="eval-1",
        metric_id="turnover",
        observed_at=_utc(5, 2),
        value=Decimal("12.0"),
        unit="orders",
        cost_scenario_id="baseline-costs",
    )
    result_recorder.record_observation("result-set-1", pnl)
    result_recorder.record_observation("result-set-1", turnover)
    result_recorder.record_assessment(
        "result-set-1",
        ExpectedOutcomeAssessment(
            assessment_id="assessment-control-random",
            run_id=RunId("research-run-1"),
            evaluation_plan_id="eval-1",
            setup_id="CONTROL/random",
            status=ExpectedOutcomeAssessmentStatus.CONFIRMED,
            assessed_at=_utc(5, 2),
            rationale="Negative manually recorded pnl after costs confirms degradation.",
            related_observation_ids=("obs-pnl", "obs-turnover"),
        ),
    )
    result_recorder.mark_recorded("result-set-1")
    reviewed = result_recorder.mark_reviewed("result-set-1")

    assert manifest.expected_outcomes == (expected,)
    assert replay_plan.replay_plan_id == "replay-1"
    assert evaluation_plan.metric_specs[0].metric_id == "pnl_after_costs"
    assert not hasattr(evaluation_plan.metric_specs[0], "value")
    assert reviewed.status is EvaluationResultStatus.REVIEWED
    assert reviewed.observations[0] == pnl
    assert reviewed.observations[0].value == Decimal("-42.5")
    assert reviewed.assessments[0].setup_id == "CONTROL/random"
    assert reviewed.assessments[0].status is ExpectedOutcomeAssessmentStatus.CONFIRMED
    assert not hasattr(expected, "observed_value")
    assert not hasattr(result_recorder, "calculate_metrics")
    assert artifact_store.list_for_run(RunId("research-run-1")) == ()

    recorder_source = Path(
        inspect.getsourcefile(LocalEvaluationResultRecorder) or ""
    ).read_text()
    assert "open(" not in recorder_source
    assert "Path(" not in recorder_source
    assert "sqlalchemy" not in recorder_source
    assert "confluent_kafka" not in recorder_source
