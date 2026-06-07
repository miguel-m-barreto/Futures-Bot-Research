from __future__ import annotations

import hashlib
import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import RunId
from futures_bot.domain.research import (
    ConfigSnapshot,
    ConfigSnapshotKind,
    CostScenario,
    DatasetSnapshot,
    EvaluationObjective,
    EvaluationPlan,
    ExecutionAssumptions,
    ExecutionMode,
    ExpectedOutcome,
    ExperimentDefinition,
    ExperimentStatus,
    MetricDirection,
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
    InMemoryConfigSnapshotStore,
    InMemoryEvaluationPlanStore,
    InMemoryExperimentDefinitionStore,
    InMemoryReplayPlanStore,
    InMemoryResearchRunManifestStore,
    InMemoryRunLineageStore,
)
from futures_bot.ports.research import (
    ConfigSnapshotStorePort,
    ExperimentDefinitionStorePort,
    RunLineageStorePort,
)
from futures_bot.research.registry import LocalExperimentRegistry


def _utc(day: int = 1, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def _sha(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _experiment(
    experiment_id: str = "exp-1",
    *,
    status: ExperimentStatus = ExperimentStatus.PLANNED,
    updated_at: datetime | None = None,
    parent_experiment_id: str | None = None,
) -> ExperimentDefinition:
    return ExperimentDefinition(
        experiment_id=experiment_id,
        title="Random baseline cost degradation",
        objective="Predeclare a random-control degradation expectation.",
        status=status,
        created_at=_utc(1),
        updated_at=updated_at or _utc(1),
        owner="research",
        tags=("baseline", "costs"),
        parent_experiment_id=parent_experiment_id,
    )


def _config(
    config_id: str = "cfg-1",
    *,
    kind: ConfigSnapshotKind = ConfigSnapshotKind.RUN_CONFIG,
    canonical_json: str = '{"a":1}',
    sha256: str | None = None,
    created_at: datetime | None = None,
) -> ConfigSnapshot:
    return ConfigSnapshot(
        config_id=config_id,
        kind=kind,
        created_at=created_at or _utc(2),
        canonical_json=canonical_json,
        sha256=sha256 or _sha(canonical_json),
    )


def _lineage(  # noqa: PLR0913
    lineage_id: str = "lineage-1",
    *,
    run_id: str = "run-1",
    experiment_id: str = "exp-1",
    kind: RunLineageKind = RunLineageKind.ROOT,
    config_ids: tuple[str, ...] = ("cfg-1",),
    parent_run_id: RunId | None = None,
    replay_plan_id: str | None = None,
    evaluation_plan_id: str | None = None,
    created_at: datetime | None = None,
) -> RunLineageRecord:
    return RunLineageRecord(
        lineage_id=lineage_id,
        run_id=RunId(run_id),
        experiment_id=experiment_id,
        kind=kind,
        created_at=created_at or _utc(3),
        config_ids=config_ids,
        parent_run_id=parent_run_id,
        replay_plan_id=replay_plan_id,
        evaluation_plan_id=evaluation_plan_id,
    )


def _dataset() -> DatasetSnapshot:
    return DatasetSnapshot(
        dataset_id="ds-1",
        source="local-curated",
        market_type="stablecoin-collateral-futures",
        symbols=("BTCUSDT",),
        timeframe="1m",
        start_at=_utc(1),
        end_at=_utc(5),
        created_at=_utc(1),
    )


def _window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(2),
        end_at=_utc(3),
        window_id="test-001",
    )


def _manifest() -> ResearchRunManifest:
    return ResearchRunManifest(
        run_id=RunId("run-1"),
        experiment_id="exp-1",
        status=ResearchRunStatus.PLANNED,
        execution_mode=ExecutionMode.REPLAY,
        created_at=_utc(2),
        updated_at=_utc(2),
        git_commit="abc123",
        code_branch="main",
        config_hash=_sha('{"a":1}'),
        dataset=_dataset(),
        temporal_windows=(_window(),),
        execution_assumptions=ExecutionAssumptions(
            mode=ExecutionMode.REPLAY,
            taker_fee_bps=Decimal("5"),
        ),
        expected_outcomes=(
            ExpectedOutcome(
                setup_id="CONTROL/random",
                expectation="Expected to degrade after costs.",
                primary_measurements=("pnl_after_costs",),
            ),
        ),
    )


def _replay_plan() -> ReplayPlan:
    return ReplayPlan(
        replay_plan_id="replay-1",
        run_id=RunId("run-1"),
        data_source_kind=ReplayDataSourceKind.DATASET_SNAPSHOT,
        dataset_id="ds-1",
        temporal_windows=(_window(),),
        created_at=_utc(3),
    )


def _evaluation_plan() -> EvaluationPlan:
    return EvaluationPlan(
        evaluation_plan_id="eval-1",
        run_id=RunId("run-1"),
        replay_plan_id="replay-1",
        objective=EvaluationObjective.BASELINE_COMPARISON,
        metric_specs=(
            MetricSpec(
                metric_id="pnl_after_costs",
                name="PnL after costs",
                direction=MetricDirection.MAXIMIZE,
                is_primary=True,
            ),
        ),
        cost_scenarios=(CostScenario(scenario_id="baseline-costs"),),
        created_at=_utc(4),
        expected_outcome_ids=("CONTROL/random",),
    )


def test_experiment_definition_validates_required_fields_and_tags() -> None:
    experiment = _experiment()
    assert experiment.experiment_id == "exp-1"
    with pytest.raises(ValidationError, match="field"):
        _experiment("").model_copy()
    with pytest.raises(ValidationError, match="duplicate tags"):
        ExperimentDefinition(
            experiment_id="exp-2",
            title="Title",
            objective="Objective",
            status=ExperimentStatus.PLANNED,
            created_at=_utc(),
            updated_at=_utc(),
            tags=("a", "a"),
        )


def test_config_snapshot_validates_json_and_sha() -> None:
    assert _config().canonical_json == '{"a":1}'
    with pytest.raises(ValidationError, match="sha256"):
        _config(sha256="bad")
    with pytest.raises(ValidationError, match="canonical_json"):
        _config(sha256=_sha('{"a":2}'))
    with pytest.raises(ValidationError, match="JSON object"):
        _config(canonical_json='["not-object"]')
    with pytest.raises(ValidationError, match="valid JSON"):
        _config(canonical_json="{bad")


def test_run_lineage_record_validation() -> None:
    assert _lineage().kind is RunLineageKind.ROOT
    with pytest.raises(ValidationError, match="config_ids"):
        _lineage(config_ids=())
    with pytest.raises(ValidationError, match="duplicate config_ids"):
        _lineage(config_ids=("cfg-1", "cfg-1"))
    with pytest.raises(ValidationError, match="parent_run_id"):
        _lineage(parent_run_id=RunId("run-1"))
    with pytest.raises(ValidationError, match="ROOT"):
        _lineage(parent_run_id=RunId("parent-run"))


def test_registry_stores_implement_ports() -> None:
    _: ExperimentDefinitionStorePort = InMemoryExperimentDefinitionStore()
    _: ConfigSnapshotStorePort = InMemoryConfigSnapshotStore()
    _: RunLineageStorePort = InMemoryRunLineageStore()


def test_experiment_store_round_trip_ordering_and_transitions() -> None:
    store = InMemoryExperimentDefinitionStore()
    store.save(_experiment("exp-b", updated_at=_utc(1, 2)))
    store.save(_experiment("exp-a", updated_at=_utc(1, 1)))
    assert [experiment.experiment_id for experiment in store.list_all()] == [
        "exp-a",
        "exp-b",
    ]
    with pytest.raises(ValueError, match="updated_at regression"):
        store.save(_experiment("exp-a", updated_at=_utc(1, 0)))
    store.save(
        _experiment(
            "exp-a",
            status=ExperimentStatus.COMPLETED,
            updated_at=_utc(1, 2),
        )
    )
    store.save(
        _experiment(
            "exp-a",
            status=ExperimentStatus.ARCHIVED,
            updated_at=_utc(1, 3),
        )
    )
    with pytest.raises(ValueError, match="invalid experiment status transition"):
        store.save(
            _experiment(
                "exp-a",
                status=ExperimentStatus.ACTIVE,
                updated_at=_utc(1, 4),
            )
        )


def test_experiment_store_rejects_parent_change() -> None:
    store = InMemoryExperimentDefinitionStore()
    store.save(_experiment(parent_experiment_id="parent-1"))
    with pytest.raises(ValueError, match="parent_experiment_id"):
        store.save(_experiment(updated_at=_utc(1, 1), parent_experiment_id="parent-2"))


def test_config_store_round_trip_conflict_and_filters() -> None:
    store = InMemoryConfigSnapshotStore()
    first = _config("b", created_at=_utc(2, 1))
    second = _config(
        "a",
        kind=ConfigSnapshotKind.DATASET_CONFIG,
        canonical_json='{"dataset":"ds-1"}',
        created_at=_utc(2, 0),
    )
    same_hash = _config(
        "same-hash",
        canonical_json='{"a":1}',
        created_at=_utc(2, 2),
    )
    store.save(first)
    store.save(first)
    store.save(second)
    store.save(same_hash)
    assert store.load("b") == first
    assert [snapshot.config_id for snapshot in store.list_all()] == [
        "a",
        "b",
        "same-hash",
    ]
    assert [snapshot.config_id for snapshot in store.list_by_kind(first.kind)] == [
        "b",
        "same-hash",
    ]
    with pytest.raises(ValueError, match="config_id conflict"):
        store.save(_config("b", canonical_json='{"other":1}'))


def test_config_store_revalidates_model_copy_hash_mismatch() -> None:
    store = InMemoryConfigSnapshotStore()
    valid = _config()
    invalid = valid.model_copy(update={"sha256": _sha('{"a":2}')})

    with pytest.raises(ValidationError, match="canonical_json"):
        store.save(invalid)


def test_lineage_store_round_trip_conflict_and_filters() -> None:
    store = InMemoryRunLineageStore()
    first = _lineage("b", created_at=_utc(3, 1))
    second = _lineage("a", experiment_id="exp-2", created_at=_utc(3, 0))
    store.save(first)
    store.save(first)
    store.save(second)
    assert store.load("b") == first
    assert [record.lineage_id for record in store.list_for_run(RunId("run-1"))] == [
        "a",
        "b",
    ]
    assert [record.lineage_id for record in store.list_for_experiment("exp-1")] == [
        "b"
    ]
    with pytest.raises(ValueError, match="lineage_id conflict"):
        store.save(_lineage("b", experiment_id="other-exp"))


def test_local_registry_registers_experiment_config_and_lineage() -> None:
    experiment_store = InMemoryExperimentDefinitionStore()
    config_store = InMemoryConfigSnapshotStore()
    lineage_store = InMemoryRunLineageStore()
    registry = LocalExperimentRegistry(
        experiment_store=experiment_store,
        config_store=config_store,
        lineage_store=lineage_store,
        now=lambda: _utc(5),
    )
    registry.register_experiment(_experiment())
    snapshot = registry.fingerprint_config(
        config_id="cfg-1",
        kind=ConfigSnapshotKind.RUN_CONFIG,
        payload={"threshold": Decimal("1.0")},
    )
    lineage = registry.register_lineage(_lineage(config_ids=("cfg-1",)))

    assert config_store.load("cfg-1") == snapshot
    assert registry.lineage_for_run(RunId("run-1")) == (lineage,)
    assert registry.configs_for_lineage("lineage-1") == (snapshot,)


def test_local_registry_rejects_model_copy_hash_mismatch() -> None:
    registry = LocalExperimentRegistry(
        experiment_store=InMemoryExperimentDefinitionStore(),
        config_store=InMemoryConfigSnapshotStore(),
        lineage_store=InMemoryRunLineageStore(),
    )
    invalid = _config().model_copy(update={"sha256": _sha('{"a":2}')})

    with pytest.raises(ValidationError, match="canonical_json"):
        registry.register_config_snapshot(invalid)


def test_local_registry_rejects_missing_references() -> None:
    registry = LocalExperimentRegistry(
        experiment_store=InMemoryExperimentDefinitionStore(),
        config_store=InMemoryConfigSnapshotStore(),
        lineage_store=InMemoryRunLineageStore(),
    )
    with pytest.raises(KeyError, match="experiment"):
        registry.register_lineage(_lineage())

    registry.register_experiment(_experiment())
    with pytest.raises(KeyError, match="config"):
        registry.register_lineage(_lineage(config_ids=("missing-cfg",)))


def test_local_registry_validates_optional_manifest_and_plan_references() -> None:
    experiment_store = InMemoryExperimentDefinitionStore()
    config_store = InMemoryConfigSnapshotStore()
    lineage_store = InMemoryRunLineageStore()
    manifest_store = InMemoryResearchRunManifestStore()
    replay_store = InMemoryReplayPlanStore()
    evaluation_store = InMemoryEvaluationPlanStore()
    registry = LocalExperimentRegistry(
        experiment_store=experiment_store,
        config_store=config_store,
        lineage_store=lineage_store,
        manifest_store=manifest_store,
        replay_plan_store=replay_store,
        evaluation_plan_store=evaluation_store,
    )
    registry.register_experiment(_experiment())
    registry.register_config_snapshot(_config())
    manifest_store.save(_manifest())
    replay_store.save(_replay_plan())
    evaluation_store.save(_evaluation_plan())

    lineage = _lineage(replay_plan_id="replay-1", evaluation_plan_id="eval-1")
    registry.register_lineage(lineage)
    assert registry.lineage_for_experiment("exp-1") == (lineage,)

    with pytest.raises(KeyError, match="research run manifest"):
        registry.validate_lineage_references(_lineage(run_id="missing-run"))


def test_registry_modules_have_no_forbidden_imports_or_file_io() -> None:
    for cls in (LocalExperimentRegistry, InMemoryExperimentDefinitionStore):
        source_path = inspect.getsourcefile(cls)
        assert source_path is not None
        source = Path(source_path).read_text(encoding="utf-8")
        forbidden = (
            "pandas",
            "numpy",
            "sklearn",
            "torch",
            "sqlalchemy",
            "confluent_kafka",
            "aiokafka",
            "LocalJsonlWal",
            "decide_wal_gc",
            "open(",
            "write_text",
        )
        for name in forbidden:
            assert name not in source
