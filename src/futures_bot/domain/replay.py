from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.assets import AssetSymbol, StableCollateralAsset
from futures_bot.domain.research import TemporalWindow
from futures_bot.domain.time import ensure_aware_utc


class ReplayInputKind(StrEnum):
    OHLCV_BAR = "OHLCV_BAR"
    MARK_PRICE = "MARK_PRICE"
    INDEX_PRICE = "INDEX_PRICE"
    FUNDING_RATE = "FUNDING_RATE"
    OPEN_INTEREST = "OPEN_INTEREST"
    LIQUIDATION = "LIQUIDATION"
    ORDER_BOOK_TOP = "ORDER_BOOK_TOP"
    TRADE = "TRADE"
    SYNTHETIC_EVENT = "SYNTHETIC_EVENT"
    OTHER = "OTHER"


class ReplayInputSourceKind(StrEnum):
    DATASET_SNAPSHOT = "DATASET_SNAPSHOT"
    EVENT_JOURNAL = "EVENT_JOURNAL"
    WAL_SEGMENT = "WAL_SEGMENT"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"
    OTHER = "OTHER"


class ReplayInputQuality(StrEnum):
    RAW = "RAW"
    NORMALIZED = "NORMALIZED"
    CLEANED = "CLEANED"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    UNKNOWN = "UNKNOWN"


class ReplayOrderingPolicy(StrEnum):
    EVENT_TIME_THEN_SEQUENCE = "EVENT_TIME_THEN_SEQUENCE"
    EVENT_TIME_THEN_KIND_THEN_SEQUENCE = "EVENT_TIME_THEN_KIND_THEN_SEQUENCE"
    SOURCE_ORDER = "SOURCE_ORDER"
    OTHER = "OTHER"


class ReplayInputValidationStatus(StrEnum):
    PLANNED = "PLANNED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"


class ReplayInstrumentRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    venue: str
    symbol: str
    market_type: str
    settlement_asset: StableCollateralAsset
    quote_asset: StableCollateralAsset | None = None
    base_asset: str | None = None

    @field_validator("venue", "symbol", "market_type")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("settlement_asset", "quote_asset", mode="before")
    @classmethod
    def _coerce_stable_asset(cls, value: object) -> object:
        if value is None:
            return None
        if (
            isinstance(value, dict)
            and isinstance(value.get("symbol"), dict)
            and isinstance(value["symbol"].get("value"), str)
        ):
            return StableCollateralAsset(value["symbol"]["value"])
        if isinstance(value, StableCollateralAsset):
            return value
        if isinstance(value, AssetSymbol | str):
            return StableCollateralAsset(value)
        raise ValueError("stable collateral asset must be USDT or USDC")

    @field_validator("base_asset")
    @classmethod
    def _validate_base_asset(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "base_asset")


class ReplayInputRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: str
    kind: ReplayInputKind
    instrument: ReplayInstrumentRef
    event_time: datetime
    source_sequence: int
    payload: Mapping[str, object]
    content_hash: str | None = None

    @field_validator("record_id")
    @classmethod
    def _validate_record_id(cls, value: str) -> str:
        return _validate_required_text(value, "record_id")

    @field_validator("event_time")
    @classmethod
    def _validate_event_time(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("source_sequence", mode="before")
    @classmethod
    def _validate_source_sequence(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("source_sequence must be an integer")
        if value < 0:
            raise ValueError("source_sequence must be >= 0")
        return value

    @field_validator("payload", mode="before")
    @classmethod
    def _validate_payload_before(cls, value: object) -> object:
        _validate_payload_mapping(value)
        return value

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: Mapping[str, object]) -> Mapping[str, object]:
        _validate_payload_mapping(value)
        return value

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "content_hash")

    @model_validator(mode="after")
    def _validate_payload_for_kind(self) -> Self:
        _validate_kind_specific_payload(self.kind, self.payload)
        return self


