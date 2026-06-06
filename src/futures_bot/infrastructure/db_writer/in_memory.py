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
        self._records: dict[tuple[str, int], JournalRecord] = {}
        self.fail_next_commit = fail_next_commit

    def commit_records(
        self, records: tuple[broker_domain.KafkaPublishRecord, ...]
    ) -> tuple[JournalRecord, ...]:
        """Commit a non-empty, single-run, sorted, contiguous record batch."""
        self._validate_batch(records)

        if self.fail_next_commit:
            self.fail_next_commit = False
            raise RuntimeError("simulated DB writer commit failure")

        journal_records = tuple(record.journal_record for record in records)
        staged: dict[tuple[str, int], JournalRecord] = {}

        for record in journal_records:
            key = (str(record.run_id), record.wal_offset.value)
            existing = self._records.get(key) or staged.get(key)
            if existing is not None:
                self._validate_same_event_id(key, existing.event.event_id, record.event.event_id)
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
        return tuple(sorted(records, key=lambda record: record.wal_offset.value))

    def committed_offsets(self, run_id: RunId) -> tuple[WalOffset, ...]:
        """Return committed WAL offsets for run_id in ascending order."""
        return tuple(record.wal_offset for record in self.committed_records(run_id))

    def has_committed(self, run_id: RunId, wal_offset: WalOffset) -> bool:
        """Return whether run_id has a committed record at wal_offset."""
        return (str(run_id), wal_offset.value) in self._records

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
