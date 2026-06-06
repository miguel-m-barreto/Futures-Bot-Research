from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from futures_bot.domain import research as research_domain
from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    CostScenario,
    DatasetSnapshot,
    EvaluationArtifactKind,
    EvaluationArtifactMetadata,
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


def _utc(day: int = 1) -> datetime:
    return datetime(2026, 1, day, tzinfo=UTC)


def _window(kind: TemporalWindowKind = TemporalWindowKind.TRAIN) -> TemporalWindow:
    return TemporalWindow(kind=kind, start_at=_utc(1), end_at=_utc(2))


def _dataset() -> DatasetSnapshot:
    return DatasetSnapshot(
        dataset_id="ds-stablecoin-futures-1",
        source="local-curated",
        market_type="stablecoin-collateral-futures",
        symbols=("BTCUSDT", "ETHUSDC"),
        timeframe="1m",
        start_at=_utc(1),
        end_at=_utc(3),
        data_version="v1",
        content_hash="hash-ds",
        created_at=_utc(4),
    )


def _assumptions() -> ExecutionAssumptions:
    return ExecutionAssumptions(
        mode=ExecutionMode.BACKTEST,
        maker_fee_bps=Decimal("2.0"),
        taker_fee_bps=Decimal("5.0"),
        slippage_bps=Decimal("1.5"),
        funding_included=True,
    )


def _expected() -> ExpectedOutcome:
    return ExpectedOutcome(
        setup_id="baseline-1",
        expectation="Walk-forward validation should expose regime sensitivity.",
        primary_measurements=("max_drawdown", "turnover", "hit_rate"),
        failure_criteria=("holdout drawdown exceeds validation drawdown by 2x",),
    )


def test_valid_temporal_window() -> None:
    window = _window()
    assert window.kind is TemporalWindowKind.TRAIN


def test_temporal_window_rejects_start_at_or_after_end_at() -> None:
    with pytest.raises(ValidationError, match="start_at"):
        TemporalWindow(kind=TemporalWindowKind.TRAIN, start_at=_utc(2), end_at=_utc(2))


def test_temporal_window_rejects_negative_sequence_index() -> None:
    with pytest.raises(ValidationError, match="sequence_index"):
        TemporalWindow(
            kind=TemporalWindowKind.TRAIN,
            start_at=_utc(1),
            end_at=_utc(2),
            sequence_index=-1,
        )


def test_temporal_window_rejects_empty_fold_id_or_window_id() -> None:
    with pytest.raises(ValidationError, match="field"):
        TemporalWindow(
            kind=TemporalWindowKind.TRAIN,
            start_at=_utc(1),
            end_at=_utc(2),
            fold_id="",
        )
    with pytest.raises(ValidationError, match="field"):
        TemporalWindow(
            kind=TemporalWindowKind.TRAIN,
            start_at=_utc(1),
            end_at=_utc(2),
            window_id="",
        )


def test_dataset_snapshot_rejects_duplicate_symbols() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        DatasetSnapshot(
            dataset_id="ds-1",
            source="source",
            market_type="stablecoin-collateral-futures",
            symbols=("BTCUSDT", "BTCUSDT"),
            timeframe="1m",
            start_at=_utc(1),
            end_at=_utc(2),
            created_at=_utc(3),
        )


def test_dataset_snapshot_rejects_empty_symbols() -> None:
    with pytest.raises(ValidationError, match="symbols"):
        DatasetSnapshot(
            dataset_id="ds-1",
            source="source",
            market_type="stablecoin-collateral-futures",
            symbols=(),
            timeframe="1m",
            start_at=_utc(1),
            end_at=_utc(2),
            created_at=_utc(3),
        )


def test_execution_assumptions_reject_negative_bps() -> None:
    with pytest.raises(ValidationError, match="non-negative"):
        ExecutionAssumptions(mode=ExecutionMode.BACKTEST, taker_fee_bps=Decimal("-1"))


def test_execution_assumptions_reject_float_bps() -> None:
    with pytest.raises(ValidationError, match="Decimal-compatible"):
        ExecutionAssumptions(mode=ExecutionMode.BACKTEST, taker_fee_bps=1.5)


def test_expected_outcome_requires_primary_measurements() -> None:
    with pytest.raises(ValidationError, match="primary_measurements"):
        ExpectedOutcome(
            setup_id="baseline",
            expectation="Expected before observed outputs.",
            primary_measurements=(),
        )


def test_research_run_manifest_requires_non_empty_temporal_windows() -> None:
    with pytest.raises(ValidationError, match="temporal_windows"):
        ResearchRunManifest(
            run_id=RunId("research-run-1"),
            experiment_id="experiment-1",
            status=ResearchRunStatus.PLANNED,
            execution_mode=ExecutionMode.BACKTEST,
            created_at=_utc(1),
            updated_at=_utc(1),
            git_commit="abc123",
            code_branch="main",
            config_hash="cfg123",
            dataset=_dataset(),
            temporal_windows=(),
            execution_assumptions=_assumptions(),
        )


def test_research_run_manifest_preserves_expected_outcomes() -> None:
    manifest = ResearchRunManifest(
        run_id=RunId("research-run-1"),
        experiment_id="experiment-1",
        status=ResearchRunStatus.PLANNED,
        execution_mode=ExecutionMode.BACKTEST,
        created_at=_utc(1),
        updated_at=_utc(1),
        git_commit="abc123",
        code_branch="main",
        config_hash="cfg123",
        dataset=_dataset(),
        temporal_windows=(_window(),),
        execution_assumptions=_assumptions(),
        expected_outcomes=(_expected(),),
    )
    assert manifest.expected_outcomes == (_expected(),)