class ReplayInputDataset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    input_dataset_id: str
    dataset_id: str
    source_kind: ReplayInputSourceKind
    quality: ReplayInputQuality
    instruments: tuple[ReplayInstrumentRef, ...]
    start_at: datetime
    end_at: datetime
    created_at: datetime
    content_hash: str | None = None
    record_count: int | None = None
    notes: str | None = None

    @field_validator("input_dataset_id", "dataset_id")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("start_at", "end_at", "created_at")
    @classmethod
    def _validate_datetime(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("instruments")
    @classmethod
    def _validate_instruments(
        cls, value: tuple[ReplayInstrumentRef, ...]
    ) -> tuple[ReplayInstrumentRef, ...]:
        if not value:
            raise ValueError("instruments must be non-empty")
        keys = [
            (instrument.venue, instrument.symbol, str(instrument.settlement_asset))
            for instrument in value
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate instruments are not allowed")
        return value

    @field_validator("record_count", mode="before")
    @classmethod
    def _validate_record_count(cls, value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("record_count must be an integer")
        if value is not None and value < 0:
            raise ValueError("record_count must be >= 0")
        return value

    @field_validator("content_hash", "notes")
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "text")

    @model_validator(mode="after")
    def _validate_range(self) -> Self:
        if self.start_at >= self.end_at:
            raise ValueError("start_at must be before end_at")
        return self


class ReplayInputBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: str
    replay_plan_id: str
    input_dataset_id: str
    temporal_window: TemporalWindow
    ordering_policy: ReplayOrderingPolicy
    records: tuple[ReplayInputRecord, ...]
    created_at: datetime
    validation_status: ReplayInputValidationStatus
    notes: str | None = None

    @field_validator("batch_id", "replay_plan_id", "input_dataset_id")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "notes")

    @model_validator(mode="after")
    def _validate_batch(self) -> Self:
        if not self.records and self.validation_status is not ReplayInputValidationStatus.PLANNED:
            raise ValueError("records can be empty only for PLANNED batches")
        record_ids = [record.record_id for record in self.records]
        if len(set(record_ids)) != len(record_ids):
            raise ValueError("duplicate record_id values are not allowed")
        for record in self.records:
            if (
                record.event_time < self.temporal_window.start_at
                or record.event_time >= self.temporal_window.end_at
            ):
                raise ValueError("records must be inside temporal_window [start_at, end_at)")
        _validate_record_ordering(self.records, self.ordering_policy)
        return self


def _validate_record_ordering(
    records: tuple[ReplayInputRecord, ...],
    ordering_policy: ReplayOrderingPolicy,
) -> None:
    if ordering_policy is ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE:
        ordered = tuple(sorted(records, key=_event_time_sequence_key))
    elif ordering_policy is ReplayOrderingPolicy.EVENT_TIME_THEN_KIND_THEN_SEQUENCE:
        ordered = tuple(sorted(records, key=_event_time_kind_sequence_key))
    else:
        return
    if ordered != records:
        raise ValueError("records must be sorted according to ordering_policy")


def _event_time_sequence_key(record: ReplayInputRecord) -> tuple[datetime, int]:
    return (record.event_time, record.source_sequence)


def _event_time_kind_sequence_key(
    record: ReplayInputRecord,
) -> tuple[datetime, str, int]:
    return (record.event_time, record.kind.value, record.source_sequence)


def _validate_payload_mapping(value: object) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("payload must be a mapping")
    if not value:
        raise ValueError("payload must be non-empty")
    for key, item in value.items():
        if not isinstance(key, str) or not key or key != key.strip():
            raise ValueError("payload keys must be non-empty trimmed strings")
        _validate_payload_value(item)


def _validate_payload_value(value: object) -> None:
    if isinstance(value, float):
        raise ValueError("payload values must not contain floats")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("payload Decimal values must be finite")
        return
    if value is None or isinstance(value, str | int | bool):
        return
    if isinstance(value, Mapping):
        _validate_payload_mapping(value)
        return
    if isinstance(value, tuple | list):
        for item in value:
            _validate_payload_value(item)
        return
    raise TypeError(f"unsupported payload value type: {type(value).__name__}")


def _validate_kind_specific_payload(
    kind: ReplayInputKind,
    payload: Mapping[str, object],
) -> None:
    if kind is ReplayInputKind.OHLCV_BAR:
        _validate_ohlcv_payload(payload)
    elif kind is ReplayInputKind.MARK_PRICE:
        _require_positive_decimal(payload, "price")
        _optional_decimal(payload, "funding_rate")
        _optional_positive_decimal(payload, "index_price")
    elif kind is ReplayInputKind.INDEX_PRICE:
        _require_positive_decimal(payload, "price")
    elif kind is ReplayInputKind.FUNDING_RATE:
        _require_decimal(payload, "funding_rate")
        _optional_positive_decimal(payload, "mark_price")
        _optional_positive_decimal(payload, "index_price")
    elif kind is ReplayInputKind.OPEN_INTEREST:
        _require_non_negative_decimal(payload, "open_interest")
        _optional_non_negative_decimal(payload, "open_interest_value")
    elif kind is ReplayInputKind.ORDER_BOOK_TOP:
        _validate_order_book_top_payload(payload)
    elif kind is ReplayInputKind.TRADE:
        _validate_trade_payload(payload)
    elif kind is ReplayInputKind.LIQUIDATION:
        _validate_liquidation_payload(payload)
    elif kind is ReplayInputKind.SYNTHETIC_EVENT:
        _require_non_empty_string(payload, "event_type")


def _validate_ohlcv_payload(payload: Mapping[str, object]) -> None:
    open_price = _require_positive_decimal(payload, "open")
    high = _require_positive_decimal(payload, "high")
    low = _require_positive_decimal(payload, "low")
    close = _require_positive_decimal(payload, "close")
    _require_non_negative_decimal(payload, "volume")
    if high < low:
        raise ValueError("OHLCV_BAR high must be >= low")
    if high < open_price:
        raise ValueError("OHLCV_BAR high must be >= open")
    if high < close:
        raise ValueError("OHLCV_BAR high must be >= close")
    if low > open_price:
        raise ValueError("OHLCV_BAR low must be <= open")
    if low > close:
        raise ValueError("OHLCV_BAR low must be <= close")
    _optional_non_negative_decimal(payload, "quote_volume")
    _optional_non_negative_decimal(payload, "taker_buy_base_volume")
    _optional_non_negative_decimal(payload, "taker_buy_quote_volume")
    _optional_non_negative_int(payload, "trade_count")


def _validate_order_book_top_payload(payload: Mapping[str, object]) -> None:
    bid_price = _require_positive_decimal(payload, "bid_price")
    ask_price = _require_positive_decimal(payload, "ask_price")
    _require_non_negative_decimal(payload, "bid_size")
    _require_non_negative_decimal(payload, "ask_size")
    if ask_price < bid_price:
        raise ValueError("ORDER_BOOK_TOP ask_price must be >= bid_price")
    _optional_non_negative_int(payload, "bid_count")
    _optional_non_negative_int(payload, "ask_count")


def _validate_trade_payload(payload: Mapping[str, object]) -> None:
    _require_positive_decimal(payload, "price")
    _require_positive_decimal(payload, "quantity")
    _optional_side(payload, "side")
    _optional_non_empty_string(payload, "trade_id")


def _validate_liquidation_payload(payload: Mapping[str, object]) -> None:
    _require_positive_decimal(payload, "price")
    _require_positive_decimal(payload, "quantity")
    _require_side(payload, "side")
    _optional_non_empty_string(payload, "liquidation_id")


def _require_field(payload: Mapping[str, object], key: str) -> object:
    if key not in payload:
        raise ValueError(f"payload field {key!r} is required")
    return payload[key]


def _require_decimal(payload: Mapping[str, object], key: str) -> Decimal:
    value = _require_field(payload, key)
    if not isinstance(value, Decimal):
        raise ValueError(f"payload field {key!r} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"payload field {key!r} must be finite")
    return value


def _require_positive_decimal(payload: Mapping[str, object], key: str) -> Decimal:
    value = _require_decimal(payload, key)
    if value <= 0:
        raise ValueError(f"payload field {key!r} must be > 0")
    return value


def _require_non_negative_decimal(payload: Mapping[str, object], key: str) -> Decimal:
    value = _require_decimal(payload, key)
    if value < 0:
        raise ValueError(f"payload field {key!r} must be >= 0")
    return value


def _require_non_negative_int(payload: Mapping[str, object], key: str) -> int:
    value = _require_field(payload, key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"payload field {key!r} must be an integer")
    if value < 0:
        raise ValueError(f"payload field {key!r} must be >= 0")
    return value


def _require_non_empty_string(payload: Mapping[str, object], key: str) -> str:
    value = _require_field(payload, key)
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"payload field {key!r} must be a non-empty string")
    return value


def _require_side(payload: Mapping[str, object], key: str) -> str:
    value = _require_non_empty_string(payload, key)
    if value not in {"buy", "sell"}:
        raise ValueError(f"payload field {key!r} must be 'buy' or 'sell'")
    return value


def _optional_decimal(payload: Mapping[str, object], key: str) -> Decimal | None:
    if key not in payload:
        return None
    return _require_decimal(payload, key)


def _optional_positive_decimal(
    payload: Mapping[str, object], key: str
) -> Decimal | None:
    if key not in payload:
        return None
    return _require_positive_decimal(payload, key)


def _optional_non_negative_decimal(
    payload: Mapping[str, object], key: str
) -> Decimal | None:
    if key not in payload:
        return None
    return _require_non_negative_decimal(payload, key)


def _optional_non_negative_int(
    payload: Mapping[str, object], key: str
) -> int | None:
    if key not in payload:
        return None
    return _require_non_negative_int(payload, key)


def _optional_non_empty_string(
    payload: Mapping[str, object], key: str
) -> str | None:
    if key not in payload:
        return None
    return _require_non_empty_string(payload, key)


def _optional_side(payload: Mapping[str, object], key: str) -> str | None:
    if key not in payload:
        return None
    return _require_side(payload, key)


def _validate_required_text(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value


def _validate_optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value


class ReplayTimelineStatus(StrEnum):
    PLANNED = "PLANNED"
    BUILT = "BUILT"
    VALIDATED = "VALIDATED"
    INVALIDATED = "INVALIDATED"


class ReplayTimelineCursorStatus(StrEnum):
    CREATED = "CREATED"
    ADVANCED = "ADVANCED"
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"


class ReplayTimelineEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    batch_id: str
    input_dataset_id: str
    record_id: str
    kind: ReplayInputKind
    instrument: ReplayInstrumentRef
    event_time: datetime
    source_sequence: int
    order_index: int
    content_hash: str | None = None

    @field_validator("event_id", "batch_id", "input_dataset_id", "record_id")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("event_time")
    @classmethod
    def _validate_event_time(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("source_sequence", mode="before")
    @classmethod
    def _validate_source_sequence(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("source_sequence must be an integer")
        if value < 0:
            raise ValueError("source_sequence must be >= 0")
        return value

    @field_validator("order_index", mode="before")
    @classmethod
    def _validate_order_index(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("order_index must be an integer")
        if value < 0:
            raise ValueError("order_index must be >= 0")
        return value

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "content_hash")


def _validate_timeline_non_empty_requirements(
    status: ReplayTimelineStatus,
    input_batch_ids: tuple[str, ...],
    input_dataset_ids: tuple[str, ...],
    events: tuple[ReplayTimelineEvent, ...],
) -> None:
    if status is not ReplayTimelineStatus.PLANNED:
        if not input_batch_ids:
            raise ValueError("input_batch_ids can be empty only for PLANNED timelines")
        if not input_dataset_ids:
            raise ValueError("input_dataset_ids can be empty only for PLANNED timelines")
        if not events:
            raise ValueError("events can be empty only for PLANNED timelines")


def _validate_timeline_unique_ids(
    input_batch_ids: tuple[str, ...],
    input_dataset_ids: tuple[str, ...],
    events: tuple[ReplayTimelineEvent, ...],
) -> None:
    if len(set(input_batch_ids)) != len(input_batch_ids):
        raise ValueError("duplicate input_batch_ids are not allowed")
    if len(set(input_dataset_ids)) != len(input_dataset_ids):
        raise ValueError("duplicate input_dataset_ids are not allowed")
    event_ids = [e.event_id for e in events]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("duplicate event_id values are not allowed")
    batch_record_pairs = [(e.batch_id, e.record_id) for e in events]
    if len(set(batch_record_pairs)) != len(batch_record_pairs):
        raise ValueError("duplicate (batch_id, record_id) pairs are not allowed")


def _validate_timeline_event_window(
    events: tuple[ReplayTimelineEvent, ...],
    temporal_window: TemporalWindow,
) -> None:
    for event in events:
        if (
            event.event_time < temporal_window.start_at
            or event.event_time >= temporal_window.end_at
        ):
            raise ValueError("events must be inside temporal_window [start_at, end_at)")


def _validate_timeline_event_sets(
    events: tuple[ReplayTimelineEvent, ...],
    input_batch_ids: tuple[str, ...],
    input_dataset_ids: tuple[str, ...],
) -> None:
    if {e.batch_id for e in events} != set(input_batch_ids):
        raise ValueError("input_batch_ids must match event batch_id set")
    if {e.input_dataset_id for e in events} != set(input_dataset_ids):
        raise ValueError("input_dataset_ids must match event input_dataset_id set")


def _validate_timeline_order_indexes(events: tuple[ReplayTimelineEvent, ...]) -> None:
    for i, event in enumerate(events):
        if event.order_index != i:
            raise ValueError(
                "order_index must be contiguous 0..len(events)-1 "
                "and events must be sorted by order_index"
            )


class ReplayTimeline(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timeline_id: str
    replay_plan_id: str
    temporal_window: TemporalWindow
    ordering_policy: ReplayOrderingPolicy
    input_batch_ids: tuple[str, ...]
    input_dataset_ids: tuple[str, ...]
    events: tuple[ReplayTimelineEvent, ...]
    created_at: datetime
    status: ReplayTimelineStatus
    notes: str | None = None

    @field_validator("timeline_id", "replay_plan_id")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "notes")

    @model_validator(mode="after")
    def _validate_timeline(self) -> Self:
        _validate_timeline_non_empty_requirements(
            self.status, self.input_batch_ids, self.input_dataset_ids, self.events
        )
        _validate_timeline_unique_ids(
            self.input_batch_ids, self.input_dataset_ids, self.events
        )
        _validate_timeline_event_window(self.events, self.temporal_window)
        if self.events:
            _validate_timeline_event_sets(
                self.events, self.input_batch_ids, self.input_dataset_ids
            )
            _validate_timeline_order_indexes(self.events)
            _validate_event_ordering(self.events, self.ordering_policy)
        return self


class ReplayTimelineCursor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cursor_id: str
    timeline_id: str
    replay_plan_id: str
    status: ReplayTimelineCursorStatus
    next_order_index: int
    updated_at: datetime
    completed_at: datetime | None = None
    notes: str | None = None

    @field_validator("cursor_id", "timeline_id", "replay_plan_id")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("next_order_index", mode="before")
    @classmethod
    def _validate_next_order_index(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("next_order_index must be an integer")
        if value < 0:
            raise ValueError("next_order_index must be >= 0")
        return value

    @field_validator("updated_at")
    @classmethod
    def _validate_updated_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("completed_at")
    @classmethod
    def _validate_completed_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_aware_utc(value)

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "notes")

    @model_validator(mode="after")
    def _validate_cursor(self) -> Self:
        if self.status is ReplayTimelineCursorStatus.COMPLETED:
            if self.completed_at is None:
                raise ValueError("completed_at is required when status is COMPLETED")
        elif self.completed_at is not None:
            raise ValueError("completed_at must be None for non-COMPLETED status")
        if self.completed_at is not None and self.completed_at < self.updated_at:
            raise ValueError("completed_at must be >= updated_at")
        return self


class ReplayTimelineCoverageStatus(StrEnum):
    PLANNED = "PLANNED"
    GENERATED = "GENERATED"
    INVALIDATED = "INVALIDATED"


class ReplayTimelineCoverageIssueSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ReplayTimelineCoverageIssueKind(StrEnum):
    EMPTY_TIMELINE = "EMPTY_TIMELINE"
    MISSING_EXPECTED_KIND = "MISSING_EXPECTED_KIND"
    MISSING_EXPECTED_INSTRUMENT = "MISSING_EXPECTED_INSTRUMENT"
    EVENT_TIME_GAP = "EVENT_TIME_GAP"
    START_COVERAGE_GAP = "START_COVERAGE_GAP"
    END_COVERAGE_GAP = "END_COVERAGE_GAP"
    DUPLICATE_EVENT_REF = "DUPLICATE_EVENT_REF"
    ORDERING_ANOMALY = "ORDERING_ANOMALY"
    OTHER = "OTHER"


class ReplayTimelineCoverageIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    issue_id: str
    kind: ReplayTimelineCoverageIssueKind
    severity: ReplayTimelineCoverageIssueSeverity
    message: str
    event_id: str | None = None
    instrument_key: str | None = None
    input_kind: ReplayInputKind | None = None
    observed_count: int | None = None
    expected_count: int | None = None

    @field_validator("issue_id", "message")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("event_id", "instrument_key")
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "field")

    @field_validator("observed_count", "expected_count", mode="before")
    @classmethod
    def _validate_count_fields(cls, value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("count must be a strict integer")
        if value < 0:
            raise ValueError("count must be >= 0")
        return value


class ReplayTimelineCoverageSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_events: int
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    event_count_by_kind: Mapping[ReplayInputKind, int]
    event_count_by_instrument: Mapping[str, int]
    event_count_by_dataset: Mapping[str, int]
    issue_count_by_severity: Mapping[ReplayTimelineCoverageIssueSeverity, int]

    @field_validator("total_events", mode="before")
    @classmethod
    def _validate_total_events(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("total_events must be a strict integer")
        if value < 0:
            raise ValueError("total_events must be >= 0")
        return value

    @field_validator("first_event_at", "last_event_at")
    @classmethod
    def _validate_event_times(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_aware_utc(value)

    @field_validator("event_count_by_kind", "issue_count_by_severity", mode="before")
    @classmethod
    def _validate_enum_count_mapping(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            raise ValueError("must be a mapping")
        for v in value.values():
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError("count values must be strict integers")
            if v < 0:
                raise ValueError("count values must be >= 0")
        return value

    @field_validator("event_count_by_instrument", "event_count_by_dataset", mode="before")
    @classmethod
    def _validate_str_count_mapping(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            raise ValueError("must be a mapping")
        for k, v in value.items():
            if not isinstance(k, str) or not k:
                raise ValueError("mapping keys must be non-empty strings")
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError("count values must be strict integers")
            if v < 0:
                raise ValueError("count values must be >= 0")
        return value

    @model_validator(mode="after")
    def _validate_summary(self) -> Self:
        if self.total_events == 0:
            if self.first_event_at is not None or self.last_event_at is not None:
                raise ValueError(
                    "first_event_at and last_event_at must be None when total_events is 0"
                )
            if (
                self.event_count_by_kind
                or self.event_count_by_instrument
                or self.event_count_by_dataset
            ):
                raise ValueError(
                    "event count mappings must be empty when total_events is 0"
                )
        elif self.first_event_at is None or self.last_event_at is None:
            raise ValueError(
                "first_event_at and last_event_at are required when total_events > 0"
            )
        elif self.first_event_at > self.last_event_at:
            raise ValueError("first_event_at must be <= last_event_at")
        if self.total_events > 0:
            n = self.total_events
            if sum(self.event_count_by_kind.values()) != n:
                raise ValueError("sum of event_count_by_kind must equal total_events")
            if sum(self.event_count_by_instrument.values()) != n:
                raise ValueError("sum of event_count_by_instrument must equal total_events")
            if sum(self.event_count_by_dataset.values()) != n:
                raise ValueError("sum of event_count_by_dataset must equal total_events")
        return self


class ReplayTimelineCoverageReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str
    timeline_id: str
    replay_plan_id: str
    temporal_window: TemporalWindow
    generated_at: datetime
    status: ReplayTimelineCoverageStatus
    summary: ReplayTimelineCoverageSummary
    issues: tuple[ReplayTimelineCoverageIssue, ...] = ()
    expected_input_kinds: tuple[ReplayInputKind, ...] = ()
    expected_instrument_keys: tuple[str, ...] = ()
    notes: str | None = None

    @field_validator("report_id", "timeline_id", "replay_plan_id")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "notes")

    @model_validator(mode="after")
    def _validate_report(self) -> Self:
        issue_ids = [i.issue_id for i in self.issues]
        if len(set(issue_ids)) != len(issue_ids):
            raise ValueError("duplicate issue_id values are not allowed")
        if len(set(self.expected_input_kinds)) != len(self.expected_input_kinds):
            raise ValueError("duplicate expected_input_kinds are not allowed")
        if len(set(self.expected_instrument_keys)) != len(self.expected_instrument_keys):
            raise ValueError("duplicate expected_instrument_keys are not allowed")
        for key in self.expected_instrument_keys:
            _validate_required_text(key, "expected_instrument_keys element")
        expected_counts: dict[ReplayTimelineCoverageIssueSeverity, int] = {}
        for issue in self.issues:
            expected_counts[issue.severity] = expected_counts.get(issue.severity, 0) + 1
        if dict(self.summary.issue_count_by_severity) != expected_counts:
            raise ValueError(
                "summary.issue_count_by_severity must match the actual issue severity counts"
            )
        return self


class ReplayTimelineCoverageDiffStatus(StrEnum):
    PLANNED = "PLANNED"
    GENERATED = "GENERATED"
    INVALIDATED = "INVALIDATED"


class ReplayTimelineCoverageDiffDirection(StrEnum):
    BASELINE_TO_CANDIDATE = "BASELINE_TO_CANDIDATE"


class ReplayTimelineCoverageDiffSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ReplayTimelineCoverageDiffKind(StrEnum):
    TOTAL_EVENT_COUNT_CHANGED = "TOTAL_EVENT_COUNT_CHANGED"
    KIND_COUNT_CHANGED = "KIND_COUNT_CHANGED"
    INSTRUMENT_COUNT_CHANGED = "INSTRUMENT_COUNT_CHANGED"
    DATASET_COUNT_CHANGED = "DATASET_COUNT_CHANGED"
    ISSUE_SEVERITY_COUNT_CHANGED = "ISSUE_SEVERITY_COUNT_CHANGED"
    EXPECTED_KIND_SET_CHANGED = "EXPECTED_KIND_SET_CHANGED"
    EXPECTED_INSTRUMENT_SET_CHANGED = "EXPECTED_INSTRUMENT_SET_CHANGED"
    FIRST_EVENT_TIME_CHANGED = "FIRST_EVENT_TIME_CHANGED"
    LAST_EVENT_TIME_CHANGED = "LAST_EVENT_TIME_CHANGED"
    REPORT_STATUS_CHANGED = "REPORT_STATUS_CHANGED"
    OTHER = "OTHER"


class ReplayTimelineCoverageDiffItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str
    kind: ReplayTimelineCoverageDiffKind
    severity: ReplayTimelineCoverageDiffSeverity
    message: str
    key: str | None = None
    baseline_value: str | None = None
    candidate_value: str | None = None
    numeric_delta: int | None = None

    @field_validator("item_id", "message")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("key", "baseline_value", "candidate_value")
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "field")

    @field_validator("numeric_delta", mode="before")
    @classmethod
    def _validate_numeric_delta(cls, value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("numeric_delta must be a strict integer")
        return value


class ReplayTimelineCoverageDiffSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_items: int
    item_count_by_kind: Mapping[ReplayTimelineCoverageDiffKind, int]
    item_count_by_severity: Mapping[ReplayTimelineCoverageDiffSeverity, int]
    has_errors: bool
    has_warnings: bool

    @field_validator("total_items", mode="before")
    @classmethod
    def _validate_total_items(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("total_items must be a strict integer")
        if value < 0:
            raise ValueError("total_items must be >= 0")
        return value

    @field_validator("item_count_by_kind", "item_count_by_severity", mode="before")
    @classmethod
    def _validate_count_mapping(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            raise ValueError("must be a mapping")
        for v in value.values():
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError("count values must be strict integers")
            if v < 0:
                raise ValueError("count values must be >= 0")
        return value

    @model_validator(mode="after")
    def _validate_diff_summary(self) -> Self:
        if self.total_items == 0:
            if self.item_count_by_kind or self.item_count_by_severity:
                raise ValueError("count mappings must be empty when total_items is 0")
            if self.has_errors or self.has_warnings:
                raise ValueError(
                    "has_errors and has_warnings must be False when total_items is 0"
                )
        else:
            if sum(self.item_count_by_kind.values()) != self.total_items:
                raise ValueError("sum of item_count_by_kind must equal total_items")
            if sum(self.item_count_by_severity.values()) != self.total_items:
                raise ValueError("sum of item_count_by_severity must equal total_items")
        error_count = dict(self.item_count_by_severity).get(
            ReplayTimelineCoverageDiffSeverity.ERROR, 0
        )
        warning_count = dict(self.item_count_by_severity).get(
            ReplayTimelineCoverageDiffSeverity.WARNING, 0
        )
        if self.has_errors != (error_count > 0):
            raise ValueError("has_errors must match whether ERROR count > 0")
        if self.has_warnings != (warning_count > 0):
            raise ValueError("has_warnings must match whether WARNING count > 0")
        return self


class ReplayTimelineCoverageDiff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    diff_id: str
    baseline_report_id: str
    candidate_report_id: str
    baseline_timeline_id: str
    candidate_timeline_id: str
    baseline_replay_plan_id: str
    candidate_replay_plan_id: str
    generated_at: datetime
    status: ReplayTimelineCoverageDiffStatus
    direction: ReplayTimelineCoverageDiffDirection = (
        ReplayTimelineCoverageDiffDirection.BASELINE_TO_CANDIDATE
    )
    summary: ReplayTimelineCoverageDiffSummary
    items: tuple[ReplayTimelineCoverageDiffItem, ...] = ()
    notes: str | None = None

    @field_validator(
        "diff_id",
        "baseline_report_id",
        "candidate_report_id",
        "baseline_timeline_id",
        "candidate_timeline_id",
        "baseline_replay_plan_id",
        "candidate_replay_plan_id",
    )
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "notes")

    @model_validator(mode="after")
    def _validate_diff(self) -> Self:
        if self.baseline_report_id == self.candidate_report_id:
            raise ValueError(
                "baseline_report_id and candidate_report_id must differ"
            )
        item_ids = [item.item_id for item in self.items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("duplicate item_id values are not allowed")
        if self.summary.total_items != len(self.items):
            raise ValueError("summary.total_items must equal len(items)")
        by_kind: dict[ReplayTimelineCoverageDiffKind, int] = {}
        by_severity: dict[ReplayTimelineCoverageDiffSeverity, int] = {}
        for item in self.items:
            by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
            by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
        if dict(self.summary.item_count_by_kind) != by_kind:
            raise ValueError(
                "summary.item_count_by_kind must match actual item kind counts"
            )
        if dict(self.summary.item_count_by_severity) != by_severity:
            raise ValueError(
                "summary.item_count_by_severity must match actual item severity counts"
            )
        return self


def _validate_event_ordering(
    events: tuple[ReplayTimelineEvent, ...],
    ordering_policy: ReplayOrderingPolicy,
) -> None:
    if not events:
        return
    if ordering_policy is ReplayOrderingPolicy.EVENT_TIME_THEN_SEQUENCE:
        ordered = tuple(
            sorted(events, key=lambda e: (e.event_time, e.source_sequence, e.event_id))
        )
        if ordered != events:
            raise ValueError(
                "events must be sorted according to EVENT_TIME_THEN_SEQUENCE policy"
            )
    elif ordering_policy is ReplayOrderingPolicy.EVENT_TIME_THEN_KIND_THEN_SEQUENCE:
        ordered = tuple(
            sorted(
                events,
                key=lambda e: (e.event_time, e.kind.value, e.source_sequence, e.event_id),
            )
        )
        if ordered != events:
            raise ValueError(
                "events must be sorted according to EVENT_TIME_THEN_KIND_THEN_SEQUENCE policy"
            )


def _check_no_floats_in_json(value: object, path: str = "root") -> None:
    if isinstance(value, float):
        raise ValueError(f"float value at {path!r} not allowed in canonical payload")
    if isinstance(value, dict):
        for k, v in value.items():
            _check_no_floats_in_json(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _check_no_floats_in_json(v, f"{path}[{i}]")


class ReplayArtifactKind(StrEnum):
    TIMELINE = "TIMELINE"
    COVERAGE_REPORT = "COVERAGE_REPORT"
    COVERAGE_DIFF = "COVERAGE_DIFF"


class ReplayArtifactFingerprintStatus(StrEnum):
    GENERATED = "GENERATED"
    INVALIDATED = "INVALIDATED"


class ReplayArtifactHashAlgorithm(StrEnum):
    SHA256 = "SHA256"


_ARTIFACT_ID_FIELD: dict[ReplayArtifactKind, str] = {
    ReplayArtifactKind.TIMELINE: "timeline_id",
    ReplayArtifactKind.COVERAGE_REPORT: "report_id",
    ReplayArtifactKind.COVERAGE_DIFF: "diff_id",
}


def _validate_plan_id_in_payload(
    artifact_kind: ReplayArtifactKind,
    artifact: dict[str, object],
    replay_plan_id: str,
) -> None:
    if artifact_kind is ReplayArtifactKind.COVERAGE_DIFF:
        if artifact.get("baseline_replay_plan_id") != replay_plan_id:
            raise ValueError(
                "canonical_payload baseline_replay_plan_id does not match replay_plan_id"
            )
        if artifact.get("candidate_replay_plan_id") != replay_plan_id:
            raise ValueError(
                "canonical_payload candidate_replay_plan_id does not match replay_plan_id"
            )
    elif artifact.get("replay_plan_id") != replay_plan_id:
        raise ValueError("canonical_payload replay_plan_id does not match self.replay_plan_id")


class ReplayArtifactFingerprint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fingerprint_id: str
    artifact_kind: ReplayArtifactKind
    artifact_id: str
    replay_plan_id: str | None = None
    generated_at: datetime
    status: ReplayArtifactFingerprintStatus
    hash_algorithm: ReplayArtifactHashAlgorithm = ReplayArtifactHashAlgorithm.SHA256
    canonical_payload: str
    sha256: str
    notes: str | None = None

    @field_validator("fingerprint_id", "artifact_id")
    @classmethod
    def _validate_required_ids(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("replay_plan_id")
    @classmethod
    def _validate_replay_plan_id(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "replay_plan_id")

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("canonical_payload")
    @classmethod
    def _validate_canonical_payload_format(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("canonical_payload must not be empty or blank")
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"canonical_payload is not valid JSON: {e}") from e
        canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if canonical != value:
            raise ValueError("canonical_payload must be compact sorted JSON")
        _check_no_floats_in_json(parsed)
        return value

    @field_validator("sha256")
    @classmethod
    def _validate_sha256_format(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("sha256 must be a 64-character lowercase hex string")
        return value

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "notes")

    @model_validator(mode="after")
    def _validate_sha_and_consistency(self) -> Self:
        expected = hashlib.sha256(self.canonical_payload.encode("utf-8")).hexdigest()
        if self.sha256 != expected:
            raise ValueError("sha256 does not match sha256(canonical_payload)")
        parsed = json.loads(self.canonical_payload)
        if not isinstance(parsed, dict):
            raise ValueError("canonical_payload must be a JSON object")
        if "artifact_kind" not in parsed:
            raise ValueError("canonical_payload must have top-level 'artifact_kind'")
        if "artifact" not in parsed:
            raise ValueError("canonical_payload must have top-level 'artifact'")
        if parsed["artifact_kind"] != self.artifact_kind.value:
            raise ValueError(
                "canonical_payload artifact_kind does not match self.artifact_kind"
            )
        artifact = parsed["artifact"]
        if not isinstance(artifact, dict):
            raise ValueError("canonical_payload 'artifact' must be a JSON object")
        id_field = _ARTIFACT_ID_FIELD[self.artifact_kind]
        if id_field not in artifact:
            raise ValueError(f"canonical_payload artifact must have '{id_field}'")
        if artifact[id_field] != self.artifact_id:
            raise ValueError(
                f"canonical_payload artifact.{id_field} does not match artifact_id"
            )
        if self.replay_plan_id is not None:
            _validate_plan_id_in_payload(self.artifact_kind, artifact, self.replay_plan_id)
        return self


class ReplayArtifactFingerprintVerificationStatus(StrEnum):
    VALID = "VALID"
    MISMATCH = "MISMATCH"
    MISSING_FINGERPRINT = "MISSING_FINGERPRINT"
    MISSING_ARTIFACT = "MISSING_ARTIFACT"
    INVALIDATED = "INVALIDATED"


class ReplayArtifactFingerprintVerificationIssueKind(StrEnum):
    FINGERPRINT_NOT_FOUND = "FINGERPRINT_NOT_FOUND"
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    HASH_MISMATCH = "HASH_MISMATCH"
    CANONICAL_PAYLOAD_MISMATCH = "CANONICAL_PAYLOAD_MISMATCH"
    ARTIFACT_KIND_MISMATCH = "ARTIFACT_KIND_MISMATCH"
    ARTIFACT_ID_MISMATCH = "ARTIFACT_ID_MISMATCH"
    REPLAY_PLAN_ID_MISMATCH = "REPLAY_PLAN_ID_MISMATCH"
    OTHER = "OTHER"


class ReplayArtifactFingerprintVerificationIssueSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ReplayArtifactFingerprintVerificationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    issue_id: str
    kind: ReplayArtifactFingerprintVerificationIssueKind
    severity: ReplayArtifactFingerprintVerificationIssueSeverity
    message: str
    expected_value: str | None = None
    observed_value: str | None = None

    @field_validator("issue_id", "message")
    @classmethod
    def _validate_required_text_fields(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("expected_value", "observed_value")
    @classmethod
    def _validate_optional_value_fields(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "value")


class ReplayArtifactFingerprintVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verification_id: str
    fingerprint_id: str
    artifact_kind: ReplayArtifactKind | None = None
    artifact_id: str | None = None
    replay_plan_id: str | None = None
    verified_at: datetime
    status: ReplayArtifactFingerprintVerificationStatus
    stored_sha256: str | None = None
    recomputed_sha256: str | None = None
    stored_canonical_payload: str | None = None
    recomputed_canonical_payload: str | None = None
    issues: tuple[ReplayArtifactFingerprintVerificationIssue, ...] = ()
    notes: str | None = None

    @field_validator("verification_id", "fingerprint_id")
    @classmethod
    def _validate_required_ids(cls, value: str) -> str:
        return _validate_required_text(value, "field")

    @field_validator("artifact_id", "replay_plan_id")
    @classmethod
    def _validate_optional_id_fields(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "field")

    @field_validator("verified_at")
    @classmethod
    def _validate_verified_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("stored_sha256", "recomputed_sha256")
    @classmethod
    def _validate_optional_sha256_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("sha256 must be a 64-character lowercase hex string")
        return value

    @field_validator("stored_canonical_payload", "recomputed_canonical_payload")
    @classmethod
    def _validate_optional_payload_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("canonical_payload must not be empty or blank")
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"canonical_payload is not valid JSON: {e}") from e
        canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if canonical != value:
            raise ValueError("canonical_payload must be compact sorted JSON")
        _check_no_floats_in_json(parsed)
        return value

    @field_validator("notes")
    @classmethod
    def _validate_notes_field(cls, value: str | None) -> str | None:
        return _validate_optional_text(value, "notes")

    @model_validator(mode="after")
    def _validate_status_rules(self) -> Self:
        if self.status is ReplayArtifactFingerprintVerificationStatus.VALID:
            _validate_verification_valid(self)
        elif self.status is ReplayArtifactFingerprintVerificationStatus.MISMATCH:
            _validate_verification_mismatch(self)
        elif self.status is ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT:
            _validate_verification_missing_fingerprint(self)
        elif self.status is ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT:
            _validate_verification_missing_artifact(self)
        _validate_optional_sha_matches_payload(
            "stored_sha256", self.stored_sha256, self.stored_canonical_payload
        )
        _validate_optional_sha_matches_payload(
            "recomputed_sha256", self.recomputed_sha256, self.recomputed_canonical_payload
        )
        _validate_payloads_identity_for_verification(self)
        issue_ids = [i.issue_id for i in self.issues]
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("duplicate issue_id in issues")
        return self


def _validate_verification_valid(v: ReplayArtifactFingerprintVerification) -> None:
    if v.artifact_kind is None:
        raise ValueError("VALID status requires artifact_kind")
    if v.artifact_id is None:
        raise ValueError("VALID status requires artifact_id")
    if v.stored_sha256 is None:
        raise ValueError("VALID status requires stored_sha256")
    if v.recomputed_sha256 is None:
        raise ValueError("VALID status requires recomputed_sha256")
    if v.stored_sha256 != v.recomputed_sha256:
        raise ValueError("VALID status requires stored_sha256 == recomputed_sha256")
    if v.stored_canonical_payload is None:
        raise ValueError("VALID status requires stored_canonical_payload")
    if v.recomputed_canonical_payload is None:
        raise ValueError("VALID status requires recomputed_canonical_payload")
    if v.stored_canonical_payload != v.recomputed_canonical_payload:
        raise ValueError(
            "VALID status requires stored_canonical_payload == recomputed_canonical_payload"
        )
    if v.issues:
        raise ValueError("VALID status requires no issues")


def _validate_verification_mismatch(v: ReplayArtifactFingerprintVerification) -> None:
    if v.artifact_kind is None:
        raise ValueError("MISMATCH status requires artifact_kind")
    if v.artifact_id is None:
        raise ValueError("MISMATCH status requires artifact_id")
    if v.stored_sha256 is None:
        raise ValueError("MISMATCH status requires stored_sha256")
    if v.recomputed_sha256 is None:
        raise ValueError("MISMATCH status requires recomputed_sha256")
    if not v.issues:
        raise ValueError("MISMATCH status requires at least one issue")


def _validate_verification_missing_fingerprint(
    v: ReplayArtifactFingerprintVerification,
) -> None:
    if v.stored_sha256 is not None:
        raise ValueError("MISSING_FINGERPRINT status requires stored_sha256 to be None")
    if v.recomputed_sha256 is not None:
        raise ValueError("MISSING_FINGERPRINT status requires recomputed_sha256 to be None")
    if not any(
        i.kind is ReplayArtifactFingerprintVerificationIssueKind.FINGERPRINT_NOT_FOUND
        for i in v.issues
    ):
        raise ValueError(
            "MISSING_FINGERPRINT status requires a FINGERPRINT_NOT_FOUND issue"
        )


def _validate_verification_missing_artifact(v: ReplayArtifactFingerprintVerification) -> None:
    if v.stored_sha256 is None:
        raise ValueError("MISSING_ARTIFACT status requires stored_sha256")
    if v.recomputed_sha256 is not None:
        raise ValueError("MISSING_ARTIFACT status requires recomputed_sha256 to be None")
    if not any(
        i.kind is ReplayArtifactFingerprintVerificationIssueKind.ARTIFACT_NOT_FOUND
        for i in v.issues
    ):
        raise ValueError("MISSING_ARTIFACT status requires an ARTIFACT_NOT_FOUND issue")


def _validate_optional_sha_matches_payload(
    field_name: str,
    sha256: str | None,
    payload: str | None,
) -> None:
    if sha256 is not None and payload is not None:
        expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if sha256 != expected:
            raise ValueError(
                f"{field_name} does not match sha256 of its canonical payload"
            )


def _parse_verification_payload(payload: str) -> dict[str, object]:
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError("canonical_payload must be a JSON object")
    return parsed


def _validate_verification_payload_identity(
    artifact_kind: ReplayArtifactKind,
    artifact_id: str,
    replay_plan_id: str | None,
    payload: str,
    field_name: str,
) -> None:
    parsed = _parse_verification_payload(payload)
    if "artifact_kind" not in parsed:
        raise ValueError(f"{field_name} must have top-level 'artifact_kind'")
    if parsed["artifact_kind"] != artifact_kind.value:
        raise ValueError(f"{field_name} artifact_kind does not match self.artifact_kind")
    if "artifact" not in parsed:
        raise ValueError(f"{field_name} must have top-level 'artifact'")
    artifact = parsed["artifact"]
    if not isinstance(artifact, dict):
        raise ValueError(f"{field_name} 'artifact' must be a JSON object")
    id_field = _ARTIFACT_ID_FIELD[artifact_kind]
    if id_field not in artifact:
        raise ValueError(f"{field_name} artifact must have '{id_field}'")
    if artifact[id_field] != artifact_id:
        raise ValueError(f"{field_name} artifact.{id_field} does not match artifact_id")
    if replay_plan_id is not None:
        _validate_plan_id_in_payload(artifact_kind, artifact, replay_plan_id)


def _validate_payloads_identity_for_verification(
    v: ReplayArtifactFingerprintVerification,
) -> None:
    kind = v.artifact_kind
    aid = v.artifact_id
    if kind is None or aid is None:
        return
    plan_id = v.replay_plan_id
    if v.stored_canonical_payload is not None:
        _validate_verification_payload_identity(
            kind, aid, plan_id, v.stored_canonical_payload, "stored_canonical_payload"
        )
    if v.recomputed_canonical_payload is not None:
        _validate_verification_payload_identity(
            kind, aid, plan_id, v.recomputed_canonical_payload, "recomputed_canonical_payload"
        )


class ReplayArtifactFingerprintVerificationBatchReportStatus(StrEnum):
    GENERATED = "GENERATED"
    INVALIDATED = "INVALIDATED"


class ReplayArtifactFingerprintVerificationBatchScopeKind(StrEnum):
    EXPLICIT_FINGERPRINT_SET = "EXPLICIT_FINGERPRINT_SET"
    REPLAY_PLAN = "REPLAY_PLAN"
    ARTIFACT_SET = "ARTIFACT_SET"
    OTHER = "OTHER"


def _validate_strict_int(value: object, field_name: str) -> object:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be a strict int")
    return value


class ReplayArtifactFingerprintVerificationBatchItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    item_id: str
    fingerprint_id: str
    verification_id: str
    verification_status: ReplayArtifactFingerprintVerificationStatus
    artifact_kind: ReplayArtifactKind | None = None
    artifact_id: str | None = None
    replay_plan_id: str | None = None
    issue_count: int = 0

    @field_validator("issue_count", mode="before")
    @classmethod
    def _validate_issue_count_type(cls, v: object) -> object:
        return _validate_strict_int(v, "issue_count")

    @model_validator(mode="after")
    def _validate_ids(self) -> Self:
        if not self.item_id:
            raise ValueError("item_id must be non-empty")
        if not self.fingerprint_id:
            raise ValueError("fingerprint_id must be non-empty")
        if not self.verification_id:
            raise ValueError("verification_id must be non-empty")
        if self.artifact_id is not None and not self.artifact_id:
            raise ValueError("artifact_id must be non-empty if provided")
        if self.replay_plan_id is not None and not self.replay_plan_id:
            raise ValueError("replay_plan_id must be non-empty if provided")
        if self.issue_count < 0:
            raise ValueError("issue_count must be >= 0")
        return self


class ReplayArtifactFingerprintVerificationBatchSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    total_fingerprints: int
    count_by_status: Mapping[ReplayArtifactFingerprintVerificationStatus, int]
    total_issues: int
    all_valid: bool
    has_mismatches: bool
    has_missing: bool

    @field_validator("total_fingerprints", "total_issues", mode="before")
    @classmethod
    def _reject_non_int_counts(cls, v: object) -> object:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("count fields must be a strict int")
        return v

    @field_validator("count_by_status", mode="before")
    @classmethod
    def _validate_count_by_status_values(cls, v: object) -> object:
        if isinstance(v, Mapping):
            for val in v.values():
                if isinstance(val, bool) or not isinstance(val, int):
                    raise ValueError("count_by_status values must be a strict int")
        return v

    @model_validator(mode="after")
    def _validate_counts(self) -> Self:
        if self.total_fingerprints < 0:
            raise ValueError("total_fingerprints must be >= 0")
        if self.total_issues < 0:
            raise ValueError("total_issues must be >= 0")
        for count in self.count_by_status.values():
            if count < 0:
                raise ValueError("count_by_status values must be >= 0")
        if self.total_fingerprints == 0 and self.count_by_status:
            raise ValueError("count_by_status must be empty when total_fingerprints == 0")
        count_sum = sum(self.count_by_status.values())
        if count_sum != self.total_fingerprints:
            raise ValueError("sum of count_by_status values must equal total_fingerprints")
        valid_count = self.count_by_status.get(
            ReplayArtifactFingerprintVerificationStatus.VALID, 0
        )
        expected_all_valid = (
            self.total_fingerprints > 0 and valid_count == self.total_fingerprints
        )
        if self.all_valid != expected_all_valid:
            raise ValueError("all_valid is inconsistent with count_by_status")
        mismatch_count = self.count_by_status.get(
            ReplayArtifactFingerprintVerificationStatus.MISMATCH, 0
        )
        if self.has_mismatches != (mismatch_count > 0):
            raise ValueError("has_mismatches is inconsistent with count_by_status")
        missing_fp = self.count_by_status.get(
            ReplayArtifactFingerprintVerificationStatus.MISSING_FINGERPRINT, 0
        )
        missing_art = self.count_by_status.get(
            ReplayArtifactFingerprintVerificationStatus.MISSING_ARTIFACT, 0
        )
        if self.has_missing != ((missing_fp + missing_art) > 0):
            raise ValueError("has_missing is inconsistent with count_by_status")
        return self


class ReplayArtifactFingerprintVerificationBatchReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    report_id: str
    scope_kind: ReplayArtifactFingerprintVerificationBatchScopeKind
    replay_plan_id: str | None = None
    generated_at: datetime
    status: ReplayArtifactFingerprintVerificationBatchReportStatus
    summary: ReplayArtifactFingerprintVerificationBatchSummary
    items: tuple[ReplayArtifactFingerprintVerificationBatchItem, ...] = ()
    requested_fingerprint_ids: tuple[str, ...] = ()
    notes: str | None = None

    @field_validator("generated_at", mode="after")
    @classmethod
    def _validate_generated_at(cls, v: datetime) -> datetime:
        return ensure_aware_utc(v)

    @model_validator(mode="after")
    def _validate_report(self) -> Self:
        if not self.report_id:
            raise ValueError("report_id must be non-empty")
        if self.replay_plan_id is not None and not self.replay_plan_id:
            raise ValueError("replay_plan_id must be non-empty if provided")
        if self.notes is not None and (not self.notes or self.notes != self.notes.strip()):
            raise ValueError("notes must be non-empty without leading/trailing whitespace")
        if any(not fp_id for fp_id in self.requested_fingerprint_ids):
            raise ValueError("requested_fingerprint_ids must not contain empty strings")
        rfp_ids = list(self.requested_fingerprint_ids)
        if len(rfp_ids) != len(set(rfp_ids)):
            raise ValueError("duplicate fingerprint_id in requested_fingerprint_ids")
        item_ids = [i.item_id for i in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("duplicate item_id in items")
        ver_ids = [i.verification_id for i in self.items]
        if len(ver_ids) != len(set(ver_ids)):
            raise ValueError("duplicate verification_id in items")
        item_fp_ids = [i.fingerprint_id for i in self.items]
        if len(item_fp_ids) != len(set(item_fp_ids)):
            raise ValueError("duplicate fingerprint_id in items")
        if (
            self.scope_kind is ReplayArtifactFingerprintVerificationBatchScopeKind.REPLAY_PLAN
            and self.replay_plan_id is None
        ):
            raise ValueError("REPLAY_PLAN scope requires replay_plan_id")
        if self.requested_fingerprint_ids and tuple(item_fp_ids) != self.requested_fingerprint_ids:
            raise ValueError(
                "items fingerprint_ids must exactly match requested_fingerprint_ids"
            )
        _validate_batch_summary_matches_items(self)
        return self


def _validate_batch_summary_matches_items(
    r: ReplayArtifactFingerprintVerificationBatchReport,
) -> None:
    items = r.items
    s = r.summary
    if len(items) != s.total_fingerprints:
        raise ValueError("summary.total_fingerprints does not match len(items)")
    actual_counts: dict[ReplayArtifactFingerprintVerificationStatus, int] = {}
    for item in items:
        vs = item.verification_status
        actual_counts[vs] = actual_counts.get(vs, 0) + 1
    expected = {k: v for k, v in s.count_by_status.items() if v > 0}
    if expected != actual_counts:
        raise ValueError("summary.count_by_status does not match items")
    actual_total_issues = sum(item.issue_count for item in items)
    if actual_total_issues != s.total_issues:
        raise ValueError("summary.total_issues does not match sum of item.issue_count")
