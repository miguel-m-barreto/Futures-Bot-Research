from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

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


def _utc(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def test_replay_input_contract_flow_is_metadata_only() -> None:
    manifest_store = InMemoryResearchRunManifestStore()
    replay_plan_store = InMemoryReplayPlanStore()
    input_dataset_store = InMemoryReplayInputDatasetStore()
    input_batch_store = InMemoryReplayInputBatchStore()
    planner = LocalReplayInputPlanner(
        input_dataset_store=input_dataset_store,
        input_batch_store=input_batch_store,
        replay_plan_store=replay_plan_store,
        manifest_store=manifest_store,
    )

    dataset_snapshot = DatasetSnapshot(
        dataset_id="ds-stablecoin-futures",
        source="curated-historical-futures-bars",
        market_type="stablecoin-collateral-futures",
        symbols=("BTCUSDT",),
        timeframe="1m",
        start_at=_utc(1),
        end_at=_utc(3),
        created_at=_utc(1),
    )
    window = TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(2),
        end_at=_utc(3),
        window_id="test-window",
    )
    manifest_store.save(
        ResearchRunManifest(
            run_id=RunId("run-1"),
            experiment_id="exp-replay-input-contract",
            status=ResearchRunStatus.PLANNED,
            execution_mode=ExecutionMode.REPLAY,
            created_at=_utc(1),
            updated_at=_utc(1),
            git_commit="abc123",
            code_branch="main",
            config_hash="cfg",
            dataset=dataset_snapshot,
            temporal_windows=(window,),
            execution_assumptions=ExecutionAssumptions(mode=ExecutionMode.REPLAY),
        )
    )
    replay_plan = ReplayPlan(
        replay_plan_id="replay-1",
        run_id=RunId("run-1"),
        data_source_kind=ReplayDataSourceKind.DATASET_SNAPSHOT,
        dataset_id=dataset_snapshot.dataset_id,
        temporal_windows=(window,),
        created_at=_utc(1, 1),
    )
    replay_plan_store.save(replay_plan)

    instrument = ReplayInstrumentRef(
        venue="binance",
        symbol="BTCUSDT",
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
        quote_asset="USDT",
        base_asset="BTC",
    )
    input_dataset = ReplayInputDataset(
        input_dataset_id="input-ds-1",
        dataset_id=dataset_snapshot.dataset_id,
        source_kind=ReplayInputSourceKind.DATASET_SNAPSHOT,
        quality=ReplayInputQuality.CLEANED,
        instruments=(instrument,),
        start_at=dataset_snapshot.start_at,
        end_at=dataset_snapshot.end_at,
        created_at=_utc(1, 2),
        record_count=2,
    )
    planner.validate_dataset_against_manifest(input_dataset, RunId("run-1"))
    planner.register_input_dataset(input_dataset)

    records = (
        ReplayInputRecord(
            record_id="bar-1",
            kind=ReplayInputKind.OHLCV_BAR,
            instrument=instrument,
            event_time=_utc(2, 0),
            source_sequence=0,
            payload={
                "open": Decimal("100"),
                "high": Decimal("101"),
                "low": Decimal("99"),
                "close": Decimal("100.5"),
                "volume": Decimal("12.5"),
            },
        ),
        ReplayInputRecord(
            record_id="bar-2",
            kind=ReplayInputKind.OHLCV_BAR,
            instrument=instrument,
            event_time=_utc(2, 1),
            source_sequence=1,
            payload={
                "open": Decimal("100.5"),
                "high": Decimal("102"),
                "low": Decimal("100"),
                "close": Decimal("101"),
                "volume": Decimal("9.75"),
            },
        ),
    )
    batch = planner.create_input_batch(
        ReplayInputBatch(
            batch_id="batch-1",
            replay_plan_id=replay_plan.replay_plan_id,
            input_dataset_id=input_dataset.input_dataset_id,
            temporal_window=window,
            ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
            records=records,
            created_at=_utc(2, 2),
            validation_status=ReplayInputValidationStatus.VALIDATED,
        )
    )

    assert batch.records == records
    assert all(window.start_at <= record.event_time < window.end_at for record in records)
    assert input_dataset.dataset_id == dataset_snapshot.dataset_id
    assert batch.replay_plan_id == replay_plan.replay_plan_id
    assert input_batch_store.load("batch-1") == batch
    assert not hasattr(planner, "run_replay")
    assert not hasattr(planner, "calculate_metrics")

    source_path = inspect.getsourcefile(LocalReplayInputPlanner)
    assert source_path is not None
    source = Path(source_path).read_text(encoding="utf-8")
    assert "open(" not in source
    assert "write_text" not in source
    assert "EvaluationResultSet" not in source
