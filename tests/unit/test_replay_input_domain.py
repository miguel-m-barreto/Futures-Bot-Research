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


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def _instrument(symbol: str = "BTCUSDT", settlement_asset: str = "USDT") -> ReplayInstrumentRef:
    return ReplayInstrumentRef(
        venue="binance",
        symbol=symbol,
        market_type="stablecoin-collateral-futures",
        settlement_asset=settlement_asset,
        quote_asset=settlement_asset,
        base_asset=symbol[:-4],
    )


def _record(
    record_id: str = "record-1",
    *,
    event_time: datetime | None = None,
    source_sequence: int = 0,
    kind: ReplayInputKind = ReplayInputKind.OHLCV_BAR,
) -> ReplayInputRecord:
    payload: dict[str, object]
    if kind is ReplayInputKind.MARK_PRICE:
        payload = {"price": Decimal("100")}
    else:
        payload = {
            "open": Decimal("100"),
            "high": Decimal("101"),
            "low": Decimal("99"),
            "close": Decimal("100.5"),
            "volume": Decimal("12.3"),
        }
    return ReplayInputRecord(
        record_id=record_id,
        kind=kind,
        instrument=_instrument(),
        event_time=event_time or _utc(1),
        source_sequence=source_sequence,
        payload=payload,
    )


def _dataset(*, instruments: tuple[ReplayInstrumentRef, ...] | None = None) -> ReplayInputDataset:
    return ReplayInputDataset(
        input_dataset_id="input-ds-1",
        dataset_id="ds-1",
        source_kind=ReplayInputSourceKind.DATASET_SNAPSHOT,
        quality=ReplayInputQuality.CLEANED,
        instruments=instruments or (_instrument(),),
        start_at=_utc(0),
        end_at=_utc(3),
        created_at=_utc(4),
        record_count=1,
    )


def _window() -> TemporalWindow:
    return TemporalWindow(
        kind=TemporalWindowKind.TEST,
        start_at=_utc(0),
        end_at=_utc(3),
        window_id="test-window",
    )


def _batch(
    *,
    records: tuple[ReplayInputRecord, ...] | None = None,
    ordering_policy: ReplayOrderingPolicy = ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE,
    validation_status: ReplayInputValidationStatus = ReplayInputValidationStatus.VALIDATED,
) -> ReplayInputBatch:
    return ReplayInputBatch(
        batch_id="batch-1",
        replay_plan_id="replay-1",
        input_dataset_id="input-ds-1",
        temporal_window=_window(),
        ordering_policy=ordering_policy,
        records=records if records is not None else (_record(),),
        created_at=_utc(4),
        validation_status=validation_status,
    )


def test_valid_replay_instrument_ref_with_usdt_settlement() -> None:
    instrument = _instrument()
    assert str(instrument.settlement_asset) == "USDT"
    assert str(instrument.quote_asset) == "USDT"


def test_replay_instrument_ref_rejects_unsupported_stable_asset() -> None:
    with pytest.raises(ValidationError, match="USDT or USDC"):
        _instrument(settlement_asset="USD")


def test_replay_input_record_accepts_decimal_payload_and_rejects_float() -> None:
    record = _record()
    assert record.payload["close"] == Decimal("100.5")
    with pytest.raises(ValidationError, match="floats"):
        ReplayInputRecord(
            record_id="record-float",
            kind=ReplayInputKind.OHLCV_BAR,
            instrument=_instrument(),
            event_time=_utc(1),
            source_sequence=0,
            payload={"nested": {"close": 100.5}},
        )


def test_replay_input_record_rejects_non_finite_decimal_payloads() -> None:
    for value in (Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ValidationError, match="finite"):
            ReplayInputRecord(
                record_id=f"record-{value}",
                kind=ReplayInputKind.OHLCV_BAR,
                instrument=_instrument(),
                event_time=_utc(1),
                source_sequence=0,
                payload={"close": value},
            )
    with pytest.raises(ValidationError, match="finite"):
        ReplayInputRecord(
            record_id="record-negative-infinity",
            kind=ReplayInputKind.OHLCV_BAR,
            instrument=_instrument(),
            event_time=_utc(1),
            source_sequence=0,
            payload={"nested": {"close": Decimal("-Infinity")}},
        )


