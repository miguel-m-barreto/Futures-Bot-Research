from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from math import isfinite
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.ids import (
    DbWriterCheckpointId,
    HistoricalStateSliceId,
    InstrumentId,
    LiveStateSnapshotId,
    LiveTailSliceId,
    StitchedStateSliceId,
    StreamEventId,
    StreamId,
    StreamPartitionId,
)
from futures_bot.domain.instruments import VenueId
from futures_bot.domain.time import ensure_aware_utc

_DURABILITY_RANK: dict[DurabilityStatus, int]


class DurabilityStatus(StrEnum):
    LIVE_ACCEPTED = "LIVE_ACCEPTED"
    DURABLE_COMMITTED = "DURABLE_COMMITTED"
    PROJECTED_TO_LIVE_STATE = "PROJECTED_TO_LIVE_STATE"
    PERSISTED_TO_DB = "PERSISTED_TO_DB"
    RECONCILED = "RECONCILED"


class StitchFailureReason(StrEnum):
    LIVE_HISTORY_GAP = "LIVE_HISTORY_GAP"
    INVALID_OVERLAP = "INVALID_OVERLAP"
    STALE_LIVE_STATE = "STALE_LIVE_STATE"
    SPECULATIVE_NOT_ALLOWED = "SPECULATIVE_NOT_ALLOWED"
    INCOMPLETE_HISTORY = "INCOMPLETE_HISTORY"
    STREAM_PARTITION_MISMATCH = "STREAM_PARTITION_MISMATCH"


