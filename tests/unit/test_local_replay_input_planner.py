from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from futures_bot.domain.ids import RunId
from futures_bot.domain.replay import (
    ReplayInputBatch,
    ReplayInputDataset,
    ReplayInputKind,
    ReplayInputQuality,
    ReplayInputRecord,
    ReplayInputSourceKind,
    ReplayInputValidationStatus,
    ReplayInstrumentRef,
    ReplayOrderingPolicy,
)
from futures_bot.domain.research import (
    DatasetSnapshot,
    ExecutionAssumptions,
    ExecutionMode,
    ReplayDataSourceKind,
    ReplayPlan,
    ResearchRunManifest,
    ResearchRunStatus,
    TemporalWindow,
    TemporalWindowKind,
)
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayInputBatchStore,
    InMemoryReplayInputDatasetStore,
)
from futures_bot.infrastructure.research.in_memory import (
    InMemoryReplayPlanStore,
    InMemoryResearchRunManifestStore,
)
from futures_bot.replay.local import LocalReplayInputPlanner


def _utc(day: int = 1, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def _window(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    *,
    window_id: str = "test-window",
) -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=start_at or _utc(2),
        end_at=end_at or _utc(3),
        window_id=window_id,
    )


def _manifest() -> ResearchRunManifest:
    return ResearchRunManifest(
        run_id=RunId("run-1"),
        experiment_id="exp-1",
        status=ResearchRunStatus.PLANNED,
        execution_mode=ExecutionMode.REPLAY,
        created_at=_utc(1),
        updated_at=_utc(1),
        git_commit="abc123",
        code_branch="main",
        config_hash="cfg",
        dataset=DatasetSnapshot(
            dataset_id="ds-1",
            source="curated",
            market_type="stablecoin-collateral-futures",
            symbols=("BTCUSDT", "ETHUSDC"),
            timeframe="1m",
            start_at=_utc(1),
            end_at=_utc(4),
            created_at=_utc(1),
        ),
        temporal_windows=(_window(),),
        execution_assumptions=ExecutionAssumptions(mode=ExecutionMode.REPLAY),
    )


def _replay_plan(
    *,
    dataset_id: str = "ds-1",
    temporal_windows: tuple[TemporalWindow, ...] | None = None,
) -> ReplayPlan:
    return ReplayPlan(
        replay_plan_id="replay-1",
        run_id=RunId("run-1"),
        data_source_kind=ReplayDataSourceKind.DATASET_SNAPSHOT,
        dataset_id=dataset_id,
        temporal_windows=temporal_windows or (_window(),),
        created_at=_utc(1, 1),
    )


def _instrument(symbol: str = "BTCUSDT") -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol=symbol,
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
    )


