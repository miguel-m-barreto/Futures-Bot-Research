from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from futures_bot.domain.events import EventEnvelope
from futures_bot.domain.ids import ProducerId, RunId
from futures_bot.domain.time import ensure_aware_utc
from futures_bot.domain.wal_offsets import WalOffset, WalOffsetRange

__all__ = ["JournalRecord", "WalOffset", "WalOffsetRange"]


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
