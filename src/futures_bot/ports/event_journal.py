from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Protocol

from futures_bot.domain.events import EventEnvelope
from futures_bot.domain.ids import WalSegmentId
from futures_bot.domain.journal import JournalRecord
from futures_bot.domain.wal import WalAppendResult, WalSegmentMetadata


class EventJournalPort(Protocol):
    """Append-only event journal port.

    Concrete implementations provide local WAL, in-memory, or other backends.
    """

    def append(
        self,
        event: EventEnvelope,
        *,
        recorded_at: datetime | None = None,
    ) -> WalAppendResult:
        """Append an event to the journal and return the result."""
        ...

    def current_segment_metadata(self) -> WalSegmentMetadata:
        """Return metadata for the currently active (open) segment."""
        ...

    def list_segment_metadata(self) -> tuple[WalSegmentMetadata, ...]:
        """Return metadata for all known segments, sealed then active."""
        ...

    def seal_current_segment(self) -> WalSegmentMetadata:
        """Seal the active segment and open a fresh one. Returns sealed metadata."""
        ...

    def iter_records(self) -> Iterator[JournalRecord]:
        """Yield every record across all segments in WAL offset order."""
        ...

    def read_segment(self, segment_id: WalSegmentId) -> tuple[JournalRecord, ...]:
        """Return all records from the named segment."""
        ...

    def close(self) -> None:
        """Flush and close the journal. Subsequent appends return rejected."""
        ...