def test_replay_input_record_rejects_negative_sequence() -> None:
    with pytest.raises(ValidationError, match="source_sequence"):
        _record(source_sequence=-1)


def test_replay_input_record_rejects_bool_and_string_sequence() -> None:
    with pytest.raises(ValidationError, match="source_sequence"):
        ReplayInputRecord(
            record_id="record-bool-sequence",
            kind=ReplayInputKind.OHLCV_BAR,
            instrument=_instrument(),
            event_time=_utc(1),
            source_sequence=True,
            payload={"close": Decimal("100")},
        )
    with pytest.raises(ValidationError, match="source_sequence"):
        ReplayInputRecord(
            record_id="record-string-sequence",
            kind=ReplayInputKind.OHLCV_BAR,
            instrument=_instrument(),
            event_time=_utc(1),
            source_sequence="1",  # type: ignore[arg-type]
            payload={"close": Decimal("100")},
        )


def test_replay_input_dataset_validates_instruments_and_time_range() -> None:
    assert _dataset().dataset_id == "ds-1"
    with pytest.raises(ValidationError, match="duplicate instruments"):
        _dataset(instruments=(_instrument(), _instrument()))
    with pytest.raises(ValidationError, match="start_at"):
        ReplayInputDataset(
            input_dataset_id="input-ds-1",
            dataset_id="ds-1",
            source_kind=ReplayInputSourceKind.DATASET_SNAPSHOT,
            quality=ReplayInputQuality.CLEANED,
            instruments=(_instrument(),),
            start_at=_utc(3),
            end_at=_utc(0),
            created_at=_utc(4),
        )


def test_replay_input_dataset_rejects_bool_and_string_record_count() -> None:
    with pytest.raises(ValidationError, match="record_count"):
        ReplayInputDataset(
            input_dataset_id="input-ds-1",
            dataset_id="ds-1",
            source_kind=ReplayInputSourceKind.DATASET_SNAPSHOT,
            quality=ReplayInputQuality.CLEANED,
            instruments=(_instrument(),),
            start_at=_utc(0),
            end_at=_utc(3),
            created_at=_utc(4),
            record_count=True,
        )
    with pytest.raises(ValidationError, match="record_count"):
        ReplayInputDataset(
            input_dataset_id="input-ds-1",
            dataset_id="ds-1",
            source_kind=ReplayInputSourceKind.DATASET_SNAPSHOT,
            quality=ReplayInputQuality.CLEANED,
            instruments=(_instrument(),),
            start_at=_utc(0),
            end_at=_utc(3),
            created_at=_utc(4),
            record_count="1",  # type: ignore[arg-type]
        )


def test_replay_input_batch_validates_records_and_ordering() -> None:
    assert _batch().batch_id == "batch-1"
    with pytest.raises(ValidationError, match="duplicate record_id"):
        _batch(records=(_record("same"), _record("same", source_sequence=1)))
    with pytest.raises(ValidationError, match="inside temporal_window"):
        _batch(records=(_record(event_time=_utc(3)),))
    with pytest.raises(ValidationError, match="sorted"):
        _batch(records=(_record("later", source_sequence=1), _record("earlier", source_sequence=0)))
    planned = _batch(records=(), validation_status=ReplayInputValidationStatus.PLANNED)
    assert planned.records == ()
    with pytest.raises(ValidationError, match="PLANNED"):
        _batch(records=(), validation_status=ReplayInputValidationStatus.VALIDATED)


def test_event_time_kind_sequence_ordering() -> None:
    records = (
        _record("a", kind=ReplayInputKind.OHLCV_BAR, source_sequence=0),
        _record("b", kind=ReplayInputKind.MARK_PRICE, source_sequence=1),
    )
    with pytest.raises(ValidationError, match="sorted"):
        _batch(
            records=records,
            ordering_policy=ReplayOrderingPolicy.EVENT_TIME_THEN_KIND_THEN_SEQUENCE,
        )


def test_replay_domain_has_no_forbidden_imports() -> None:
    source_path = inspect.getsourcefile(ReplayInputBatch)
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
        "open(",
        "write_text",
        "LocalJsonlWal",
        "decide_wal_gc",
    )
    for name in forbidden:
        assert name not in source
