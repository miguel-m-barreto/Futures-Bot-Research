"""One-shot local DB writer service.

No real DB. No Kafka client. No WAL access. No runtime loop. No GC logic.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from itertools import pairwise
from typing import Protocol

from futures_bot.domain import broker as broker_domain
from futures_bot.domain.ids import BatchId, ConsumerId, RunId, SidecarId
from futures_bot.domain.journal import JournalRecord
from futures_bot.domain.sidecars import DbWriterCheckpoint, SidecarCheckpoint, SidecarKind
from futures_bot.ports.checkpoint_store import (
    DbWriterCheckpointStorePort,
    RequiredConsumerCheckpointWriterPort,
)


class CommittedEventStorePort(Protocol):
    """Minimal durable-event sink contract used by LocalDbWriterService."""

    def commit_records(
        self, records: tuple[broker_domain.KafkaPublishRecord, ...]
    ) -> tuple[JournalRecord, ...]:
        """Durably commit records and return committed journal records."""
        ...

    def committed_records(self, run_id: RunId) -> tuple[JournalRecord, ...]:
        """Return committed records for run_id in WAL offset order."""
        ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LocalDbWriterService:
    """One-shot local DB writer service.

    Consumes already-published KafkaPublishRecord objects, commits their
    JournalRecord payloads into a local sink, then advances DB writer and
    required-consumer checkpoints only after the commit succeeds.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        consumer_id: ConsumerId,
        db_store: CommittedEventStorePort,
        checkpoint_store: DbWriterCheckpointStorePort,
        required_checkpoint_writer: RequiredConsumerCheckpointWriterPort | None,
        is_required_for_wal_gc: bool = True,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._consumer_id = consumer_id
        self._db_store = db_store
        self._checkpoint_store = checkpoint_store
        self._required_checkpoint_writer = required_checkpoint_writer
        self._is_required_for_wal_gc = is_required_for_wal_gc
        self._now: Callable[[], datetime] = now if now is not None else _utcnow

    def commit_published_batch(
        self, records: tuple[broker_domain.KafkaPublishRecord, ...]
    ) -> DbWriterCheckpoint | None:
        """Commit published records and advance checkpoints after success."""
        self._validate_batch(records)

        run_id = records[0].journal_record.run_id
        checkpoint = self._checkpoint_store.load(self._consumer_id, run_id)

        if checkpoint is None:
            records_to_commit = records
        else:
            self._validate_checkpoint_duplicates(records, checkpoint)
            records_to_commit = tuple(
                record
                for record in records
                if (
                    record.journal_record.wal_offset.value
                    > checkpoint.last_committed_wal_offset.value
                )
            )
            if not records_to_commit:
                return checkpoint

            expected = checkpoint.last_committed_wal_offset.value + 1
            found = records_to_commit[0].journal_record.wal_offset.value
            if found != expected:
                raise ValueError(
                    f"DB writer gap detected: expected next offset {expected}, found {found}"
                )

        committed = self._db_store.commit_records(records_to_commit)
        last_record = committed[-1]
        first_offset = committed[0].wal_offset.value
        last_offset = last_record.wal_offset.value
        saved_at = self._now()

        saved_checkpoint = DbWriterCheckpoint(
            consumer_id=self._consumer_id,
            run_id=run_id,
            last_committed_wal_offset=last_record.wal_offset,
            last_committed_event_id=last_record.event.event_id,
            kafka_offset=self._checkpoint_kafka_offset(records_to_commit[-1]),
            db_transaction_id=(
                f"local-dbwriter:{self._consumer_id!s}:{run_id!s}:{last_offset}"
            ),
            batch_id=BatchId(
                value=f"dbw-{self._consumer_id!s}-{run_id!s}-{first_offset}-{last_offset}"
            ),
            updated_at=saved_at,
        )
        self._checkpoint_store.save(saved_checkpoint)

        if self._required_checkpoint_writer is not None:
            self._required_checkpoint_writer.upsert(
                SidecarCheckpoint(
                    sidecar_id=SidecarId(value=f"db-writer:{self._consumer_id!s}"),
                    sidecar_kind=SidecarKind.DB_WRITER,
                    run_id=run_id,
                    last_committed_wal_offset=last_record.wal_offset,
                    updated_at=saved_at,
                    is_required_for_wal_gc=self._is_required_for_wal_gc,
                )
            )

        return saved_checkpoint

    @staticmethod
    def _validate_batch(records: tuple[broker_domain.KafkaPublishRecord, ...]) -> None:
        if not records:
            raise ValueError("records must be non-empty")

        run_id = records[0].journal_record.run_id
        offsets = [record.journal_record.wal_offset.value for record in records]

        for record in records:
            if record.journal_record.run_id != run_id:
                raise ValueError("records must all have the same run_id")

        if offsets != sorted(offsets):
            raise ValueError("records must be sorted by wal_offset")

        for previous, current in pairwise(offsets):
            if current != previous + 1:
                raise ValueError("records must be contiguous by wal_offset")

    def _validate_checkpoint_duplicates(
        self,
        records: tuple[broker_domain.KafkaPublishRecord, ...],
        checkpoint: DbWriterCheckpoint,
    ) -> None:
        committed_by_offset = {
            record.wal_offset.value: record
            for record in self._db_store.committed_records(checkpoint.run_id)
        }

        checkpoint_offset = checkpoint.last_committed_wal_offset.value
        for record in records:
            wal_offset = record.journal_record.wal_offset.value
            if wal_offset > checkpoint_offset:
                continue

            committed = committed_by_offset.get(wal_offset)
            if committed is None:
                raise ValueError(
                    f"record at offset {wal_offset} is at or before checkpoint "
                    "but is not committed"
                )
            if committed.event.event_id != record.journal_record.event.event_id:
                raise ValueError(
                    f"record conflict at offset {wal_offset}: "
                    f"existing event_id {committed.event.event_id!s}, "
                    f"new event_id {record.journal_record.event.event_id!s}"
                )

    @staticmethod
    def _checkpoint_kafka_offset(
        record: broker_domain.KafkaPublishRecord,
    ) -> broker_domain.KafkaPartitionOffset:
        return broker_domain.KafkaPartitionOffset(
            topic=record.topic,
            partition=0,
            offset=record.journal_record.wal_offset.value,
        )
