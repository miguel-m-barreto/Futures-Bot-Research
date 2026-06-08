from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

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
from futures_bot.domain.research import TemporalWindow, TemporalWindowKind
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayInputBatchStore,
    InMemoryReplayInputDatasetStore,
)
from futures_bot.ports.replay import (
    ReplayInputBatchStorePort,
    ReplayInputDatasetStorePort,
)


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _instrument(symbol: str = "BTCUSDT") -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol=symbol,
        market_type="stablecoin-collateral-futures",
        settlement_asset="USDT",
    )


def _dataset(
    input_dataset_id: str = "input-ds-1",
    *,
    dataset_id: str = "ds-1",
    created_at: datetime | None = None,
    content_hash: str = "hash-1",
) -> ReplayInputDataset:
    return ReplayInputDataset(
        input_dataset_id=input_dataset_id,
        dataset_id=dataset_id,
        source_kind=ReplayInputSourceKind.DATASET_SNAPSHOT,
        quality=ReplayInputQuality.CLEANED,
        instruments=(_instrument(),),
        start_at=_utc(0),
        end_at=_utc(3),
        created_at=created_at or _utc(4),
        content_hash=content_hash,
    )


def _record(record_id: str = "record-1", source_sequence: int = 0) -> ReplayInputRecord:
    return ReplayInputRecord(
        record_id=record_id,
        kind=ReplayInputKind.OHLCV_BAR,
        instrument=_instrument(),
        event_time=_utc(1),
        source_sequence=source_sequence,
        payload={
            "open": Decimal("100"),
            "high": Decimal("101"),
            "low": Decimal("99"),
            "close": Decimal("100"),
            "volume": Decimal("1"),
        },
    )


def _window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(0),
        end_at=_utc(3),
        window_id="test-window",
    )


def _batch(
    batch_id: str = "batch-1",
    *,
    replay_plan_id: str = "replay-1",
    input_dataset_id: str = "input-ds-1",
    created_at: datetime | None = None,
) -> ReplayInputBatch:
    return ReplayInputBatch(
        batch_id=batch_id,
        replay_plan_id=replay_plan_id,
        input_dataset_id=input_dataset_id,
        temporal_window=_window(),
        ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
        records=(_record(),),
        created_at=created_at or _utc(4),
        validation_status=ReplayInputValidationStatus.VALIDATED,
    )


def test_replay_input_stores_implement_ports() -> None:
    _: ReplayInputDatasetStorePort = InMemoryReplayInputDatasetStore()
    _: ReplayInputBatchStorePort = InMemoryReplayInputBatchStore()


def test_dataset_store_save_load_lists_and_conflicts() -> None:
    store = InMemoryReplayInputDatasetStore()
    first = _dataset("b", created_at=_utc(4), content_hash="same")
    second = _dataset("a", created_at=_utc(3), content_hash="same")
    other = _dataset("other", dataset_id="ds-2", created_at=_utc(2))
    store.save(first)
    store.save(first)
    store.save(second)
    store.save(other)
    assert store.load("b") == first
    assert [dataset.input_dataset_id for dataset in store.list_all()] == ["other", "a", "b"]
    assert [dataset.input_dataset_id for dataset in store.list_for_dataset("ds-1")] == [
        "a",
        "b",
    ]
    with pytest.raises(ValueError, match="input_dataset_id conflict"):
        store.save(_dataset("b", content_hash="other-hash"))


def test_dataset_store_revalidates_model_copy_invalid_state() -> None:
    store = InMemoryReplayInputDatasetStore()
    invalid = _dataset().model_copy(update={"record_count": -1})
    with pytest.raises(ValidationError, match="record_count"):
        store.save(invalid)
    invalid_bool = _dataset().model_copy(update={"record_count": True})
    with pytest.raises(ValidationError, match="record_count"):
        store.save(invalid_bool)


def test_batch_store_save_load_lists_and_conflicts() -> None:
    store = InMemoryReplayInputBatchStore()
    first = _batch("b", created_at=_utc(4))
    second = _batch("a", created_at=_utc(3))
    other = _batch("other", replay_plan_id="replay-2", input_dataset_id="input-ds-2")
    store.save(first)
    store.save(first)
    store.save(second)
    store.save(other)
    assert store.load("b") == first
    assert [batch.batch_id for batch in store.list_for_replay_plan("replay-1")] == [
        "a",
        "b",
    ]
    assert [batch.batch_id for batch in store.list_for_input_dataset("input-ds-1")] == [
        "a",
        "b",
    ]
    with pytest.raises(ValueError, match="batch_id conflict"):
        store.save(_batch("b", replay_plan_id="other-replay"))


def test_batch_store_revalidates_model_copy_invalid_state() -> None:
    store = InMemoryReplayInputBatchStore()
    invalid = _batch().model_copy(update={"records": (_record("same"), _record("same", 1))})
    with pytest.raises(ValidationError, match="duplicate record_id"):
        store.save(invalid)
    invalid_decimal_record = _record().model_copy(
        update={"payload": {"close": Decimal("NaN")}}
    )
    invalid_decimal_batch = _batch().model_copy(
        update={"records": (invalid_decimal_record,)}
    )
    with pytest.raises(ValidationError, match="finite"):
        store.save(invalid_decimal_batch)
    invalid_sequence_record = _record().model_copy(update={"source_sequence": True})
    invalid_sequence_batch = _batch().model_copy(
        update={"records": (invalid_sequence_record,)}
    )
    with pytest.raises(ValidationError, match="source_sequence"):
        store.save(invalid_sequence_batch)
    invalid_relation_record = _record().model_copy(
        update={
            "payload": {
                "open": Decimal("100"),
                "high": Decimal("80"),
                "low": Decimal("90"),
                "close": Decimal("95"),
                "volume": Decimal("1"),
            }
        }
    )
    invalid_relation_batch = _batch().model_copy(
        update={"records": (invalid_relation_record,)}
    )
    with pytest.raises(ValidationError, match="high"):
        store.save(invalid_relation_batch)
    invalid_trade_count_record = _record().model_copy(
        update={
            "payload": {
                "open": Decimal("100"),
                "high": Decimal("110"),
                "low": Decimal("90"),
                "close": Decimal("100"),
                "volume": Decimal("1"),
                "trade_count": True,
            }
        }
    )
    invalid_trade_count_batch = _batch().model_copy(
        update={"records": (invalid_trade_count_record,)}
    )
    with pytest.raises(ValidationError, match="trade_count"):
        store.save(invalid_trade_count_batch)
    invalid_kind_decimal_record = _record().model_copy(
        update={
            "kind": ReplayInputKind.MARK_PRICE,
            "payload": {"price": Decimal("Infinity")},
        }
    )
    invalid_kind_decimal_batch = _batch().model_copy(
        update={"records": (invalid_kind_decimal_record,)}
    )
    with pytest.raises(ValidationError, match="finite"):
        store.save(invalid_kind_decimal_batch)


def test_in_memory_replay_input_stores_have_no_forbidden_imports() -> None:
    source_path = inspect.getsourcefile(InMemoryReplayInputDatasetStore)
    assert source_path is not None
    source = Path(source_path).read_text(encoding="utf-8")
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "duckdb",
        "sqlite",
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
    )
    for name in forbidden:
        assert name not in source
