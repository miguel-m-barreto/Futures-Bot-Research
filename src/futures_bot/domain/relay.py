from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from futures_bot.domain.broker import KafkaPublishAck
from futures_bot.domain.ids import RunId
from futures_bot.domain.journal import JournalRecord, WalOffset


class WalRelayBatch(BaseModel):
    """An ordered, contiguous slice of WAL records prepared for broker publish."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    records: tuple[JournalRecord, ...]

    @model_validator(mode="after")
    def _validate_records(self) -> Self:
        if not self.records:
            raise ValueError("records must be non-empty")
        for rec in self.records:
            if rec.run_id != self.run_id:
                raise ValueError(
                    f"all records must have run_id={self.run_id!s}; "
                    f"found {rec.run_id!s}"
                )
        offsets = [rec.wal_offset.value for rec in self.records]
        for i in range(1, len(offsets)):
            if offsets[i] <= offsets[i - 1]:
                raise ValueError(
                    "records must be sorted in strictly ascending wal_offset order"
                )
            if offsets[i] != offsets[i - 1] + 1:
                raise ValueError(
                    f"records must be contiguous: gap between offsets "
                    f"{offsets[i - 1]} and {offsets[i]}"
                )
        return self

    @property
    def first_offset(self) -> WalOffset:
        return self.records[0].wal_offset

    @property
    def last_offset(self) -> WalOffset:
        return self.records[-1].wal_offset

    @property
    def record_count(self) -> int:
        return len(self.records)


class WalRelayPublishResult(BaseModel):
    """Broker publish acknowledgement for a WAL relay batch.

    This result represents broker-side (Kafka) progress only.  It is NOT
    sufficient to authorize WAL GC.  WAL GC requires all *required* consumers
    (typically DB_WRITER) to have committed — see RequiredConsumerCheckpointSet
    and decide_wal_gc.

    This model carries no db_transaction_id, no batch_id, and no
    DbWriterCheckpoint.  A WalRelayPublishResult must never be used as a GC
    eligibility signal.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId
    first_offset: WalOffset
    last_offset: WalOffset
    record_count: int
    broker_ack: KafkaPublishAck

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        if self.record_count <= 0:
            raise ValueError("record_count must be > 0")
        if self.first_offset > self.last_offset:
            raise ValueError("first_offset must be <= last_offset")
        expected_count = self.last_offset.value - self.first_offset.value + 1
        if self.record_count != expected_count:
            raise ValueError(
                f"record_count must equal last_offset - first_offset + 1 "
                f"({expected_count}); got {self.record_count}"
            )
        # Always require broker_ack to reference the last record's offset.
        # Partial-batch semantics are not modelled here; if they are needed
        # later they belong in a separate partial-result type.
        if self.broker_ack.journal_offset != self.last_offset:
            raise ValueError(
                "broker_ack.journal_offset must equal last_offset"
            )
        return self