class StreamPosition(BaseModel):
    """Deterministic location in a canonical durable stream."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stream_id: StreamId
    partition_id: StreamPartitionId
    offset: int
    event_sequence: int
    event_time: datetime

    @field_validator("offset", "event_sequence")
    @classmethod
    def _validate_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("stream position counters must be >= 0")
        return value

    @field_validator("event_time")
    @classmethod
    def _validate_event_time(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    def require_same_stream_partition(self, other: StreamPosition) -> None:
        if self.stream_id != other.stream_id or self.partition_id != other.partition_id:
            raise ValueError("stream positions must share stream_id and partition_id")

    def is_before(self, other: StreamPosition) -> bool:
        self.require_same_stream_partition(other)
        return (self.offset, self.event_sequence) < (
            other.offset,
            other.event_sequence,
        )

    def is_after(self, other: StreamPosition) -> bool:
        self.require_same_stream_partition(other)
        return (self.offset, self.event_sequence) > (
            other.offset,
            other.event_sequence,
        )

    def is_contiguous_after(self, other: StreamPosition) -> bool:
        self.require_same_stream_partition(other)
        return (
            self.offset == other.offset + 1
            and self.event_sequence == other.event_sequence + 1
        )


class StreamEventEnvelope(BaseModel):
    """Event carried by the future durable stream."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    event_id: StreamEventId
    event_kind: str
    stream_position: StreamPosition
    payload: Any
    payload_canonical_hash: str
    payload_size_bytes: int
    durability_status: DurabilityStatus
    producer_id: str
    created_at: datetime

    @field_validator("schema_version", "event_kind", "producer_id")
    @classmethod
    def _validate_trimmed_text(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("text fields must be non-empty and trimmed")
        return value

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: Any) -> Any:
        _canonical_json_bytes(value)
        return value

    @field_validator("payload_canonical_hash")
    @classmethod
    def _validate_hash_format(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("payload_canonical_hash must be a lowercase sha256 hex")
        return value

    @field_validator("payload_size_bytes")
    @classmethod
    def _validate_payload_size(cls, value: int) -> int:
        if value < 0:
            raise ValueError("payload_size_bytes must be >= 0")
        return value

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        payload_bytes = _canonical_json_bytes(self.payload)
        expected_hash = canonical_payload_hash(self.payload)
        if self.payload_canonical_hash != expected_hash:
            raise ValueError("payload_canonical_hash does not match payload")
        if self.payload_size_bytes != len(payload_bytes):
            raise ValueError("payload_size_bytes does not match canonical payload bytes")
        expected_event_id = deterministic_stream_event_id(
            self.stream_position,
            self.event_kind,
            self.payload_canonical_hash,
        )
        if self.event_id != expected_event_id:
            raise ValueError("event_id is not deterministic for stream position/event/hash")
        return self


class DbWriterBatchPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_size_bytes: int
    max_count: int
    max_wait_ms: int
    critical_max_wait_ms: int | None = None

    @field_validator(
        "max_size_bytes",
        "max_count",
        "max_wait_ms",
        "critical_max_wait_ms",
    )
    @classmethod
    def _validate_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("batch policy limits must be positive")
        return value

    def should_flush(
        self,
        accumulated_size_bytes: int,
        accumulated_count: int,
        oldest_event_age_ms: int,
        *,
        is_critical: bool = False,
    ) -> bool:
        if accumulated_size_bytes < 0:
            raise ValueError("accumulated_size_bytes must be >= 0")
        if accumulated_count < 0:
            raise ValueError("accumulated_count must be >= 0")
        if oldest_event_age_ms < 0:
            raise ValueError("oldest_event_age_ms must be >= 0")
        wait_limit = (
            self.critical_max_wait_ms
            if is_critical and self.critical_max_wait_ms is not None
            else self.max_wait_ms
        )
        return (
            accumulated_size_bytes >= self.max_size_bytes
            or accumulated_count >= self.max_count
            or oldest_event_age_ms >= wait_limit
        )


class DbWriterCheckpoint(BaseModel):
    """Forward-only marker for records safely committed to the historical DB."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint_id: DbWriterCheckpointId
    stream_id: StreamId
    partition_id: StreamPartitionId
    persisted_until_offset: int
    persisted_until_event_sequence: int
    persisted_until_event_time: datetime
    last_batch_event_count: int
    last_batch_size_bytes: int
    last_commit_started_at: datetime
    last_commit_finished_at: datetime
    lag_records: int
    lag_ms: int

    @field_validator(
        "persisted_until_offset",
        "persisted_until_event_sequence",
        "last_batch_event_count",
        "last_batch_size_bytes",
        "lag_records",
        "lag_ms",
    )
    @classmethod
    def _validate_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("checkpoint counters must be >= 0")
        return value

    @field_validator(
        "persisted_until_event_time",
        "last_commit_started_at",
        "last_commit_finished_at",
    )
    @classmethod
    def _validate_timestamp(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_commit_window(self) -> Self:
        if self.last_commit_finished_at < self.last_commit_started_at:
            raise ValueError("last_commit_finished_at must be >= last_commit_started_at")
        return self

    @property
    def persisted_until_position(self) -> StreamPosition:
        return StreamPosition(
            stream_id=self.stream_id,
            partition_id=self.partition_id,
            offset=self.persisted_until_offset,
            event_sequence=self.persisted_until_event_sequence,
            event_time=self.persisted_until_event_time,
        )

    def validate_advances_from(self, previous: DbWriterCheckpoint | None) -> None:
        if previous is None:
            return
        if self.stream_id != previous.stream_id or self.partition_id != previous.partition_id:
            raise ValueError("checkpoint stream/partition mismatch")
        if (
            self.persisted_until_offset,
            self.persisted_until_event_sequence,
        ) < (
            previous.persisted_until_offset,
            previous.persisted_until_event_sequence,
        ):
            raise ValueError("checkpoint cannot move backwards")


class LiveStateFreshness(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    latest_position: StreamPosition
    projected_at: datetime
    staleness_ms: int
    gap_free: bool
    is_complete: bool
    is_speculative: bool
    durability_status: DurabilityStatus
    source_health_status: str | None = None

    @field_validator("projected_at")
    @classmethod
    def _validate_projected_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("staleness_ms")
    @classmethod
    def _validate_staleness(cls, value: int) -> int:
        if value < 0:
            raise ValueError("staleness_ms must be >= 0")
        return value

    @field_validator("source_health_status")
    @classmethod
    def _validate_source_health_status(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != value.strip()):
            raise ValueError("source_health_status must be non-empty and trimmed")
        return value

    @model_validator(mode="after")
    def _validate_speculative_consistency(self) -> Self:
        if (
            not self.is_speculative
            and durability_rank(self.durability_status)
            < durability_rank(DurabilityStatus.DURABLE_COMMITTED)
        ):
            raise ValueError(
                "non-speculative state requires DURABLE_COMMITTED or later durability"
            )
        return self

    def is_tradable_for_policy(
        self,
        *,
        max_staleness_ms: int,
        allow_speculative: bool,
        require_gap_free: bool,
        require_complete: bool,
        minimum_durability_status: DurabilityStatus,
    ) -> bool:
        if max_staleness_ms < 0:
            raise ValueError("max_staleness_ms must be >= 0")
        if self.staleness_ms > max_staleness_ms:
            return False
        if require_gap_free and not self.gap_free:
            return False
        if require_complete and not self.is_complete:
            return False
        if self.is_speculative and not allow_speculative:
            return False
        return durability_rank(self.durability_status) >= durability_rank(
            minimum_durability_status
        )


class LiveStateFreshnessPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_staleness_ms: int
    allow_speculative: bool = False
    require_gap_free: bool = True
    require_complete: bool = True
    minimum_durability_status: DurabilityStatus = DurabilityStatus.DURABLE_COMMITTED

    @field_validator("max_staleness_ms")
    @classmethod
    def _validate_max_staleness(cls, value: int) -> int:
        if value < 0:
            raise ValueError("max_staleness_ms must be >= 0")
        return value

    def allows(self, freshness: LiveStateFreshness) -> bool:
        return freshness.is_tradable_for_policy(
            max_staleness_ms=self.max_staleness_ms,
            allow_speculative=self.allow_speculative,
            require_gap_free=self.require_gap_free,
            require_complete=self.require_complete,
            minimum_durability_status=self.minimum_durability_status,
        )


class LiveStateSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: LiveStateSnapshotId
    snapshot_kind: str
    instrument_id: InstrumentId | None = None
    venue_id: VenueId | None = None
    latest_position: StreamPosition
    payload: Any
    payload_canonical_hash: str
    freshness: LiveStateFreshness
    updated_at: datetime

    @field_validator("snapshot_kind")
    @classmethod
    def _validate_snapshot_kind(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("snapshot_kind must be non-empty and trimmed")
        return value

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: Any) -> Any:
        _canonical_json_bytes(value)
        return value

    @field_validator("payload_canonical_hash")
    @classmethod
    def _validate_hash_format(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("payload_canonical_hash must be a lowercase sha256 hex")
        return value

    @field_validator("updated_at")
    @classmethod
    def _validate_updated_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.payload_canonical_hash != canonical_payload_hash(self.payload):
            raise ValueError("payload_canonical_hash does not match payload")
        if self.freshness.latest_position != self.latest_position:
            raise ValueError("freshness.latest_position must equal latest_position")
        return self

    def validate_can_replace(self, previous: LiveStateSnapshot | None) -> None:
        if previous is None:
            return
        if self.snapshot_id != previous.snapshot_id:
            raise ValueError("snapshot_id mismatch")
        self.latest_position.require_same_stream_partition(previous.latest_position)
        if self.latest_position.offset < previous.latest_position.offset:
            raise ValueError("older offset cannot overwrite newer live state")
        if (
            self.latest_position.offset == previous.latest_position.offset
            and self.payload_canonical_hash != previous.payload_canonical_hash
        ):
            raise ValueError("same offset with different payload hash is rejected")


class HistoricalStateSlice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slice_id: HistoricalStateSliceId
    stream_id: StreamId
    partition_id: StreamPartitionId
    from_offset: int
    to_offset: int
    events: tuple[StreamEventEnvelope, ...]
    persisted_until_position: StreamPosition
    is_gap_free: bool

    @field_validator("from_offset", "to_offset")
    @classmethod
    def _validate_offset(cls, value: int) -> int:
        if value < 0:
            raise ValueError("slice offsets must be >= 0")
        return value

    @field_validator("events", mode="before")
    @classmethod
    def _coerce_events(cls, value: object) -> tuple[StreamEventEnvelope, ...]:
        return tuple(value) if isinstance(value, Sequence) and not isinstance(value, str) else value  # type: ignore[return-value]

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        _validate_same_stream_partition(
            self.stream_id,
            self.partition_id,
            self.persisted_until_position,
            "persisted_until_position",
        )
        if not self.events:
            if self.from_offset > self.to_offset:
                return self
            return self
        if self.from_offset > self.to_offset:
            raise ValueError("from_offset must be <= to_offset for non-empty slices")
        _validate_ordered_events(self.events)
        _validate_events_match_stream_partition(
            self.stream_id,
            self.partition_id,
            self.events,
        )
        if self.events[0].stream_position.offset != self.from_offset:
            raise ValueError("from_offset must match first event offset")
        if self.events[-1].stream_position.offset != self.to_offset:
            raise ValueError("to_offset must match last event offset")
        if self.is_gap_free:
            _validate_contiguous_events(self.events)
        if self.persisted_until_position.offset < self.to_offset:
            raise ValueError("persisted_until_position must cover to_offset")
        return self


class LiveTailSlice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slice_id: LiveTailSliceId
    stream_id: StreamId
    partition_id: StreamPartitionId
    from_offset: int
    to_offset: int
    events: tuple[StreamEventEnvelope, ...]
    latest_position: StreamPosition
    freshness: LiveStateFreshness

    @field_validator("from_offset", "to_offset")
    @classmethod
    def _validate_offset(cls, value: int) -> int:
        if value < 0:
            raise ValueError("slice offsets must be >= 0")
        return value

    @field_validator("events", mode="before")
    @classmethod
    def _coerce_events(cls, value: object) -> tuple[StreamEventEnvelope, ...]:
        return tuple(value) if isinstance(value, Sequence) and not isinstance(value, str) else value  # type: ignore[return-value]

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        _validate_same_stream_partition(
            self.stream_id,
            self.partition_id,
            self.latest_position,
            "latest_position",
        )
        if self.freshness.latest_position != self.latest_position:
            raise ValueError("freshness.latest_position must equal latest_position")
        if not self.events:
            return self
        if self.from_offset > self.to_offset:
            raise ValueError("from_offset must be <= to_offset for non-empty slices")
        _validate_ordered_events(self.events)
        _validate_contiguous_events(self.events)
        _validate_events_match_stream_partition(
            self.stream_id,
            self.partition_id,
            self.events,
        )
        if self.events[0].stream_position.offset != self.from_offset:
            raise ValueError("from_offset must match first event offset")
        if self.events[-1].stream_position.offset != self.to_offset:
            raise ValueError("to_offset must match last event offset")
        if self.latest_position.offset < self.to_offset:
            raise ValueError("latest_position must cover to_offset")
        return self


class StitchedStateSlice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slice_id: StitchedStateSliceId
    stream_id: StreamId
    partition_id: StreamPartitionId
    historical: HistoricalStateSlice
    live_tail: LiveTailSlice | None = None
    events: tuple[StreamEventEnvelope, ...]
    from_offset: int
    to_offset: int
    is_complete: bool
    is_gap_free: bool
    tradable: bool
    reason: StitchFailureReason | None = None

    @field_validator("from_offset", "to_offset")
    @classmethod
    def _validate_offset(cls, value: int) -> int:
        if value < 0:
            raise ValueError("slice offsets must be >= 0")
        return value

    @field_validator("events", mode="before")
    @classmethod
    def _coerce_events(cls, value: object) -> tuple[StreamEventEnvelope, ...]:
        return tuple(value) if isinstance(value, Sequence) and not isinstance(value, str) else value  # type: ignore[return-value]

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if (
            self.historical.stream_id != self.stream_id
            or self.historical.partition_id != self.partition_id
        ):
            raise ValueError("historical stream/partition mismatch")
        if self.live_tail is not None and (
            self.live_tail.stream_id != self.stream_id
            or self.live_tail.partition_id != self.partition_id
        ):
            raise ValueError("live_tail stream/partition mismatch")
        if self.events:
            _validate_ordered_events(self.events)
            _validate_events_match_stream_partition(
                self.stream_id,
                self.partition_id,
                self.events,
            )
            if self.events[0].stream_position.offset != self.from_offset:
                raise ValueError("from_offset must match first stitched event offset")
            if self.events[-1].stream_position.offset != self.to_offset:
                raise ValueError("to_offset must match last stitched event offset")
            if self.is_gap_free:
                _validate_contiguous_events(self.events)
        if self.tradable:
            if not self.is_complete or not self.is_gap_free:
                raise ValueError("tradable stitched state must be complete and gap-free")
            if self.reason is not None:
                raise ValueError("tradable stitched state must not have a reason")
        elif self.reason is None:
            raise ValueError("non-tradable stitched state requires a reason")
        return self


def canonical_payload_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def canonical_payload_size_bytes(payload: Any) -> int:
    return len(_canonical_json_bytes(payload))


def deterministic_stream_event_id(
    stream_position: StreamPosition,
    event_kind: str,
    payload_canonical_hash: str,
) -> StreamEventId:
    if not event_kind or event_kind != event_kind.strip():
        raise ValueError("event_kind must be non-empty and trimmed")
    seed = "|".join(
        (
            str(stream_position.stream_id),
            str(stream_position.partition_id),
            str(stream_position.offset),
            str(stream_position.event_sequence),
            stream_position.event_time.isoformat(),
            event_kind,
            payload_canonical_hash,
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return StreamEventId(value=f"stream-event:{digest}")


def durability_rank(status: DurabilityStatus) -> int:
    return _DURABILITY_RANK[status]


def event_identity_matches(
    left: StreamEventEnvelope,
    right: StreamEventEnvelope,
) -> bool:
    return (
        left.event_id == right.event_id
        and left.payload_canonical_hash == right.payload_canonical_hash
    )


def _canonical_json_bytes(payload: Any) -> bytes:
    _validate_json_compatible(payload, path="payload")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _validate_json_compatible(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} float must be finite")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            _validate_json_compatible(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _validate_json_compatible(item, path=f"{path}[{index}]")
        return
    raise ValueError(f"{path} must be JSON-compatible")


def _validate_same_stream_partition(
    stream_id: StreamId,
    partition_id: StreamPartitionId,
    position: StreamPosition,
    name: str,
) -> None:
    if position.stream_id != stream_id or position.partition_id != partition_id:
        raise ValueError(f"{name} stream/partition mismatch")


def _validate_events_match_stream_partition(
    stream_id: StreamId,
    partition_id: StreamPartitionId,
    events: tuple[StreamEventEnvelope, ...],
) -> None:
    for event in events:
        position = event.stream_position
        if position.stream_id != stream_id or position.partition_id != partition_id:
            raise ValueError("events must match stream_id and partition_id")


def _validate_ordered_events(events: tuple[StreamEventEnvelope, ...]) -> None:
    for previous, current in pairwise(events):
        if not current.stream_position.is_after(previous.stream_position):
            raise ValueError("events must be ordered by stream position")


def _validate_contiguous_events(events: tuple[StreamEventEnvelope, ...]) -> None:
    for previous, current in pairwise(events):
        if not current.stream_position.is_contiguous_after(previous.stream_position):
            raise ValueError("events must be contiguous by stream position")


_DURABILITY_RANK = {
    DurabilityStatus.LIVE_ACCEPTED: 0,
    DurabilityStatus.DURABLE_COMMITTED: 1,
    DurabilityStatus.PROJECTED_TO_LIVE_STATE: 2,
    DurabilityStatus.PERSISTED_TO_DB: 3,
    DurabilityStatus.RECONCILED: 4,
}
