from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    CostScenario,
    DatasetSnapshot,
    EvaluationObjective,
    EvaluationPlan,
    ExecutionAssumptions,
    ExecutionMode,
    ExpectedOutcome,
    MetricDirection,
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
    InMemoryReplayPlanStore,
    InMemoryResearchRunManifestStore,
)
from futures_bot.ports.research import EvaluationPlanStorePort, ReplayPlanStorePort
from futures_bot.research.local import LocalResearchPlanner, LocalResearchRunRecorder


def _utc(month: int, day: int, hour: int = 0) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


def _dataset() -> DatasetSnapshot:
    return DatasetSnapshot(
        dataset_id="stablecoin-futures-v1-2026q1",
        source="curated-historical-futures-bars",
        market_type="stablecoin-collateral-futures",
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDC"),
        timeframe="1m",
        start_at=_utc(1, 1),
        end_at=_utc(4, 1),
        data_version="2026q1",
        content_hash="dataset-hash-abc",
        created_at=_utc(4, 2),
    )


def _window(
    kind: TemporalWindowKind,
    start_at: datetime,
    end_at: datetime,
    *,
    fold_id: str,
    sequence_index: int,
) -> TemporalWindow:
    return TemporalWindow(
        kind=kind,
        start_at=start_at,
        end_at=end_at,
        fold_id=fold_id,
        sequence_index=sequence_index,
        window_id=f"{fold_id}-{kind.value.lower()}",
    )


def _walk_forward_windows() -> tuple[TemporalWindow, ...]:
    return (
        _window(
            TemporalWindowKind.TRAIN,
            _utc(1, 1),
            _utc(1, 20),
            fold_id="fold-001",
            sequence_index=0,
        ),
        _window(
            TemporalWindowKind.VALIDATION,
            _utc(1, 20),
            _utc(2, 1),
            fold_id="fold-001",
            sequence_index=1,
        ),
        _window(
            TemporalWindowKind.TEST,
            _utc(2, 1),
            _utc(2, 10),
            fold_id="fold-001",
            sequence_index=2,
        ),
        _window(
            TemporalWindowKind.TRAIN,
            _utc(1, 10),
            _utc(2, 10),
            fold_id="fold-002",
            sequence_index=3,
        ),
        _window(
            TemporalWindowKind.VALIDATION,
            _utc(2, 10),
            _utc(3, 1),
            fold_id="fold-002",
            sequence_index=4,
        ),
        _window(
            TemporalWindowKind.TEST,
            _utc(3, 1),
            _utc(3, 10),
            fold_id="fold-002",
            sequence_index=5,
        ),
        TemporalWindow(
            kind=TemporalWindowKind.FINAL_HOLDOUT,
            start_at=_utc(3, 10),
            end_at=_utc(4, 1),
            window_id="final-holdout",
            sequence_index=6,
        ),
    )


def _expected_outcomes() -> tuple[ExpectedOutcome, ...]:
    return (
        ExpectedOutcome(
            setup_id="wf-baseline",
            expectation="Walk-forward folds should expose regime sensitivity.",
            primary_measurements=("max_drawdown", "turnover", "holdout_gap"),
            failure_criteria=("final holdout exceeds expected drawdown envelope",),
        ),
    )


def _manifest() -> ResearchRunManifest:
    return ResearchRunManifest(
        run_id=RunId("research-run-1"),
        experiment_id="stablecoin-futures-walk-forward-baseline",
        status=ResearchRunStatus.PLANNED,
        execution_mode=ExecutionMode.BACKTEST,
        created_at=_utc(4, 3),
        updated_at=_utc(4, 3),
        git_commit="abc123def",
        code_branch="main",
        config_hash="config-hash-xyz",
        dataset=_dataset(),
        temporal_windows=_walk_forward_windows(),
        execution_assumptions=ExecutionAssumptions(
            mode=ExecutionMode.BACKTEST,
            maker_fee_bps=Decimal("2"),
            taker_fee_bps=Decimal("5"),
            slippage_bps=Decimal("1"),
            funding_included=True,
        ),
        expected_outcomes=_expected_outcomes(),
    )


def _replay_plan(
    replay_plan_id: str = "replay-1",
    *,
    run_id: str = "research-run-1",
    dataset_id: str = "stablecoin-futures-v1-2026q1",
    created_at: datetime | None = None,
) -> ReplayPlan:
    return ReplayPlan(
        replay_plan_id=replay_plan_id,
        run_id=RunId(run_id),
        data_source_kind=ReplayDataSourceKind.DATASET_SNAPSHOT,
        dataset_id=dataset_id,
        temporal_windows=_walk_forward_windows(),
        created_at=created_at or _utc(4, 4),
        random_seed=42,
    )


