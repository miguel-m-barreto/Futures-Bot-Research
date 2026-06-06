from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    DatasetSnapshot,
    EvaluationArtifactKind,
    EvaluationArtifactMetadata,
    ExecutionAssumptions,
    ExecutionMode,
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


def _utc(day: int = 1, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def _dataset() -> DatasetSnapshot:
    return DatasetSnapshot(
        dataset_id="ds-1",
        source="local-curated",
        market_type="stablecoin-collateral-futures",
        symbols=("BTCUSDT",),
        timeframe="1m",
        start_at=_utc(1),
        end_at=_utc(2),
        created_at=_utc(3),
    )


def _manifest(notes: str | None = None) -> ResearchRunManifest:
    return ResearchRunManifest(
        run_id=RunId("research-run-1"),
        experiment_id="experiment-1",
        status=ResearchRunStatus.PLANNED,
        execution_mode=ExecutionMode.BACKTEST,
        created_at=_utc(4),
        updated_at=_utc(4),
        git_commit="abc123",
        code_branch="main",
        config_hash="cfg123",
        dataset=_dataset(),
        temporal_windows=(
            TemporalWindow(
                kind=TemporalWindowKind.TRAIN,
                start_at=_utc(1),
                end_at=_utc(2),
            ),
        ),
        execution_assumptions=ExecutionAssumptions(
            mode=ExecutionMode.BACKTEST,
            taker_fee_bps=Decimal("5"),
        ),
        notes=notes,
    )


def _artifact(
    artifact_id: str = "artifact-1",
    run_id: str = "research-run-1",
) -> EvaluationArtifactMetadata:
    return EvaluationArtifactMetadata(
        artifact_id=artifact_id,
        run_id=RunId(run_id),
        kind=EvaluationArtifactKind.METRICS,
        created_at=_utc(5),
        uri=f"memory://{artifact_id}",
        content_hash=f"hash-{artifact_id}",
    )


def _recorder(
    *,
    manifest_store: InMemoryResearchRunManifestStore | None = None,
    artifact_store: InMemoryEvaluationArtifactStore | None = None,
    now: datetime | None = None,
) -> tuple[
    LocalResearchRunRecorder,
    InMemoryResearchRunManifestStore,
    InMemoryEvaluationArtifactStore,
]:
    manifest_store = manifest_store or InMemoryResearchRunManifestStore()
    artifact_store = artifact_store or InMemoryEvaluationArtifactStore()
    recorder = LocalResearchRunRecorder(
        manifest_store=manifest_store,
        artifact_store=artifact_store,
        now=lambda: now or _utc(6),
    )
    return recorder, manifest_store, artifact_store


def test_create_manifest_saves_manifest() -> None:
    recorder, manifest_store, _ = _recorder()
    manifest = recorder.create_manifest(_manifest())
    assert manifest_store.load(RunId("research-run-1")) == manifest


def test_mark_running_updates_status_and_updated_at() -> None:
    recorder, manifest_store, _ = _recorder(now=_utc(6))
    recorder.create_manifest(_manifest())
    manifest = recorder.mark_running(RunId("research-run-1"))
    assert manifest.status is ResearchRunStatus.RUNNING
    assert manifest.updated_at == _utc(6)
    assert manifest_store.load(RunId("research-run-1")) == manifest


def test_mark_completed_updates_status_and_updated_at() -> None:
    recorder, _, _ = _recorder(now=_utc(6))
    recorder.create_manifest(_manifest())
    recorder.mark_running(RunId("research-run-1"))
    completed = recorder.mark_completed(RunId("research-run-1"))
    assert completed.status is ResearchRunStatus.COMPLETED
    assert completed.updated_at == _utc(6)


def test_mark_failed_updates_status_and_stores_reason_in_notes() -> None:
    recorder, _, _ = _recorder(now=_utc(6))
    recorder.create_manifest(_manifest(notes="Initial note."))
    failed = recorder.mark_failed(RunId("research-run-1"), "Data gap detected.")
    assert failed.status is ResearchRunStatus.FAILED
    assert failed.notes is not None
    assert "Initial note." in failed.notes
    assert "Data gap detected." in failed.notes


def test_invalidate_updates_status_and_stores_reason_in_notes() -> None:
    recorder, _, _ = _recorder(now=_utc(6))
    recorder.create_manifest(_manifest())
    invalidated = recorder.invalidate(
        RunId("research-run-1"), "Expected outcomes were edited after results."
    )
    assert invalidated.status is ResearchRunStatus.INVALIDATED
    assert invalidated.notes is not None
    assert "Expected outcomes" in invalidated.notes


def test_missing_run_id_raises_key_error() -> None:
    recorder, _, _ = _recorder()
    with pytest.raises(KeyError, match="missing-run"):
        recorder.mark_running(RunId("missing-run"))


def test_record_artifact_stores_artifact() -> None:
    recorder, _, artifact_store = _recorder()
    artifact = recorder.record_artifact(_artifact())
    assert artifact_store.load("artifact-1") == artifact


def test_artifacts_for_run_returns_only_selected_run() -> None:
    recorder, _, _ = _recorder()
    recorder.record_artifact(_artifact("artifact-1", run_id="run-1"))
    recorder.record_artifact(_artifact("artifact-2", run_id="run-2"))
    assert [artifact.artifact_id for artifact in recorder.artifacts_for_run(RunId("run-1"))] == [
        "artifact-1",
    ]