def _input_dataset(
    *,
    input_dataset_id: str = "input-ds-1",
    dataset_id: str = "ds-1",
    symbol: str = "BTCUSDT",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> ReplayInputDataset:
    return ReplayInputDataset(
        input_dataset_id=input_dataset_id,
        dataset_id=dataset_id,
        source_kind=ReplayInputSourceKind.DATASET_SNAPSHOT,
        quality=ReplayInputQuality.CLEANED,
        instruments=(_instrument(symbol),),
        start_at=start_at or _utc(1),
        end_at=end_at or _utc(4),
        created_at=_utc(1),
    )


def _record() -> ReplayInputRecord:
    return ReplayInputRecord(
        record_id="record-1",
        kind=ReplayInputKind.OHLCV_BAR,
        instrument=_instrument(),
        event_time=_utc(2, 1),
        source_sequence=0,
        payload={"close": Decimal("100")},
    )


def _batch(
    *,
    replay_plan_id: str = "replay-1",
    input_dataset_id: str = "input-ds-1",
    temporal_window: TemporalWindow | None = None,
) -> ReplayInputBatch:
    return ReplayInputBatch(
        batch_id="batch-1",
        replay_plan_id=replay_plan_id,
        input_dataset_id=input_dataset_id,
        temporal_window=temporal_window or _window(),
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        records=(_record(),),
        created_at=_utc(2),
        validation_status=ReplayInputValidationStatus.VALIDATED,
    )


def _planner(
    *,
    manifest_store: InMemoryResearchRunManifestStore | None = None,
    replay_store: InMemoryReplayPlanStore | None = None,
) -> tuple[
    LocalReplayInputPlanner,
    InMemoryReplayInputDatasetStore,
    InMemoryReplayInputBatchStore,
]:
    dataset_store = InMemoryReplayInputDatasetStore()
    batch_store = InMemoryReplayInputBatchStore()
    planner = LocalReplayInputPlanner(
        input_dataset_store=dataset_store,
        input_batch_store=batch_store,
        manifest_store=manifest_store,
        replay_plan_store=replay_store,
        now=lambda: _utc(5),
    )
    return planner, dataset_store, batch_store


def test_register_input_dataset_and_create_input_batch_save_metadata() -> None:
    planner, dataset_store, batch_store = _planner()
    dataset = planner.register_input_dataset(_input_dataset())
    batch = planner.create_input_batch(_batch())
    assert dataset_store.load(dataset.input_dataset_id) == dataset
    assert batch_store.load(batch.batch_id) == batch
    assert planner.input_datasets_for_dataset("ds-1") == (dataset,)
    assert planner.batches_for_replay_plan("replay-1") == (batch,)


def test_validate_dataset_against_manifest_accepts_matching_metadata() -> None:
    manifest_store = InMemoryResearchRunManifestStore()
    manifest_store.save(_manifest())
    planner, _, _ = _planner(manifest_store=manifest_store)
    planner.validate_dataset_against_manifest(_input_dataset(), RunId("run-1"))


def test_validate_dataset_against_manifest_rejects_mismatches() -> None:
    manifest_store = InMemoryResearchRunManifestStore()
    manifest_store.save(_manifest())
    planner, _, _ = _planner(manifest_store=manifest_store)
    with pytest.raises(KeyError, match="manifest"):
        planner.validate_dataset_against_manifest(_input_dataset(), RunId("missing-run"))
    with pytest.raises(ValueError, match="dataset_id"):
        planner.validate_dataset_against_manifest(
            _input_dataset(dataset_id="other-ds"), RunId("run-1")
        )
    with pytest.raises(ValueError, match="time range"):
        planner.validate_dataset_against_manifest(
            _input_dataset(
                start_at=datetime(2025, 12, 31, tzinfo=UTC),
                end_at=_utc(4),
            ),
            RunId("run-1"),
        )
    with pytest.raises(ValueError, match="symbol"):
        planner.validate_dataset_against_manifest(
            _input_dataset(symbol="SOLUSDT"), RunId("run-1")
        )


def test_validate_batch_against_replay_plan_accepts_exact_window_match() -> None:
    replay_store = InMemoryReplayPlanStore()
    replay_store.save(_replay_plan())
    planner, dataset_store, _ = _planner(replay_store=replay_store)
    dataset_store.save(_input_dataset())
    planner.validate_batch_against_replay_plan(_batch())


def test_validate_batch_against_replay_plan_rejects_bad_references() -> None:
    replay_store = InMemoryReplayPlanStore()
    replay_store.save(_replay_plan())
    planner, dataset_store, _ = _planner(replay_store=replay_store)
    with pytest.raises(KeyError, match="input dataset"):
        planner.validate_batch_against_replay_plan(_batch())
    dataset_store.save(_input_dataset(dataset_id="other-ds"))
    with pytest.raises(ValueError, match="dataset_id"):
        planner.validate_batch_against_replay_plan(_batch())
    with pytest.raises(KeyError, match="replay plan"):
        planner.validate_batch_against_replay_plan(_batch(replay_plan_id="missing-replay"))


def test_validate_batch_against_replay_plan_rejects_non_matching_window() -> None:
    replay_store = InMemoryReplayPlanStore()
    replay_store.save(_replay_plan())
    planner, dataset_store, _ = _planner(replay_store=replay_store)
    dataset_store.save(_input_dataset())
    with pytest.raises(ValueError, match="temporal_window"):
        planner.validate_batch_against_replay_plan(
            _batch(temporal_window=_window(window_id="different-window"))
        )


def test_local_replay_input_planner_has_no_forbidden_imports() -> None:
    source_path = inspect.getsourcefile(LocalReplayInputPlanner)
    assert source_path is not None
    source = Path(source_path).read_text(encoding="utf-8")
    forbidden = (
        "sqlalchemy",
        "confluent_kafka",
        "aiokafka",
        "pandas",
        "numpy",
        "sklearn",
        "torch",
        "open(",
        "write_text",
        "LocalJsonlWal",
        "decide_wal_gc",
        "threading",
        "asyncio",
        "subprocess",
        "sleep",
    )
    for name in forbidden:
        assert name not in source
