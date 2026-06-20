from __future__ import annotations

from itertools import pairwise

from futures_bot.domain.ids import (
    HistoricalStateSliceId,
    LiveStateSnapshotId,
    StreamId,
    StreamPartitionId,
)
from futures_bot.domain.live_state import (
    DbWriterCheckpoint,
    HistoricalStateSlice,
    LiveStateSnapshot,
    StreamEventEnvelope,
    StreamPosition,
)


class InMemoryLiveStateGateway:
    """Deterministic live-state gateway test double."""

    def __init__(self) -> None:
        self._snapshots: dict[str, LiveStateSnapshot] = {}

    def put_snapshot(self, snapshot: LiveStateSnapshot) -> None:
        key = str(snapshot.snapshot_id)
        existing = self._snapshots.get(key)
        snapshot.validate_can_replace(existing)
        if existing is not None and snapshot == existing:
            return
        self._snapshots[key] = snapshot

    def get_snapshot(
        self,
        snapshot_id: LiveStateSnapshotId,
    ) -> LiveStateSnapshot | None:
        return self._snapshots.get(str(snapshot_id))


class InMemoryDbWriterCheckpointStore:
    """Forward-only DB writer checkpoint test double."""

    def __init__(self) -> None:
        self._checkpoints: dict[tuple[str, str], DbWriterCheckpoint] = {}

    def save_checkpoint(self, checkpoint: DbWriterCheckpoint) -> None:
        key = (str(checkpoint.stream_id), str(checkpoint.partition_id))
        existing = self._checkpoints.get(key)
        checkpoint.validate_advances_from(existing)
        self._checkpoints[key] = checkpoint

    def get_checkpoint(
        self,
        stream_id: StreamId,
        partition_id: StreamPartitionId,
    ) -> DbWriterCheckpoint | None:
        return self._checkpoints.get((str(stream_id), str(partition_id)))


class InMemoryHistoricalStateReader:
    """Deterministic historical reader over supplied in-memory events."""

    def __init__(
        self,
        *,
        slice_id: HistoricalStateSliceId,
        events: tuple[StreamEventEnvelope, ...],
        empty_slice_position: StreamPosition | None = None,
    ) -> None:
        self._slice_id = slice_id
        self._empty_slice_position = empty_slice_position
        self._events = tuple(
            sorted(
                events,
                key=lambda event: (
                    str(event.stream_position.stream_id),
                    str(event.stream_position.partition_id),
                    event.stream_position.offset,
                    event.stream_position.event_sequence,
                ),
            )
        )

    def read_slice(
        self,
        stream_id: StreamId,
        partition_id: StreamPartitionId,
        from_offset: int,
        to_offset: int,
    ) -> HistoricalStateSlice:
        if from_offset < 0 or to_offset < 0:
            raise ValueError("slice offsets must be >= 0")
        if from_offset > to_offset:
            raise ValueError("from_offset must be <= to_offset")
        events = tuple(
            event
            for event in self._events
            if event.stream_position.stream_id == stream_id
            and event.stream_position.partition_id == partition_id
            and from_offset <= event.stream_position.offset <= to_offset
        )
        if events:
            persisted_until_position = events[-1].stream_position
        else:
            if self._empty_slice_position is None:
                raise ValueError(
                    "empty historical slice requires explicit empty_slice_position"
                )
            if (
                self._empty_slice_position.stream_id != stream_id
                or self._empty_slice_position.partition_id != partition_id
            ):
                raise ValueError("empty_slice_position stream/partition mismatch")
            persisted_until_position = self._empty_slice_position
        return HistoricalStateSlice(
            slice_id=self._slice_id,
            stream_id=stream_id,
            partition_id=partition_id,
            from_offset=from_offset,
            to_offset=events[-1].stream_position.offset if events else to_offset,
            events=events,
            persisted_until_position=persisted_until_position,
            is_gap_free=_is_gap_free(events),
        )


def _is_gap_free(events: tuple[StreamEventEnvelope, ...]) -> bool:
    return all(
        current.stream_position.is_contiguous_after(previous.stream_position)
        for previous, current in pairwise(events)
    )