def _metric_specs() -> tuple[MetricSpec, ...]:
    return (
        MetricSpec(
            metric_id="max_drawdown",
            name="Max drawdown",
            direction=MetricDirection.MINIMIZE,
            unit="bps",
            is_primary=True,
        ),
        MetricSpec(
            metric_id="turnover",
            name="Turnover",
            direction=MetricDirection.INFORMATION_ONLY,
        ),
    )


def _cost_scenarios() -> tuple[CostScenario, ...]:
    return (
        CostScenario(
            scenario_id="baseline",
            maker_fee_bps=Decimal("2"),
            taker_fee_bps=Decimal("5"),
            slippage_bps=Decimal("1"),
            funding_included=True,
        ),
        CostScenario(
            scenario_id="high-fee",
            maker_fee_bps=Decimal("4"),
            taker_fee_bps=Decimal("10"),
            slippage_bps=Decimal("1"),
            funding_included=True,
        ),
        CostScenario(
            scenario_id="high-slippage",
            maker_fee_bps=Decimal("2"),
            taker_fee_bps=Decimal("5"),
            slippage_bps=Decimal("5"),
            funding_included=True,
        ),
        CostScenario(
            scenario_id="funding-excluded",
            maker_fee_bps=Decimal("2"),
            taker_fee_bps=Decimal("5"),
            slippage_bps=Decimal("1"),
            funding_included=False,
        ),
    )


def _evaluation_plan(
    evaluation_plan_id: str = "eval-1",
    *,
    run_id: str = "research-run-1",
    replay_plan_id: str = "replay-1",
    created_at: datetime | None = None,
) -> EvaluationPlan:
    return EvaluationPlan(
        evaluation_plan_id=evaluation_plan_id,
        run_id=RunId(run_id),
        replay_plan_id=replay_plan_id,
        objective=EvaluationObjective.ROBUSTNESS,
        metric_specs=_metric_specs(),
        cost_scenarios=_cost_scenarios(),
        created_at=created_at or _utc(4, 5),
        expected_outcome_ids=("wf-baseline",),
    )


def test_plan_stores_implement_ports() -> None:
    _: ReplayPlanStorePort = InMemoryReplayPlanStore()
    _: EvaluationPlanStorePort = InMemoryEvaluationPlanStore()


def test_replay_plan_store_save_load_and_idempotency() -> None:
    store = InMemoryReplayPlanStore()
    plan = _replay_plan()
    store.save(plan)
    store.save(plan)
    assert store.load("replay-1") == plan


def test_replay_plan_store_conflicting_same_id_rejected() -> None:
    store = InMemoryReplayPlanStore()
    store.save(_replay_plan(dataset_id="stablecoin-futures-v1-2026q1"))
    with pytest.raises(ValueError, match="conflict"):
        store.save(_replay_plan(dataset_id="other-dataset"))


def test_replay_plan_store_list_for_run_filters_and_orders() -> None:
    store = InMemoryReplayPlanStore()
    store.save(_replay_plan("b", run_id="run-1", created_at=_utc(4, 5)))
    store.save(_replay_plan("other", run_id="run-2", created_at=_utc(4, 4)))
    store.save(_replay_plan("a", run_id="run-1", created_at=_utc(4, 4)))
    assert [plan.replay_plan_id for plan in store.list_for_run(RunId("run-1"))] == [
        "a",
        "b",
    ]


def test_evaluation_plan_store_save_load_and_idempotency() -> None:
    store = InMemoryEvaluationPlanStore()
    plan = _evaluation_plan()
    store.save(plan)
    store.save(plan)
    assert store.load("eval-1") == plan


def test_evaluation_plan_store_conflicting_same_id_rejected() -> None:
    store = InMemoryEvaluationPlanStore()
    store.save(_evaluation_plan(replay_plan_id="replay-1"))
    with pytest.raises(ValueError, match="conflict"):
        store.save(_evaluation_plan(replay_plan_id="replay-other"))


def test_evaluation_plan_store_list_for_run_filters_and_orders() -> None:
    store = InMemoryEvaluationPlanStore()
    store.save(_evaluation_plan("b", run_id="run-1", created_at=_utc(4, 5)))
    store.save(_evaluation_plan("other", run_id="run-2", created_at=_utc(4, 4)))
    store.save(_evaluation_plan("a", run_id="run-1", created_at=_utc(4, 4)))
    assert [plan.evaluation_plan_id for plan in store.list_for_run(RunId("run-1"))] == [
        "a",
        "b",
    ]


