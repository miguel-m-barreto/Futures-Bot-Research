from __future__ import annotations

from typing import Protocol

from futures_bot.domain.ids import LiveStateSnapshotId, StreamId, StreamPartitionId
from futures_bot.domain.live_state import (
    DbWriterCheckpoint,
    HistoricalStateSlice,
    LiveStateFreshnessPolicy,
    LiveStateSnapshot,
    LiveTailSlice,
    StitchedStateSlice,
    StreamEventEnvelope,
)


class DurableEventStreamPort(Protocol):
    """Pure interface for the future canonical durable stream."""

    def append(self, event: StreamEventEnvelope) -> StreamEventEnvelope:
        """Append an event and return the canonical durable envelope."""
        ...

    def read_from(
        self,
        stream_id: StreamId,
        partition_id: StreamPartitionId,
        from_offset: int,
    ) -> tuple[StreamEventEnvelope, ...]:
        """Return durable events from from_offset in deterministic stream order."""
        ...


class LiveStateProjectorPort(Protocol):
    """Pure interface for applying stream events into materialized live state."""

    def project(self, event: StreamEventEnvelope) -> LiveStateSnapshot:
        """Apply one stream event and return the resulting snapshot."""
        ...


class LiveStateGatewayPort(Protocol):
    """Pure interface for freshness-aware bot-facing state snapshots."""

    def put_snapshot(self, snapshot: LiveStateSnapshot) -> None:
        """Store a snapshot if it does not regress freshness or offset."""
        ...

    def get_snapshot(
        self,
        snapshot_id: LiveStateSnapshotId,
    ) -> LiveStateSnapshot | None:
        """Return the latest snapshot, or None."""
        ...


class HistoricalStateReaderPort(Protocol):
    """Pure interface for historical/audit state slices."""

    def read_slice(
        self,
        stream_id: StreamId,
        partition_id: StreamPartitionId,
        from_offset: int,
        to_offset: int,
    ) -> HistoricalStateSlice:
        """Return historical events for the requested inclusive offset range."""
        ...


class DbWriterCheckpointPort(Protocol):
    """Pure interface for DB writer checkpoint state."""

    def save_checkpoint(self, checkpoint: DbWriterCheckpoint) -> None:
        """Persist a checkpoint if it advances the stream partition."""
        ...

    def get_checkpoint(
        self,
        stream_id: StreamId,
        partition_id: StreamPartitionId,
    ) -> DbWriterCheckpoint | None:
        """Return the latest checkpoint for a stream partition, or None."""
        ...


class StateStitcherPort(Protocol):
    """Pure interface for stitching historical DB state with live tail state."""

    def stitch(
        self,
        historical: HistoricalStateSlice,
        live_tail: LiveTailSlice | None,
        policy: LiveStateFreshnessPolicy,
    ) -> StitchedStateSlice:
        """Return a freshness-aware stitched state slice."""
        ...
