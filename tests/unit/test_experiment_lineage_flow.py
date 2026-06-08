from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    ConfigSnapshotKind,
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
    ExperimentDefinition,
    ExperimentStatus,
    MetricDirection,
    MetricObservation,
    MetricSpec,
    ReplayDataSourceKind,
    ReplayPlan,
    ResearchRunManifest,
    ResearchRunStatus,
    RunLineageKind,
    RunLineageRecord,
    TemporalWindow,
    TemporalWindowKind,
)
from futures_bot.infrastructure.research.in_memory import (
    InMemoryConfigBundleStore,
    InMemoryConfigSnapshotStore,
    InMemoryEvaluationArtifactStore,
    InMemoryEvaluationPlanStore,
    InMemoryEvaluationResultStore,
    InMemoryExperimentDefinitionStore,
    InMemoryReplayPlanStore,
    InMemoryResearchRunManifestStore,
    InMemoryRunLineageStore,
)
from futures_bot.research.local import (
    LocalEvaluationResultRecorder,
    LocalResearchPlanner,
    LocalResearchRunRecorder,
)
from futures_bot.research.registry import LocalExperimentRegistry


def _utc(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def test_experiment_lineage_reproducibility_flow_is_metadata_only() -> None:
    experiment_store = InMemoryExperimentDefinitionStore()
    config_store = InMemoryConfigSnapshotStore()
    bundle_store = InMemoryConfigBundleStore()
    lineage_store = InMemoryRunLineageStore()
    manifest_store = InMemoryResearchRunManifestStore()
    replay_store = InMemoryReplayPlanStore()
    evaluation_store = InMemoryEvaluationPlanStore()
    result_store = InMemoryEvaluationResultStore()
    registry = LocalExperimentRegistry(
        experiment_store=experiment_store,
        config_store=config_store,
        lineage_store=lineage_store,
        config_bundle_store=bundle_store,
        manifest_store=manifest_store,
        replay_plan_store=replay_store,
        evaluation_plan_store=evaluation_store,
        now=lambda: _utc(6),
    )
    run_recorder = LocalResearchRunRecorder(
        manifest_store=manifest_store,
        artifact_store=InMemoryEvaluationArtifactStore(),
        now=lambda: _utc(6),
    )
    planner = LocalResearchPlanner(
        replay_plan_store=replay_store,
        evaluation_plan_store=evaluation_store,
        manifest_store=manifest_store,
    )
    result_recorder = LocalEvaluationResultRecorder(
        result_store=result_store,
        evaluation_plan_store=evaluation_store,
        now=lambda: _utc(7),
    )

    experiment = ExperimentDefinition(
        experiment_id="exp-control-random-costs",
        title="Random baseline realistic costs",
        objective="Test whether random baseline degrades after realistic costs.",
        status=ExperimentStatus.PLANNED,
        created_at=_utc(1),
        updated_at=_utc(1),
        tags=("baseline", "stablecoin-futures"),
    )
    registry.register_experiment(experiment)

    dataset_config = registry.fingerprint_config(
        config_id="cfg-dataset",
        kind=ConfigSnapshotKind.DATASET_CONFIG,
        payload={
            "market_type": "stablecoin-collateral-futures",
            "symbols": ("BTCUSDT", "ETHUSDC"),
            "timeframe": "1m",
        },
    )
    replay_config = registry.fingerprint_config(
        config_id="cfg-replay",
        kind=ConfigSnapshotKind.RUN_CONFIG,
        payload={"mode": "REPLAY", "seed": 42},
    )
    evaluation_config = registry.fingerprint_config(
        config_id="cfg-evaluation",
        kind=ConfigSnapshotKind.EVALUATION_CONFIG,
        payload={"metrics": ("pnl_after_costs", "turnover")},
    )
    costs_config = registry.fingerprint_config(
        config_id="cfg-costs",
        kind=ConfigSnapshotKind.EXECUTION_CONFIG,
        payload={"taker_fee_bps": Decimal("5.0"), "slippage_bps": Decimal("1.0")},
    )
    config_bundle = registry.compose_config_bundle(
        bundle_id="bundle-run-1",
        config_ids=(
            dataset_config.config_id,
            replay_config.config_id,
            evaluation_config.config_id,
            costs_config.config_id,
        ),
    )

    expected = ExpectedOutcome(
        setup_id="CONTROL/random",
        expectation="Expected to degrade after realistic costs.",
        primary_measurements=("pnl_after_costs",),
    )
    dataset = DatasetSnapshot(
        dataset_id="ds-stablecoin-futures",
        source="local-curated",
        market_type="stablecoin-collateral-futures",
        symbols=("BTCUSDT", "ETHUSDC"),
        timeframe="1m",
        start_at=_utc(1),
        end_at=_utc(5),
        content_hash=dataset_config.sha256,
        created_at=_utc(1),
    )
    window = TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(2),
        end_at=_utc(3),
        window_id="test-001",
    )
    manifest = run_recorder.create_manifest(
        ResearchRunManifest(
            run_id=RunId("run-1"),
            experiment_id=experiment.experiment_id,
            status=ResearchRunStatus.PLANNED,
            execution_mode=ExecutionMode.REPLAY,
            created_at=_utc(2),
            updated_at=_utc(2),
            git_commit="abc123",
            code_branch="main",
            config_hash=config_bundle.sha256,
            dataset=dataset,
            temporal_windows=(window,),
            execution_assumptions=ExecutionAssumptions(
                mode=ExecutionMode.REPLAY,
                taker_fee_bps=Decimal("5"),
                slippage_bps=Decimal("1"),
            ),
            expected_outcomes=(expected,),
        )
    )
    replay_plan = planner.create_replay_plan(
        ReplayPlan(
            replay_plan_id="replay-1",
            run_id=manifest.run_id,
            data_source_kind=ReplayDataSourceKind.DATASET_SNAPSHOT,
            dataset_id=dataset.dataset_id,
            temporal_windows=(window,),
            created_at=_utc(3),
            random_seed=42,
        )
    )
    evaluation_plan = planner.create_evaluation_plan(
        EvaluationPlan(
            evaluation_plan_id="eval-1",
            run_id=manifest.run_id,
            replay_plan_id=replay_plan.replay_plan_id,
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
            created_at=_utc(4),
            expected_outcome_ids=(expected.setup_id,),
        )
    )
    lineage = registry.register_lineage(
        RunLineageRecord(
            lineage_id="lineage-1",
            run_id=manifest.run_id,
            experiment_id=experiment.experiment_id,
            kind=RunLineageKind.ROOT,
            created_at=_utc(5),
            config_ids=(
                dataset_config.config_id,
                replay_config.config_id,
                evaluation_config.config_id,
                costs_config.config_id,
            ),
            replay_plan_id=replay_plan.replay_plan_id,
            evaluation_plan_id=evaluation_plan.evaluation_plan_id,
            config_bundle_id=config_bundle.bundle_id,
        )
    )

    result_recorder.create_result_set(
        EvaluationResultSet(
            result_set_id="result-set-1",
            run_id=manifest.run_id,
            evaluation_plan_id=evaluation_plan.evaluation_plan_id,
            status=EvaluationResultStatus.DRAFT,
            created_at=_utc(6),
            updated_at=_utc(6),
        )
    )
    observation = MetricObservation(
        observation_id="obs-pnl",
        run_id=manifest.run_id,
        evaluation_plan_id=evaluation_plan.evaluation_plan_id,
        metric_id="pnl_after_costs",
        observed_at=_utc(6, 1),
        value=Decimal("-12.5"),
        cost_scenario_id="baseline-costs",
    )
    result_recorder.record_observation("result-set-1", observation)
    result_recorder.record_assessment(
        "result-set-1",
        ExpectedOutcomeAssessment(
            assessment_id="assessment-1",
            run_id=manifest.run_id,
            evaluation_plan_id=evaluation_plan.evaluation_plan_id,
            setup_id=expected.setup_id,
            status=ExpectedOutcomeAssessmentStatus.CONFIRMED,
            assessed_at=_utc(6, 1),
            rationale="Manual negative observation supports the predeclared expectation.",
            related_observation_ids=(observation.observation_id,),
        ),
    )

    assert registry.lineage_for_experiment(experiment.experiment_id) == (lineage,)
    assert registry.configs_for_lineage(lineage.lineage_id) == (
        dataset_config,
        replay_config,
        evaluation_config,
        costs_config,
    )
    assert registry.load_config_bundle(config_bundle.bundle_id) == config_bundle
    assert manifest.config_hash == config_bundle.sha256
    assert config_bundle.sha256 == registry.compose_config_bundle(
        bundle_id="bundle-run-1-reordered",
        config_ids=(
            costs_config.config_id,
            evaluation_config.config_id,
            replay_config.config_id,
            dataset_config.config_id,
        ),
    ).sha256
    assert dataset_config.sha256 == registry.fingerprint_config(
        config_id="cfg-dataset-copy",
        kind=ConfigSnapshotKind.DATASET_CONFIG,
        payload={
            "timeframe": "1m",
            "symbols": ("BTCUSDT", "ETHUSDC"),
            "market_type": "stablecoin-collateral-futures",
        },
    ).sha256
    assert manifest.expected_outcomes == (expected,)
    assert not hasattr(evaluation_plan.metric_specs[0], "value")
    assert not hasattr(registry, "calculate_metrics")
    assert result_store.load("result-set-1") is not None

    for cls in (LocalExperimentRegistry, LocalResearchPlanner):
        source_path = inspect.getsourcefile(cls)
        assert source_path is not None
        source = Path(source_path).read_text(encoding="utf-8")
        assert "open(" not in source
        assert "write_text" not in source
        assert "confluent_kafka" not in source
        assert "sqlalchemy" not in source
