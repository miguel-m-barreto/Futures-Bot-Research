from __future__ import annotations

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
