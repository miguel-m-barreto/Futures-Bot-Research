from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.ids import RunId, WalSegmentId
from futures_bot.domain.journal import JournalRecord, WalOffsetRange
from futures_bot.domain.time import ensure_aware_utc


class WalSegmentStatus(StrEnum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    PUBLISHED_TO_KAFKA = "PUBLISHED_TO_KAFKA"
    REQUIRED_CONSUMERS_COMMITTED = "REQUIRED_CONSUMERS_COMMITTED"
    ELIGIBLE_FOR_DELETE = "ELIGIBLE_FOR_DELETE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class WalSegmentMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    segment_id: WalSegmentId
    run_id: RunId
    status: WalSegmentStatus
    offset_range: WalOffsetRange | None = None
    created_at: datetime
    sealed_at: datetime | None = None
    event_count: int = 0
    payload_bytes: int = 0
    segment_hash: str | None = None
    previous_segment_hash: str | None = None

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("sealed_at")
    @classmethod
    def _validate_sealed_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return ensure_aware_utc(value)

    @field_validator("event_count")
    @classmethod
    def _validate_event_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("event_count must be >= 0")
        return value

    @field_validator("payload_bytes")
    @classmethod
    def _validate_payload_bytes(cls, value: int) -> int:
        if value < 0:
            raise ValueError("payload_bytes must be >= 0")
        return value

    @field_validator("segment_hash")
    @classmethod
    def _validate_segment_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip():
            raise ValueError("segment_hash must be a non-empty trimmed string")
        return value

    @field_validator("previous_segment_hash")
    @classmethod
    def _validate_previous_segment_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip():
            raise ValueError("previous_segment_hash must be a non-empty trimmed string")
        return value

    @model_validator(mode="after")
    def _validate_status_invariants(self) -> Self:
        if self.status is WalSegmentStatus.OPEN and self.sealed_at is not None:
            raise ValueError("OPEN segment must not have sealed_at")
        if self.status is not WalSegmentStatus.OPEN and self.sealed_at is None:
            raise ValueError("non-OPEN segment requires sealed_at")
        if self.sealed_at is not None and self.sealed_at < self.created_at:
            raise ValueError("sealed_at must be >= created_at")
        if self.offset_range is not None and self.event_count != self.offset_range.count:
            raise ValueError(
                "event_count must match offset_range count when offset_range is present"
            )
        if self.status is WalSegmentStatus.DELETED and (
            self.sealed_at is None or self.offset_range is None
        ):
            raise ValueError("DELETED segment requires both sealed_at and offset_range")
        return self


class WalAppendStatus(StrEnum):
    APPENDED = "APPENDED"
    REJECTED_WAL_UNAVAILABLE = "REJECTED_WAL_UNAVAILABLE"
    REJECTED_WAL_FULL = "REJECTED_WAL_FULL"
    REJECTED_BACKPRESSURE = "REJECTED_BACKPRESSURE"
    REJECTED_INVALID_EVENT = "REJECTED_INVALID_EVENT"


class WalAppendResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: WalAppendStatus
    appended: bool
    record: JournalRecord | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.status is WalAppendStatus.APPENDED:
            if not self.appended:
                raise ValueError("APPENDED status requires appended=True")
            if self.record is None:
                raise ValueError("APPENDED status requires record")
            if self.reason is not None:
                raise ValueError("APPENDED status must not have reason")
        else:
            if self.appended:
                raise ValueError("rejected status requires appended=False")
            if self.record is not None:
                raise ValueError("rejected status must not carry record")
            if not self.reason or self.reason != self.reason.strip():
                raise ValueError("rejected status requires a non-empty trimmed reason")
        return self

    @classmethod
    def ok(cls, record: JournalRecord) -> WalAppendResult:
        return cls(status=WalAppendStatus.APPENDED, appended=True, record=record)

    @classmethod
    def rejected(cls, status: WalAppendStatus, reason: str) -> WalAppendResult:
        return cls(status=status, appended=False, reason=reason)
