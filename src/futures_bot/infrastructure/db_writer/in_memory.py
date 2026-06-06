"""In-memory committed event store for DB writer tests and local validation.

No DB. No filesystem. No Kafka client. No WAL or GC logic.
"""
from __future__ import annotations

from itertools import pairwise

from futures_bot.domain import broker as broker_domain
from futures_bot.domain.ids import EventId, RunId
from futures_bot.domain.journal import JournalRecord, WalOffset


class InMemoryCommittedEventStore:
    """Simulates durable event ingestion in memory.

    Records are keyed by (run_id, wal_offset).  Recommitting the same offset
    with the same event_id is idempotent; a different event_id at an existing
    offset is rejected.
    """

    def __init__(self, fail_next_commit: bool = False) -> None:
        self._records: dict[tuple[str, int], broker_domain.KafkaConsumedRecord] = {}
        self.fail_next_commit = fail_next_commit

    def commit_records(
        self, records: tuple[broker_domain.KafkaConsumedRecord, ...]
    ) -> tuple[JournalRecord, ...]:
        """Commit a non-empty, single-run, sorted, contiguous record batch."""
        self._validate_batch(records)

        if self.fail_next_commit:
            self.fail_next_commit = False
            raise RuntimeError("simulated DB writer commit failure")

        journal_records = tuple(record.journal_record for record in records)
        staged: dict[tuple[str, int], broker_domain.KafkaConsumedRecord] = {}

        for record in records:
            journal_record = record.journal_record
            key = (str(journal_record.run_id), journal_record.wal_offset.value)
            existing = self._records.get(key) or staged.get(key)
            if existing is not None:
                self._validate_same_event_id(
                    key,
                    existing.journal_record.event.event_id,
                    journal_record.event.event_id,
                )
                self._validate_same_kafka_offset(
                    key, existing.kafka_offset, record.kafka_offset
                )
                continue
            staged[key] = record

        self._records.update(staged)
        return journal_records

    def committed_records(self, run_id: RunId) -> tuple[JournalRecord, ...]:
        """Return committed records for run_id in WAL offset order."""
        records = [
            record
            for (stored_run_id, _), record in self._records.items()
            if stored_run_id == str(run_id)
        ]
        sorted_records = sorted(
            records, key=lambda record: record.journal_record.wal_offset.value
        )
        return tuple(record.journal_record for record in sorted_records)

    def committed_offsets(self, run_id: RunId) -> tuple[WalOffset, ...]:
        """Return committed WAL offsets for run_id in ascending order."""
        return tuple(record.wal_offset for record in self.committed_records(run_id))

    def has_committed(self, run_id: RunId, wal_offset: WalOffset) -> bool:
        """Return whether run_id has a committed record at wal_offset."""
        return (str(run_id), wal_offset.value) in self._records

    def committed_kafka_offset(
        self, run_id: RunId, wal_offset: WalOffset
    ) -> broker_domain.KafkaPartitionOffset | None:
        """Return the committed broker offset for run_id/wal_offset, if any."""
        record = self._records.get((str(run_id), wal_offset.value))
        if record is None:
            return None
        return record.kafka_offset

    @staticmethod
    def _validate_batch(records: tuple[broker_domain.KafkaConsumedRecord, ...]) -> None:
        if not records:
            raise ValueError("records must be non-empty")

        _validate_consumed_record_types(records)
        _validate_batch_scope(records)
        _validate_sorted_contiguous(
            [record.journal_record.wal_offset.value for record in records],
            sort_message="records must be sorted by wal_offset",
            contiguous_message="records must be contiguous by wal_offset",
        )
        _validate_sorted_contiguous(
            [record.kafka_offset.offset for record in records],
            sort_message="records must be sorted by broker offset",
            contiguous_message="records must be contiguous by broker offset",
        )

    @staticmethod
    def _validate_same_event_id(
        key: tuple[str, int], existing_event_id: EventId, new_event_id: EventId
    ) -> None:
        if existing_event_id != new_event_id:
            _, offset = key
            raise ValueError(
                f"committed record conflict at offset {offset}: "
                f"existing event_id {existing_event_id!s}, new event_id {new_event_id!s}"
            )

    @staticmethod
    def _validate_same_kafka_offset(
        key: tuple[str, int],
        existing_offset: broker_domain.KafkaPartitionOffset,
        new_offset: broker_domain.KafkaPartitionOffset,
    ) -> None:
        if existing_offset != new_offset:
            _, offset = key
            raise ValueError(
                f"committed record conflict at offset {offset}: "
                f"existing kafka_offset {existing_offset!s}, "
                f"new kafka_offset {new_offset!s}"
            )


def _validate_consumed_record_types(
    records: tuple[broker_domain.KafkaConsumedRecord, ...]
) -> None:
    for record in records:
        if not isinstance(record, broker_domain.KafkaConsumedRecord):
            raise TypeError(
                "commit_records requires KafkaConsumedRecord objects with "
                "assigned kafka_offset"
            )


def _validate_batch_scope(records: tuple[broker_domain.KafkaConsumedRecord, ...]) -> None:
    run_id = records[0].journal_record.run_id
    topic = records[0].topic
    partition = records[0].kafka_offset.partition

    for record in records:
        if record.journal_record.run_id != run_id:
            raise ValueError("records must all have the same run_id")
        if record.topic != topic:
            raise ValueError("records must all have the same topic")
        if record.kafka_offset.partition != partition:
            raise ValueError("records must all have the same broker partition")


def _validate_sorted_contiguous(
    values: list[int],
    *,
    sort_message: str,
    contiguous_message: str,
) -> None:
    if values != sorted(values):
        raise ValueError(sort_message)

    for previous, current in pairwise(values):
        if current != previous + 1:
            raise ValueError(contiguous_message)
