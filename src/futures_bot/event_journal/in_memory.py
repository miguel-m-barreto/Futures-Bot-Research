from __future__ import annotations

from futures_bot.domain.event_journal import (
    EventJournalCheckpoint,
    EventJournalReadinessPolicy,
    EventJournalRecord,
)
from futures_bot.domain.ids import (
    EventJournalCheckpointId,
    EventJournalReadinessPolicyId,
    EventJournalRecordId,
    EventJournalStreamId,
)


class InMemoryEventJournalRecordStore:
    """Deterministic event-journal record store test double."""

    def __init__(self) -> None:
        self._records_by_id: dict[str, EventJournalRecord] = {}
        self._record_ids_by_stream: dict[str, set[str]] = {}
        self._record_id_by_stream_sequence: dict[tuple[str, int], str] = {}

    def put(self, record: EventJournalRecord) -> None:
        if record.record_id is None:
            raise ValueError("event journal record must have record_id")
        key = str(record.record_id)
        stream_key = str(record.stream_id)
        sequence_key = (stream_key, record.sequence_number)

        existing_sequence_record_id = self._record_id_by_stream_sequence.get(sequence_key)
        if existing_sequence_record_id is not None and existing_sequence_record_id != key:
            raise ValueError("event journal stream sequence collision")

        existing = self._records_by_id.get(key)
        if existing is not None:
            if existing != record:
                raise ValueError("event journal record id collision")
            return

        self._records_by_id[key] = record
        self._record_ids_by_stream.setdefault(stream_key, set()).add(key)
        self._record_id_by_stream_sequence[sequence_key] = key

    def get(self, record_id: EventJournalRecordId) -> EventJournalRecord | None:
        return self._records_by_id.get(str(record_id))

    def list_records(self) -> tuple[EventJournalRecord, ...]:
        return tuple(self._records_by_id[key] for key in sorted(self._records_by_id))

    def list_by_stream(
        self,
        stream_id: EventJournalStreamId,
    ) -> tuple[EventJournalRecord, ...]:
        record_ids = self._record_ids_by_stream.get(str(stream_id), set())
        records = tuple(self._records_by_id[record_id] for record_id in record_ids)
        return tuple(
            sorted(records, key=lambda item: (item.sequence_number, str(item.record_id)))
        )

    def latest_for_stream(
        self,
        stream_id: EventJournalStreamId,
    ) -> EventJournalRecord | None:
        records = self.list_by_stream(stream_id)
        if not records:
            return None
        return max(records, key=lambda item: (item.sequence_number, str(item.record_id)))


class InMemoryEventJournalCheckpointStore:
    """Deterministic event-journal checkpoint store test double."""

    def __init__(self) -> None:
        self._checkpoints_by_id: dict[str, EventJournalCheckpoint] = {}

    def put(self, checkpoint: EventJournalCheckpoint) -> None:
        if checkpoint.checkpoint_id is None:
            raise ValueError("event journal checkpoint must have checkpoint_id")
        key = str(checkpoint.checkpoint_id)
        existing = self._checkpoints_by_id.get(key)
        if existing is not None:
            if existing != checkpoint:
                raise ValueError("event journal checkpoint id collision")
            return
        self._checkpoints_by_id[key] = checkpoint

    def get(self, checkpoint_id: EventJournalCheckpointId) -> EventJournalCheckpoint | None:
        return self._checkpoints_by_id.get(str(checkpoint_id))

    def list_checkpoints(self) -> tuple[EventJournalCheckpoint, ...]:
        return tuple(
            self._checkpoints_by_id[key] for key in sorted(self._checkpoints_by_id)
        )


class InMemoryEventJournalReadinessPolicyStore:
    """Deterministic event-journal readiness policy store test double."""

    def __init__(self) -> None:
        self._policies_by_id: dict[str, EventJournalReadinessPolicy] = {}

    def put(self, policy: EventJournalReadinessPolicy) -> None:
        if policy.policy_id is None:
            raise ValueError("event journal policy must have policy_id")
        key = str(policy.policy_id)
        existing = self._policies_by_id.get(key)
        if existing is not None:
            if existing != policy:
                raise ValueError("event journal policy id collision")
            return
        self._policies_by_id[key] = policy

    def get(
        self,
        policy_id: EventJournalReadinessPolicyId,
    ) -> EventJournalReadinessPolicy | None:
        return self._policies_by_id.get(str(policy_id))

    def list_policies(self) -> tuple[EventJournalReadinessPolicy, ...]:
        return tuple(self._policies_by_id[key] for key in sorted(self._policies_by_id))
