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
    DatasetSnapshot,
    EvaluationArtifactKind,
    EvaluationArtifactMetadata,
    ExecutionAssumptions,
    ExecutionMode,
    ExpectedOutcome,
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


def test_evaluation_artifact_metadata_validates_non_empty_uri() -> None:
    with pytest.raises(ValidationError, match="field"):
        EvaluationArtifactMetadata(
            artifact_id="artifact-1",
            run_id=RunId("research-run-1"),
            kind=EvaluationArtifactKind.REPORT,
            created_at=_utc(1),
            uri="",
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