def test_research_run_manifest_allows_repeated_window_kinds_for_folds() -> None:
    manifest = ResearchRunManifest(
        run_id=RunId("research-run-1"),
        experiment_id="experiment-1",
        status=ResearchRunStatus.PLANNED,
        execution_mode=ExecutionMode.BACKTEST,
        created_at=_utc(1),
        updated_at=_utc(1),
        git_commit="abc123",
        code_branch="main",
        config_hash="cfg123",
        dataset=_dataset(),
        temporal_windows=(
            TemporalWindow(
                kind=TemporalWindowKind.TRAIN,
                start_at=_utc(1),
                end_at=_utc(2),
                fold_id="fold-001",
                sequence_index=0,
            ),
            TemporalWindow(
                kind=TemporalWindowKind.TRAIN,
                start_at=_utc(2),
                end_at=_utc(3),
                fold_id="fold-002",
                sequence_index=1,
            ),
        ),
        execution_assumptions=_assumptions(),
    )
    assert len(manifest.temporal_windows) == 2


def test_research_run_manifest_rejects_exact_duplicate_windows() -> None:
    duplicate = TemporalWindow(
        kind=TemporalWindowKind.TRAIN,
        start_at=_utc(1),
        end_at=_utc(2),
        fold_id="fold-001",
        sequence_index=0,
    )
    with pytest.raises(ValidationError, match="duplicate temporal windows"):
        ResearchRunManifest(
            run_id=RunId("research-run-1"),
            experiment_id="experiment-1",
            status=ResearchRunStatus.PLANNED,
            execution_mode=ExecutionMode.BACKTEST,
            created_at=_utc(1),
            updated_at=_utc(1),
            git_commit="abc123",
            code_branch="main",
            config_hash="cfg123",
            dataset=_dataset(),
            temporal_windows=(duplicate, duplicate),
            execution_assumptions=_assumptions(),
        )


def test_evaluation_artifact_metadata_validates_non_empty_uri() -> None:
    with pytest.raises(ValidationError, match="field"):
        EvaluationArtifactMetadata(
            artifact_id="artifact-1",
            run_id=RunId("research-run-1"),
            kind=EvaluationArtifactKind.REPORT,
            created_at=_utc(1),
            uri="",
        )


def test_replay_plan_requires_dataset_id_for_dataset_snapshot() -> None:
    with pytest.raises(ValidationError, match="dataset_id"):
        ReplayPlan(
            replay_plan_id="replay-1",
            run_id=RunId("research-run-1"),
            data_source_kind=ReplayDataSourceKind.DATASET_SNAPSHOT,
            temporal_windows=(_window(),),
            created_at=_utc(1),
        )


def test_replay_plan_rejects_duplicate_windows_and_negative_seed() -> None:
    window = _window()
    with pytest.raises(ValidationError, match="duplicate temporal windows"):
        ReplayPlan(
            replay_plan_id="replay-1",
            run_id=RunId("research-run-1"),
            data_source_kind=ReplayDataSourceKind.SYNTHETIC_FIXTURE,
            temporal_windows=(window, window),
            created_at=_utc(1),
        )
    with pytest.raises(ValidationError, match="random_seed"):
        ReplayPlan(
            replay_plan_id="replay-1",
            run_id=RunId("research-run-1"),
            data_source_kind=ReplayDataSourceKind.SYNTHETIC_FIXTURE,
            temporal_windows=(_window(),),
            created_at=_utc(1),
            random_seed=-1,
        )


def test_metric_spec_and_cost_scenario_validation() -> None:
    with pytest.raises(ValidationError, match="field"):
        MetricSpec(metric_id="", name="Sharpe", direction=MetricDirection.MAXIMIZE)
    with pytest.raises(ValidationError, match="non-negative"):
        CostScenario(scenario_id="high-fee", taker_fee_bps=Decimal("-1"))
    with pytest.raises(ValidationError, match="Decimal-compatible"):
        CostScenario(scenario_id="float-fee", taker_fee_bps=1.2)


def test_evaluation_plan_requires_primary_metric_and_unique_ids() -> None:
    metric = MetricSpec(
        metric_id="max_drawdown",
        name="Max drawdown",
        direction=MetricDirection.MINIMIZE,
        is_primary=False,
    )
    scenario = CostScenario(scenario_id="baseline", taker_fee_bps=Decimal("5"))
    with pytest.raises(ValidationError, match="primary"):
        EvaluationPlan(
            evaluation_plan_id="eval-1",
            run_id=RunId("research-run-1"),
            replay_plan_id="replay-1",
            objective=EvaluationObjective.ROBUSTNESS,
            metric_specs=(metric,),
            cost_scenarios=(scenario,),
            created_at=_utc(1),
        )
    primary = metric.model_copy(update={"is_primary": True})
    with pytest.raises(ValidationError, match="duplicate metric_id"):
        EvaluationPlan(
            evaluation_plan_id="eval-1",
            run_id=RunId("research-run-1"),
            replay_plan_id="replay-1",
            objective=EvaluationObjective.ROBUSTNESS,
            metric_specs=(primary, primary),
            cost_scenarios=(scenario,),
            created_at=_utc(1),
        )


def test_research_domain_does_not_import_forbidden_libraries() -> None:
    source_path = inspect.getsourcefile(research_domain)
    assert source_path is not None
    source = Path(source_path).read_text()
    forbidden = (
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "sqlalchemy",
        "psycopg",
        "asyncpg",
        "duckdb",
        "sqlite",
        "confluent_kafka",
        "aiokafka",
        "LocalJsonlWal",
        "sidecars.local",
        "decide_wal_gc",
    )
    for name in forbidden:
        assert name not in source
