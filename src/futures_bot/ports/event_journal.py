from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Protocol

from futures_bot.domain.event_journal import (
    EventJournalCheckpoint,
    EventJournalReadinessPolicy,
    EventJournalRecord,
)
from futures_bot.domain.events import EventEnvelope
from futures_bot.domain.ids import (
    EventJournalCheckpointId,
    EventJournalReadinessPolicyId,
    EventJournalRecordId,
    EventJournalStreamId,
)
from futures_bot.domain.journal import JournalRecord
from futures_bot.domain.wal import WalAppendResult, WalSegmentMetadata


class EventJournalPort(Protocol):
    """Legacy local WAL journal port used by the one-shot relay service."""

    def append(
        self,
        event: EventEnvelope,
        *,
        recorded_at: datetime | None = None,
    ) -> WalAppendResult:
        """Append an event envelope to the local journal boundary."""
        ...

    def iter_records(self) -> Iterator[JournalRecord]:
        """Iterate journal records in deterministic WAL order."""
        ...

    def current_segment_metadata(self) -> WalSegmentMetadata:
        """Return current segment metadata."""
        ...

    def list_segment_metadata(self) -> tuple[WalSegmentMetadata, ...]:
        """Return segment metadata in deterministic order."""
        ...

    def seal_current_segment(self) -> WalSegmentMetadata:
        """Seal the current segment and return its metadata."""
        ...


class EventJournalRecordStorePort(Protocol):
    """Pure event-journal record store interface."""

    def put(self, record: EventJournalRecord) -> None:
        """Store an event-journal record idempotently."""
        ...

    def get(self, record_id: EventJournalRecordId) -> EventJournalRecord | None:
        """Return an event-journal record by ID."""
        ...

    def list_records(self) -> tuple[EventJournalRecord, ...]:
        """Return all records in deterministic ID order."""
        ...

    def list_by_stream(
        self,
        stream_id: EventJournalStreamId,
    ) -> tuple[EventJournalRecord, ...]:
        """Return stream records by sequence number then record ID."""
        ...

    def latest_for_stream(
        self,
        stream_id: EventJournalStreamId,
    ) -> EventJournalRecord | None:
        """Return the latest deterministic record for a stream."""
        ...


class EventJournalCheckpointStorePort(Protocol):
    """Pure event-journal checkpoint store interface."""

    def put(self, checkpoint: EventJournalCheckpoint) -> None:
        """Store an event-journal checkpoint idempotently."""
        ...

    def get(self, checkpoint_id: EventJournalCheckpointId) -> EventJournalCheckpoint | None:
        """Return an event-journal checkpoint by ID."""
        ...

    def list_checkpoints(self) -> tuple[EventJournalCheckpoint, ...]:
        """Return all checkpoints in deterministic ID order."""
        ...


class EventJournalReadinessPolicyStorePort(Protocol):
    """Pure event-journal readiness policy store interface."""

    def put(self, policy: EventJournalReadinessPolicy) -> None:
        """Store an event-journal readiness policy idempotently."""
        ...

    def get(
        self,
        policy_id: EventJournalReadinessPolicyId,
    ) -> EventJournalReadinessPolicy | None:
        """Return an event-journal readiness policy by ID."""
        ...

    def list_policies(self) -> tuple[EventJournalReadinessPolicy, ...]:
        """Return all policies in deterministic ID order."""
        ...
