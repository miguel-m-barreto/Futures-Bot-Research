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
    EvaluationResultSet,
    EvaluationResultStatus,
    ExecutionAssumptions,
    ExecutionMode,
    ExpectedOutcomeAssessment,
    ExpectedOutcomeAssessmentStatus,
    MetricObservation,
    ResearchRunManifest,
    ResearchRunStatus,
    TemporalWindow,
    TemporalWindowKind,
)
from futures_bot.infrastructure.research.in_memory import (
    InMemoryEvaluationArtifactStore,
    InMemoryEvaluationResultStore,
    InMemoryResearchRunManifestStore,
)
from futures_bot.ports.research import (
    EvaluationArtifactStorePort,
    EvaluationResultStorePort,
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


def _result_set(
    result_set_id: str = "result-set-1",
    *,
    run_id: str = "research-run-1",
    status: EvaluationResultStatus = EvaluationResultStatus.DRAFT,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> EvaluationResultSet:
    return EvaluationResultSet(
        result_set_id=result_set_id,
        run_id=RunId(run_id),
        evaluation_plan_id="eval-1",
        status=status,
        created_at=created_at or _utc(6),
        updated_at=updated_at or created_at or _utc(6),
    )


def _observation(
    observation_id: str = "obs-1",
    *,
    run_id: str = "research-run-1",
    evaluation_plan_id: str = "eval-1",
) -> MetricObservation:
    return MetricObservation(
        observation_id=observation_id,
        run_id=RunId(run_id),
        evaluation_plan_id=evaluation_plan_id,
        metric_id="pnl_after_costs",
        observed_at=_utc(7),
        value=Decimal("-1.25"),
    )


def _assessment(
    assessment_id: str = "assessment-1",
    *,
    run_id: str = "research-run-1",
    evaluation_plan_id: str = "eval-1",
) -> ExpectedOutcomeAssessment:
    return ExpectedOutcomeAssessment(
        assessment_id=assessment_id,
        run_id=RunId(run_id),
        evaluation_plan_id=evaluation_plan_id,
        setup_id="CONTROL/random",
        status=ExpectedOutcomeAssessmentStatus.CONFIRMED,
        assessed_at=_utc(7),
        rationale="Manual assessment.",
    )


def test_manifest_store_implements_port() -> None:
    _: ResearchRunManifestStorePort = InMemoryResearchRunManifestStore()


def test_artifact_store_implements_port() -> None:
    _: EvaluationArtifactStorePort = InMemoryEvaluationArtifactStore()


def test_result_store_implements_port() -> None:
    _: EvaluationResultStorePort = InMemoryEvaluationResultStore()


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


def test_result_store_save_load_round_trip() -> None:
    store = InMemoryEvaluationResultStore()
    result_set = _result_set()
    store.save(result_set)
    assert store.load("result-set-1") == result_set


def test_result_store_list_for_run_filters_and_orders() -> None:
    store = InMemoryEvaluationResultStore()
    store.save(_result_set("b", run_id="run-1", created_at=_utc(6, 1)))
    store.save(_result_set("other", run_id="run-2", created_at=_utc(6, 0)))
    store.save(_result_set("a", run_id="run-1", created_at=_utc(6, 0)))
    assert [result.result_set_id for result in store.list_for_run(RunId("run-1"))] == [
        "a",
        "b",
    ]


def test_result_store_list_for_evaluation_plan_filters_and_orders() -> None:
    store = InMemoryEvaluationResultStore()
    store.save(_result_set("b", created_at=_utc(6, 1)))
    store.save(
        _result_set("other", created_at=_utc(6, 0)).model_copy(
            update={"evaluation_plan_id": "eval-2"}
        )
    )
    store.save(_result_set("a", created_at=_utc(6, 0)))
    assert [
        result.result_set_id
        for result in store.list_for_evaluation_plan("eval-1")
    ] == ["a", "b"]


def test_result_store_older_updated_at_rejected() -> None:
    store = InMemoryEvaluationResultStore()
    store.save(_result_set(updated_at=_utc(6, 1)))
    with pytest.raises(ValueError, match="updated_at regression"):
        store.save(_result_set(updated_at=_utc(6, 0)))


def test_result_store_conflicting_id_rejected() -> None:
    store = InMemoryEvaluationResultStore()
    store.save(_result_set(run_id="run-1"))
    with pytest.raises(ValueError, match="run_id mismatch"):
        store.save(_result_set(run_id="run-2"))
    with pytest.raises(ValueError, match="evaluation_plan_id mismatch"):
        store.save(
            _result_set(run_id="run-1", updated_at=_utc(6, 1)).model_copy(
                update={"evaluation_plan_id": "eval-2"}
            )
        )


def test_result_store_revalidates_observation_context_after_model_copy() -> None:
    store = InMemoryEvaluationResultStore()
    invalid = _result_set().model_copy(
        update={"observations": (_observation(run_id="other-run"),)}
    )

    with pytest.raises(ValueError, match="observation run_id"):
        store.save(invalid)


def test_result_store_revalidates_assessment_context_after_model_copy() -> None:
    store = InMemoryEvaluationResultStore()
    invalid = _result_set().model_copy(
        update={"assessments": (_assessment(evaluation_plan_id="other-plan"),)}
    )

    with pytest.raises(ValueError, match="assessment evaluation_plan_id"):
        store.save(invalid)


def test_result_store_revalidates_duplicate_nested_ids_after_model_copy() -> None:
    store = InMemoryEvaluationResultStore()
    invalid_observations = _result_set().model_copy(
        update={"observations": (_observation("obs-1"), _observation("obs-1"))}
    )
    invalid_assessments = _result_set("result-set-2").model_copy(
        update={"assessments": (_assessment("a-1"), _assessment("a-1"))}
    )

    with pytest.raises(ValueError, match="duplicate observation_id"):
        store.save(invalid_observations)
    with pytest.raises(ValueError, match="duplicate assessment_id"):
        store.save(invalid_assessments)


def test_result_store_valid_draft_recorded_reviewed_transition() -> None:
    store = InMemoryEvaluationResultStore()
    store.save(_result_set(status=EvaluationResultStatus.DRAFT, updated_at=_utc(6, 0)))
    store.save(_result_set(status=EvaluationResultStatus.RECORDED, updated_at=_utc(6, 1)))
    reviewed = _result_set(status=EvaluationResultStatus.REVIEWED, updated_at=_utc(6, 2))
    store.save(reviewed)
    assert store.load("result-set-1") == reviewed


def test_result_store_reviewed_to_recorded_rejected() -> None:
    store = InMemoryEvaluationResultStore()
    store.save(_result_set(status=EvaluationResultStatus.REVIEWED, updated_at=_utc(6, 1)))
    with pytest.raises(ValueError, match="invalid evaluation result status transition"):
        store.save(_result_set(status=EvaluationResultStatus.RECORDED, updated_at=_utc(6, 2)))


def test_result_store_reviewed_to_reviewed_rejects_added_observation() -> None:
    store = InMemoryEvaluationResultStore()
    reviewed = _result_set(status=EvaluationResultStatus.REVIEWED, updated_at=_utc(6, 1))
    store.save(reviewed)

    mutated = reviewed.model_copy(
        update={
            "observations": (_observation(),),
            "updated_at": _utc(6, 2),
        }
    )

    with pytest.raises(ValueError, match="reviewed evaluation result sets are immutable"):
        store.save(mutated)


def test_result_store_reviewed_to_reviewed_rejects_added_assessment() -> None:
    store = InMemoryEvaluationResultStore()
    reviewed = _result_set(status=EvaluationResultStatus.REVIEWED, updated_at=_utc(6, 1))
    store.save(reviewed)

    mutated = reviewed.model_copy(
        update={
            "assessments": (_assessment(),),
            "updated_at": _utc(6, 2),
        }
    )

    with pytest.raises(ValueError, match="reviewed evaluation result sets are immutable"):
        store.save(mutated)


def test_result_store_reviewed_to_reviewed_rejects_added_artifact_id() -> None:
    store = InMemoryEvaluationResultStore()
    reviewed = _result_set(status=EvaluationResultStatus.REVIEWED, updated_at=_utc(6, 1))
    store.save(reviewed)

    mutated = reviewed.model_copy(
        update={
            "artifact_ids": ("artifact-1",),
            "updated_at": _utc(6, 2),
        }
    )

    with pytest.raises(ValueError, match="reviewed evaluation result sets are immutable"):
        store.save(mutated)


def test_result_store_reviewed_to_reviewed_rejects_changed_notes() -> None:
    store = InMemoryEvaluationResultStore()
    reviewed = _result_set(status=EvaluationResultStatus.REVIEWED, updated_at=_utc(6, 1))
    store.save(reviewed)

    mutated = reviewed.model_copy(
        update={
            "notes": "Changed after review.",
            "updated_at": _utc(6, 2),
        }
    )

    with pytest.raises(ValueError, match="reviewed evaluation result sets are immutable"):
        store.save(mutated)


def test_result_store_reviewed_exact_idempotent_save_allowed() -> None:
    store = InMemoryEvaluationResultStore()
    reviewed = _result_set(
        status=EvaluationResultStatus.REVIEWED,
        updated_at=_utc(6, 1),
    ).model_copy(
        update={
            "observations": (_observation(),),
            "assessments": (_assessment(),),
            "artifact_ids": ("artifact-1",),
            "notes": "Reviewed.",
        }
    )

    store.save(reviewed)
    store.save(reviewed)

    assert store.load("result-set-1") == reviewed


def test_result_store_reviewed_to_invalidated_allowed() -> None:
    store = InMemoryEvaluationResultStore()
    reviewed = _result_set(
        status=EvaluationResultStatus.REVIEWED,
        updated_at=_utc(6, 1),
    ).model_copy(
        update={
            "observations": (_observation(),),
            "assessments": (_assessment(),),
            "artifact_ids": ("artifact-1",),
            "notes": "Reviewed.",
        }
    )
    store.save(reviewed)
    invalidated = reviewed.model_copy(
        update={
            "status": EvaluationResultStatus.INVALIDATED,
            "updated_at": _utc(6, 2),
            "notes": "Reviewed.\nPost-review correction.",
        }
    )
    store.save(invalidated)
    assert store.load("result-set-1") == invalidated


def test_result_store_reviewed_to_invalidated_rejects_changed_observations() -> None:
    store = InMemoryEvaluationResultStore()
    reviewed = _result_set(status=EvaluationResultStatus.REVIEWED, updated_at=_utc(6, 1))
    store.save(reviewed)

    invalidated = reviewed.model_copy(
        update={
            "status": EvaluationResultStatus.INVALIDATED,
            "observations": (_observation(),),
            "updated_at": _utc(6, 2),
            "notes": "Post-review correction.",
        }
    )

    with pytest.raises(ValueError, match="without changing observations"):
        store.save(invalidated)


def test_result_store_invalidated_to_invalidated_rejects_added_observation() -> None:
    store = InMemoryEvaluationResultStore()
    invalidated = _result_set(
        status=EvaluationResultStatus.INVALIDATED,
        updated_at=_utc(6, 1),
    )
    store.save(invalidated)

    mutated = invalidated.model_copy(
        update={
            "observations": (_observation(),),
            "updated_at": _utc(6, 2),
        }
    )

    with pytest.raises(ValueError, match="invalidated evaluation result sets are immutable"):
        store.save(mutated)


def test_result_store_invalidated_exact_idempotent_save_allowed() -> None:
    store = InMemoryEvaluationResultStore()
    invalidated = _result_set(
        status=EvaluationResultStatus.INVALIDATED,
        updated_at=_utc(6, 1),
    ).model_copy(
        update={
            "observations": (_observation(),),
            "assessments": (_assessment(),),
            "artifact_ids": ("artifact-1",),
            "notes": "Invalidated.",
        }
    )

    store.save(invalidated)
    store.save(invalidated)

    assert store.load("result-set-1") == invalidated


def test_result_store_invalidated_to_recorded_rejected() -> None:
    store = InMemoryEvaluationResultStore()
    store.save(
        _result_set(status=EvaluationResultStatus.INVALIDATED, updated_at=_utc(6, 1))
    )
    with pytest.raises(ValueError, match="invalid evaluation result status transition"):
        store.save(_result_set(status=EvaluationResultStatus.RECORDED, updated_at=_utc(6, 2)))


def test_result_store_invalidated_to_reviewed_rejected() -> None:
    store = InMemoryEvaluationResultStore()
    store.save(
        _result_set(status=EvaluationResultStatus.INVALIDATED, updated_at=_utc(6, 1))
    )
    with pytest.raises(ValueError, match="invalid evaluation result status transition"):
        store.save(_result_set(status=EvaluationResultStatus.REVIEWED, updated_at=_utc(6, 2)))


def test_result_store_draft_to_reviewed_rejected() -> None:
    store = InMemoryEvaluationResultStore()
    store.save(_result_set(status=EvaluationResultStatus.DRAFT, updated_at=_utc(6, 1)))
    with pytest.raises(ValueError, match="RECORDED"):
        store.save(_result_set(status=EvaluationResultStatus.REVIEWED, updated_at=_utc(6, 2)))


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
