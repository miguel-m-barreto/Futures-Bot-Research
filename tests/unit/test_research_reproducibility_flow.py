from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

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
from futures_bot.infrastructure.research.in_memory import (
    InMemoryEvaluationArtifactStore,
    InMemoryResearchRunManifestStore,
)
from futures_bot.research.local import LocalResearchRunRecorder


def _utc(month: int, day: int) -> datetime:
    return datetime(2026, month, day, tzinfo=UTC)


def test_research_reproducibility_metadata_flow() -> None:
    manifest_store = InMemoryResearchRunManifestStore()
    artifact_store = InMemoryEvaluationArtifactStore()
    recorder = LocalResearchRunRecorder(
        manifest_store=manifest_store,
        artifact_store=artifact_store,
        now=lambda: _utc(5, 1),
    )

    dataset = DatasetSnapshot(
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
    windows = (
        TemporalWindow(
            kind=TemporalWindowKind.TRAIN,
            start_at=_utc(1, 1),
            end_at=_utc(2, 1),
        ),
        TemporalWindow(
            kind=TemporalWindowKind.VALIDATION,
            start_at=_utc(2, 1),
            end_at=_utc(3, 1),
        ),
        TemporalWindow(
            kind=TemporalWindowKind.TEST,
            start_at=_utc(3, 1),
            end_at=_utc(3, 20),
        ),
        TemporalWindow(
            kind=TemporalWindowKind.FINAL_HOLDOUT,
            start_at=_utc(3, 20),
            end_at=_utc(4, 1),
        ),
    )
    assumptions = ExecutionAssumptions(
        mode=ExecutionMode.BACKTEST,
        maker_fee_bps=Decimal("2.0"),
        taker_fee_bps=Decimal("5.0"),
        slippage_bps=Decimal("1.0"),
        funding_included=True,
        latency_model="placeholder-local-latency",
        fill_model="placeholder-conservative-fill",
    )
    expected_outcomes = (
        ExpectedOutcome(
            setup_id="wf-baseline",
            expectation=(
                "Chronological validation should reveal whether performance "
                "depends on one narrow regime."
            ),
            primary_measurements=(
                "max_drawdown",
                "turnover",
                "holdout_underperformance",
            ),
            failure_criteria=("final holdout violates expected drawdown envelope",),
        ),
    )
    manifest = ResearchRunManifest(
        run_id=RunId("research-run-1"),
        experiment_id="stablecoin-futures-walk-forward-baseline",
        status=ResearchRunStatus.PLANNED,
        execution_mode=ExecutionMode.BACKTEST,
        created_at=_utc(4, 3),
        updated_at=_utc(4, 3),
        git_commit="abc123def",
        code_branch="main",
        config_hash="config-hash-xyz",
        dataset=dataset,
        temporal_windows=windows,
        execution_assumptions=assumptions,
        expected_outcomes=expected_outcomes,
    )

    recorder.create_manifest(manifest)
    recorder.mark_running(RunId("research-run-1"))
    completed = recorder.mark_completed(RunId("research-run-1"))
    for artifact in (
        EvaluationArtifactMetadata(
            artifact_id="metrics-metadata",
            run_id=RunId("research-run-1"),
            kind=EvaluationArtifactKind.METRICS,
            created_at=_utc(5, 1),
            uri="memory://research-run-1/metrics",
            content_hash="metrics-hash",
            description="Metadata pointer only; no metric values stored here.",
        ),
        EvaluationArtifactMetadata(
            artifact_id="report-metadata",
            run_id=RunId("research-run-1"),
            kind=EvaluationArtifactKind.REPORT,
            created_at=_utc(5, 1),
            uri="memory://research-run-1/report",
            content_hash="report-hash",
        ),
        EvaluationArtifactMetadata(
            artifact_id="environment-snapshot",
            run_id=RunId("research-run-1"),
            kind=EvaluationArtifactKind.ENVIRONMENT_SNAPSHOT,
            created_at=_utc(5, 1),
            uri="memory://research-run-1/environment",
            content_hash="env-hash",
        ),
    ):
        recorder.record_artifact(artifact)

    recorded = manifest_store.load(RunId("research-run-1"))
    assert recorded == completed
    assert recorded is not None
    assert recorded.git_commit == "abc123def"
    assert recorded.config_hash == "config-hash-xyz"
    assert recorded.dataset == dataset
    assert recorded.temporal_windows == windows
    assert recorded.expected_outcomes == expected_outcomes
    assert recorded.dataset.market_type == "stablecoin-collateral-futures"
    assert "BTCUSDT" in recorded.dataset.symbols
    assert "SOLUSDC" in recorded.dataset.symbols
    assert not hasattr(recorded, "observed_metrics")

    artifacts = recorder.artifacts_for_run(RunId("research-run-1"))
    assert [artifact.artifact_id for artifact in artifacts] == [
        "environment-snapshot",
        "metrics-metadata",
        "report-metadata",
    ]
    assert {artifact.kind for artifact in artifacts} == {
        EvaluationArtifactKind.METRICS,
        EvaluationArtifactKind.REPORT,
        EvaluationArtifactKind.ENVIRONMENT_SNAPSHOT,
    }
    assert all(artifact.uri.startswith("memory://") for artifact in artifacts)

    recorder_source = Path(inspect.getsourcefile(LocalResearchRunRecorder) or "").read_text()
    assert "open(" not in recorder_source
    assert "Path(" not in recorder_source
    assert "sqlalchemy" not in recorder_source
    assert "confluent_kafka" not in recorder_source