def test_local_research_planner_create_and_list_methods() -> None:
    replay_store = InMemoryReplayPlanStore()
    eval_store = InMemoryEvaluationPlanStore()
    planner = LocalResearchPlanner(
        replay_plan_store=replay_store,
        evaluation_plan_store=eval_store,
    )
    replay_plan = planner.create_replay_plan(_replay_plan())
    eval_plan = planner.create_evaluation_plan(_evaluation_plan())
    assert planner.replay_plans_for_run(RunId("research-run-1")) == (replay_plan,)
    assert planner.evaluation_plans_for_run(RunId("research-run-1")) == (eval_plan,)


def test_validate_plan_against_manifest_accepts_matching_dataset_and_range() -> None:
    manifest_store = InMemoryResearchRunManifestStore()
    manifest_store.save(_manifest())
    planner = LocalResearchPlanner(
        replay_plan_store=InMemoryReplayPlanStore(),
        evaluation_plan_store=InMemoryEvaluationPlanStore(),
        manifest_store=manifest_store,
    )
    planner.validate_plan_against_manifest(_replay_plan())


def test_validate_plan_against_manifest_rejects_missing_manifest() -> None:
    planner = LocalResearchPlanner(
        replay_plan_store=InMemoryReplayPlanStore(),
        evaluation_plan_store=InMemoryEvaluationPlanStore(),
        manifest_store=InMemoryResearchRunManifestStore(),
    )
    with pytest.raises(KeyError, match="research-run-1"):
        planner.validate_plan_against_manifest(_replay_plan())


def test_validate_plan_against_manifest_rejects_dataset_mismatch() -> None:
    manifest_store = InMemoryResearchRunManifestStore()
    manifest_store.save(_manifest())
    planner = LocalResearchPlanner(
        replay_plan_store=InMemoryReplayPlanStore(),
        evaluation_plan_store=InMemoryEvaluationPlanStore(),
        manifest_store=manifest_store,
    )
    with pytest.raises(ValueError, match="dataset_id"):
        planner.validate_plan_against_manifest(_replay_plan(dataset_id="other-dataset"))


def test_validate_plan_against_manifest_rejects_window_outside_dataset_range() -> None:
    manifest_store = InMemoryResearchRunManifestStore()
    manifest_store.save(_manifest())
    planner = LocalResearchPlanner(
        replay_plan_store=InMemoryReplayPlanStore(),
        evaluation_plan_store=InMemoryEvaluationPlanStore(),
        manifest_store=manifest_store,
    )
    plan = _replay_plan().model_copy(
        update={
            "temporal_windows": (
                TemporalWindow(
                    kind=TemporalWindowKind.REPLAY,
                    start_at=_utc(4, 1),
                    end_at=_utc(4, 2),
                    window_id="outside-range",
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="dataset range"):
        planner.validate_plan_against_manifest(plan)


def test_walk_forward_replay_evaluation_planning_flow_is_metadata_only() -> None:
    manifest_store = InMemoryResearchRunManifestStore()
    artifact_store = InMemoryEvaluationArtifactStore()
    replay_store = InMemoryReplayPlanStore()
    eval_store = InMemoryEvaluationPlanStore()
    recorder = LocalResearchRunRecorder(
        manifest_store=manifest_store,
        artifact_store=artifact_store,
        now=lambda: _utc(4, 6),
    )
    planner = LocalResearchPlanner(
        replay_plan_store=replay_store,
        evaluation_plan_store=eval_store,
        manifest_store=manifest_store,
    )

    manifest = recorder.create_manifest(_manifest())
    replay_plan = planner.create_replay_plan(_replay_plan())
    evaluation_plan = planner.create_evaluation_plan(_evaluation_plan())

    assert len(
        [
            window
            for window in manifest.temporal_windows
            if window.kind is TemporalWindowKind.TRAIN
        ]
    ) == 2
    assert replay_plan.dataset_id == manifest.dataset.dataset_id
    assert replay_plan.temporal_windows == manifest.temporal_windows
    assert evaluation_plan.expected_outcome_ids == ("wf-baseline",)
    assert manifest.expected_outcomes == _expected_outcomes()
    assert not hasattr(evaluation_plan, "metric_values")
    assert not hasattr(replay_plan, "execution_result")
    assert recorder.artifacts_for_run(RunId("research-run-1")) == ()


def test_local_planner_has_no_file_db_kafka_or_execution_imports() -> None:
    source_path = inspect.getsourcefile(LocalResearchPlanner)
    assert source_path is not None
    source = Path(source_path).read_text()
    forbidden = (
        "open(",
        "Path(",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "matplotlib",
        "plotly",
        "seaborn",
        "LocalJsonlWal",
        "decide_wal_gc",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
    )
    for name in forbidden:
        assert name not in source
