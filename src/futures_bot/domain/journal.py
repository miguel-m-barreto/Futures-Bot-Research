from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from futures_bot.domain.events import EventEnvelope
from futures_bot.domain.ids import ProducerId, RunId
from futures_bot.domain.time import ensure_aware_utc


class WalOffset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: int

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: int) -> int:
        if value < 0:
            raise ValueError("WalOffset value must be >= 0")
        return value

    def next(self) -> WalOffset:
        return WalOffset(value=self.value + 1)

    def is_before_or_equal(self, other: WalOffset) -> bool:
        return self.value <= other.value

    def __lt__(self, other: WalOffset) -> bool:
        return self.value < other.value

    def __le__(self, other: WalOffset) -> bool:
        return self.value <= other.value


class WalOffsetRange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    first: WalOffset
    last: WalOffset

    @model_validator(mode="after")
    def _validate_range(self) -> WalOffsetRange:
        if self.first.value > self.last.value:
            raise ValueError("WalOffsetRange first must be <= last")
        return self

    @property
    def count(self) -> int:
        return self.last.value - self.first.value + 1

    def contains(self, offset: WalOffset) -> bool:
        return self.first.value <= offset.value <= self.last.value


class JournalRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    producer_id: ProducerId
    wal_offset: WalOffset
    event: EventEnvelope
    recorded_at: datetime
    payload_hash: str
    record_size_bytes: int

    @field_validator("recorded_at")
    @classmethod
    def _validate_recorded_at(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("payload_hash")
    @classmethod
    def _validate_payload_hash(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("payload_hash must be a non-empty trimmed string")
        return value

    @field_validator("record_size_bytes")
    @classmethod
    def _validate_record_size_bytes(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("record_size_bytes must be > 0")
        return value
