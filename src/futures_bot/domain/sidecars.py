from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.broker import KafkaPartitionOffset
from futures_bot.domain.ids import BatchId, ConsumerId, EventId, RunId, SidecarId, WalSegmentId
from futures_bot.domain.journal import WalOffset
from futures_bot.domain.time import ensure_aware_utc
from futures_bot.domain.wal import WalSegmentMetadata, WalSegmentStatus


class SidecarKind(StrEnum):
    WAL_RELAY = "WAL_RELAY"
    DB_WRITER = "DB_WRITER"
    LIVE_AGGREGATOR = "LIVE_AGGREGATOR"
    DATASET_WRITER = "DATASET_WRITER"
    EVALUATION_WORKER = "EVALUATION_WORKER"
    DASHBOARD_PROJECTION_WORKER = "DASHBOARD_PROJECTION_WORKER"
    RECONCILER = "RECONCILER"
    MARKET_DATA_COLLECTOR = "MARKET_DATA_COLLECTOR"
    MARKET_STATE_BUILDER = "MARKET_STATE_BUILDER"


class SidecarCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sidecar_id: SidecarId
    sidecar_kind: SidecarKind
    run_id: RunId
    last_committed_wal_offset: WalOffset
    updated_at: datetime
    is_required_for_wal_gc: bool = False
    notes: str | None = None

    @field_validator("updated_at")
    @classmethod
    def _validate_updated_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip():
            raise ValueError("notes must be a non-empty trimmed string")
        return value

    def can_advance_to(self, next_offset: WalOffset) -> bool:
        return next_offset.value >= self.last_committed_wal_offset.value


class WalRelayCheckpoint(BaseModel):
    """Broker publish progress only. Not sufficient for WAL GC authorization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relay_id: SidecarId
    run_id: RunId
    last_published_wal_offset: WalOffset
    last_published_event_id: EventId
    kafka_offset: KafkaPartitionOffset
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def _validate_updated_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


class DbWriterCheckpoint(BaseModel):
    """Durable DB commit progress. Written in the same DB transaction as event ingestion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    consumer_id: ConsumerId
    run_id: RunId
    last_committed_wal_offset: WalOffset
    last_committed_event_id: EventId
    kafka_offset: KafkaPartitionOffset
    db_transaction_id: str
    batch_id: BatchId
    updated_at: datetime

    @field_validator("db_transaction_id")
    @classmethod
    def _validate_db_transaction_id(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("db_transaction_id must be a non-empty trimmed string")
        return value

    @field_validator("updated_at")
    @classmethod
    def _validate_updated_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)


class RequiredConsumerCheckpointSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    checkpoints: tuple[SidecarCheckpoint, ...] = ()

    @model_validator(mode="after")
    def _validate_checkpoints(self) -> Self:
        seen: set[str] = set()
        for cp in self.checkpoints:
            if str(cp.run_id) != str(self.run_id):
                raise ValueError(
                    "checkpoint run_id must match RequiredConsumerCheckpointSet run_id"
                )
            sid = str(cp.sidecar_id)
            if sid in seen:
                raise ValueError("duplicate sidecar_id in checkpoint set")
            seen.add(sid)
        return self

    def required_checkpoints(self) -> tuple[SidecarCheckpoint, ...]:
        return tuple(cp for cp in self.checkpoints if cp.is_required_for_wal_gc)

    def required_min_offset(self) -> WalOffset | None:
        required = self.required_checkpoints()
        if not required:
            return None
        slowest = min(required, key=lambda cp: cp.last_committed_wal_offset.value)
        return slowest.last_committed_wal_offset

    def all_required_consumers_reached(self, offset: WalOffset) -> bool:
        required = self.required_checkpoints()
        if not required:
            return False
        return all(cp.last_committed_wal_offset.value >= offset.value for cp in required)


class WalGcAction(StrEnum):
    KEEP = "KEEP"
    ARCHIVE = "ARCHIVE"
    DELETE = "DELETE"


class WalGcDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    segment_id: WalSegmentId
    action: WalGcAction
    eligible: bool
    reason: str
    decided_at: datetime
    required_checkpoint_min_offset: WalOffset | None = None

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("reason must be a non-empty trimmed string")
        return value

    @field_validator("decided_at")
    @classmethod
    def _validate_decided_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def _validate_action_invariants(self) -> Self:
        if self.action is WalGcAction.KEEP:
            if self.eligible:
                raise ValueError("KEEP action requires eligible=False")
        else:
            if not self.eligible:
                raise ValueError("ARCHIVE/DELETE action requires eligible=True")
            if self.required_checkpoint_min_offset is None:
                raise ValueError(
                    "ARCHIVE/DELETE action requires required_checkpoint_min_offset"
                )
        return self


def decide_wal_gc(  # noqa: PLR0911
    segment: WalSegmentMetadata,
    checkpoints: RequiredConsumerCheckpointSet,
    decided_at: datetime,
    *,
    archive_instead_of_delete: bool = True,
) -> WalGcDecision:
    def _keep(reason: str) -> WalGcDecision:
        return WalGcDecision(
            segment_id=segment.segment_id,
            action=WalGcAction.KEEP,
            eligible=False,
            reason=reason,
            decided_at=decided_at,
        )

    if segment.run_id != checkpoints.run_id:
        return _keep(
            f"segment run_id {segment.run_id!s} does not match "
            f"checkpoint set run_id {checkpoints.run_id!s}"
        )

    if segment.status is WalSegmentStatus.OPEN:
        return _keep("segment is OPEN")

    if segment.status is WalSegmentStatus.DELETED:
        return _keep("segment is already DELETED")

    if segment.offset_range is None:
        return _keep("segment has no offset_range")

    required = checkpoints.required_checkpoints()
    if not required:
        return _keep("no required consumer checkpoints configured")

    if not checkpoints.all_required_consumers_reached(segment.offset_range.last):
        return _keep("not all required consumers have reached segment end offset")

    min_offset = min(
        required, key=lambda cp: cp.last_committed_wal_offset.value
    ).last_committed_wal_offset
    action = WalGcAction.ARCHIVE if archive_instead_of_delete else WalGcAction.DELETE
    return WalGcDecision(
        segment_id=segment.segment_id,
        action=action,
        eligible=True,
        reason="all required consumers have committed at or beyond segment end offset",
        decided_at=decided_at,
        required_checkpoint_min_offset=min_offset,
    )


class RuntimeBackpressureState(StrEnum):
    NORMAL = "NORMAL"
    WAL_BACKLOG_HIGH = "WAL_BACKLOG_HIGH"
    WAL_BACKLOG_CRITICAL = "WAL_BACKLOG_CRITICAL"
    WAL_FULL = "WAL_FULL"
    WAL_UNAVAILABLE = "WAL_UNAVAILABLE"


_STATES_REQUIRING_BLOCK_NEW_ENTRIES: frozenset[RuntimeBackpressureState] = frozenset(
    {
        RuntimeBackpressureState.WAL_FULL,
        RuntimeBackpressureState.WAL_UNAVAILABLE,
        RuntimeBackpressureState.WAL_BACKLOG_CRITICAL,
    }
)


class RuntimeBackpressureDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: RuntimeBackpressureState
    allow_new_entries: bool
    allow_exits: bool
    allow_protective_actions: bool
    reason: str

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("reason must be a non-empty trimmed string")
        return value

    @model_validator(mode="after")
    def _validate_backpressure_invariants(self) -> Self:
        if self.state in _STATES_REQUIRING_BLOCK_NEW_ENTRIES and self.allow_new_entries:
            raise ValueError(f"{self.state} requires allow_new_entries=False")
        return self
