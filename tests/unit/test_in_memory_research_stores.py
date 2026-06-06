from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

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
from futures_bot.ports.research import (
    EvaluationArtifactStorePort,
    ResearchRunManifestStorePort,
)


def _utc(day: int = 1, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def _dataset() -> DatasetSnapshot:
    return DatasetSnapshot(
        dataset_id="ds-1",
        source="local-curated",
        market_type="stablecoin-collateral-futures",
        symbols=("BTCUSDT", "ETHUSDC"),
        timeframe="1m",
        start_at=_utc(1),
        end_at=_utc(2),
        created_at=_utc(3),
    )


def _manifest(
    run_id: str = "research-run-1",
    *,
    status: ResearchRunStatus = ResearchRunStatus.PLANNED,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> ResearchRunManifest:
    return ResearchRunManifest(
        run_id=RunId(run_id),
        experiment_id="experiment-1",
        status=status,
        execution_mode=ExecutionMode.BACKTEST,
        created_at=created_at or _utc(4),
        updated_at=updated_at or created_at or _utc(4),
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
    )


def _artifact(
    artifact_id: str = "artifact-1",
    *,
    run_id: str = "research-run-1",
    created_at: datetime | None = None,
    uri: str = "memory://artifact-1",
) -> EvaluationArtifactMetadata:
    return EvaluationArtifactMetadata(
        artifact_id=artifact_id,
        run_id=RunId(run_id),
        kind=EvaluationArtifactKind.METRICS,
        created_at=created_at or _utc(5),
        uri=uri,
        content_hash="hash-1",
    )


def test_manifest_store_implements_port() -> None:
    _: ResearchRunManifestStorePort = InMemoryResearchRunManifestStore()


def test_artifact_store_implements_port() -> None:
    _: EvaluationArtifactStorePort = InMemoryEvaluationArtifactStore()


def test_manifest_save_load_round_trip() -> None:
    store = InMemoryResearchRunManifestStore()
    manifest = _manifest()
    store.save(manifest)
    assert store.load(RunId("research-run-1")) == manifest


def test_manifest_list_all_deterministic() -> None:
    store = InMemoryResearchRunManifestStore()
    store.save(_manifest("run-b", created_at=_utc(5)))
    store.save(_manifest("run-a", created_at=_utc(4)))
    assert [str(manifest.run_id) for manifest in store.list_all()] == ["run-a", "run-b"]


def test_manifest_older_updated_at_rejected() -> None:
    store = InMemoryResearchRunManifestStore()
    store.save(_manifest(updated_at=_utc(4, 1)))
    with pytest.raises(ValueError, match="updated_at regression"):
        store.save(_manifest(updated_at=_utc(4, 0)))


def test_manifest_valid_transition_planned_running_completed() -> None:
    store = InMemoryResearchRunManifestStore()
    store.save(_manifest(status=ResearchRunStatus.PLANNED, updated_at=_utc(4, 0)))
    store.save(_manifest(status=ResearchRunStatus.RUNNING, updated_at=_utc(4, 1)))
    completed = _manifest(status=ResearchRunStatus.COMPLETED, updated_at=_utc(4, 2))
    store.save(completed)
    assert store.load(RunId("research-run-1")) == completed


def test_manifest_completed_to_running_rejected() -> None:
    store = InMemoryResearchRunManifestStore()
    store.save(_manifest(status=ResearchRunStatus.COMPLETED, updated_at=_utc(4, 1)))
    with pytest.raises(ValueError, match="invalid research run status transition"):
        store.save(_manifest(status=ResearchRunStatus.RUNNING, updated_at=_utc(4, 2)))


def test_artifact_save_load_round_trip() -> None:
    store = InMemoryEvaluationArtifactStore()
    artifact = _artifact()
    store.save(artifact)
    assert store.load("artifact-1") == artifact


def test_artifact_idempotent_save_accepted() -> None:
    store = InMemoryEvaluationArtifactStore()
    artifact = _artifact()
    store.save(artifact)
    store.save(artifact)
    assert store.load("artifact-1") == artifact


def test_artifact_conflicting_same_id_rejected() -> None:
    store = InMemoryEvaluationArtifactStore()
    store.save(_artifact(uri="memory://artifact-1"))
    with pytest.raises(ValueError, match="conflict"):
        store.save(_artifact(uri="memory://other"))


def test_artifact_list_for_run_filters_and_orders() -> None:
    store = InMemoryEvaluationArtifactStore()
    store.save(_artifact("b", run_id="run-1", created_at=_utc(5, 1)))
    store.save(_artifact("other", run_id="run-2", created_at=_utc(5, 0)))
    store.save(_artifact("a", run_id="run-1", created_at=_utc(5, 0)))
    assert [artifact.artifact_id for artifact in store.list_for_run(RunId("run-1"))] == [
        "a",
        "b",
    ]


def test_in_memory_research_stores_have_no_forbidden_imports() -> None:
    source_path = inspect.getsourcefile(InMemoryResearchRunManifestStore)
    assert source_path is not None
    source = Path(source_path).read_text()
    forbidden = (
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
        "LocalJsonlWal",
        "decide_wal_gc",
        "sidecars.local",
    )
    for name in forbidden:
        assert name not in source
