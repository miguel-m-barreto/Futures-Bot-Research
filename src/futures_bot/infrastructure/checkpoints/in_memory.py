"""In-memory checkpoint stores for tests and local contract validation.

No DB. No filesystem. No Kafka.
"""
from __future__ import annotations

from futures_bot.domain.broker import BrokerConsumerCursor
from futures_bot.domain.ids import BrokerTopicId, ConsumerId, RunId, SidecarId
from futures_bot.domain.sidecars import (
    DbWriterCheckpoint,
    RequiredConsumerCheckpointSet,
    SidecarCheckpoint,
    WalRelayCheckpoint,
)


class InMemoryWalRelayCheckpointStore:
    """In-memory WalRelayCheckpointStorePort implementation.

    Stores broker publish progress checkpoints only.  Entirely separate from
    any DB writer checkpoint store.  Not a GC authority.

    No DB code. No filesystem code. No Kafka code.
    """

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], WalRelayCheckpoint] = {}

    # ── WalRelayCheckpointStorePort ───────────────────────────────────────────

    def load(self, relay_id: SidecarId, run_id: RunId) -> WalRelayCheckpoint | None:
        """Return the checkpoint for (relay_id, run_id), or None if not found."""
        return self._data.get((str(relay_id), str(run_id)))

    def save(self, checkpoint: WalRelayCheckpoint) -> None:
        """Persist a relay checkpoint, overwriting any existing entry."""
        self._data[(str(checkpoint.relay_id), str(checkpoint.run_id))] = checkpoint


class InMemoryDbWriterCheckpointStore:
    """In-memory DbWriterCheckpointStorePort implementation.

    Enforces monotonic last_committed_wal_offset per (consumer_id, run_id).
    Idempotent for same offset + same event_id.  Rejects lower offsets and
    conflicting event_ids at the same offset.

    No DB code. No filesystem code. No Kafka code.
    No WalRelayCheckpoint methods.
    """

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], DbWriterCheckpoint] = {}

    # ── DbWriterCheckpointStorePort ───────────────────────────────────────────

    def load(
        self, consumer_id: ConsumerId, run_id: RunId
    ) -> DbWriterCheckpoint | None:
        """Return the DB writer checkpoint for the given consumer and run, or None."""
        return self._data.get((str(consumer_id), str(run_id)))

    def save(self, checkpoint: DbWriterCheckpoint) -> None:
        """Persist a DB writer checkpoint; enforces monotonic offset invariant.

        Raises ValueError if the new offset is lower than the existing offset,
        or if the same offset maps to a different last_committed_event_id.
        """
        key = (str(checkpoint.consumer_id), str(checkpoint.run_id))
        existing = self._data.get(key)
        if existing is not None:
            new_off = checkpoint.last_committed_wal_offset.value
            old_off = existing.last_committed_wal_offset.value
            if new_off < old_off:
                raise ValueError(
                    f"checkpoint offset regression: existing {old_off}, new {new_off}"
                )
            if new_off == old_off:
                if checkpoint.last_committed_event_id != existing.last_committed_event_id:
                    raise ValueError(
                        f"checkpoint conflict at offset {new_off}: "
                        f"existing event_id {existing.last_committed_event_id!s}, "
                        f"new event_id {checkpoint.last_committed_event_id!s}"
                    )
                return  # idempotent: same offset, same event_id
        self._data[key] = checkpoint


class InMemoryBrokerConsumerCursorStore:
    """In-memory BrokerConsumerCursorStorePort implementation.

    Stores broker-consumer resume progress by consumer/topic/partition. This
    is not a WAL GC authority and intentionally exposes no relay, DB writer, or
    sidecar checkpoint methods.

    No DB code. No filesystem code. No Kafka code.
    """

    def __init__(self) -> None:
        self._data: dict[tuple[str, str, int], BrokerConsumerCursor] = {}

    def load(
        self, consumer_id: ConsumerId, topic: BrokerTopicId, partition: int
    ) -> BrokerConsumerCursor | None:
        """Return the cursor for consumer/topic/partition, or None if absent."""
        return self._data.get((str(consumer_id), str(topic), partition))

    def save(self, cursor: BrokerConsumerCursor) -> None:
        """Persist cursor progress with per-key monotonic broker offset."""
        if not isinstance(cursor, BrokerConsumerCursor):
            raise TypeError("save requires a BrokerConsumerCursor")

        key = (
            str(cursor.consumer_id),
            str(cursor.kafka_offset.topic),
            cursor.kafka_offset.partition,
        )
        existing = self._data.get(key)
        if existing is not None:
            new_offset = cursor.kafka_offset.offset
            old_offset = existing.kafka_offset.offset
            if new_offset < old_offset:
                raise ValueError(
                    f"broker cursor offset regression: existing {old_offset}, "
                    f"new {new_offset}"
                )
            if new_offset == old_offset:
                self._validate_same_cursor_metadata(existing, cursor)
                return
        self._data[key] = cursor

    @staticmethod
    def _validate_same_cursor_metadata(
        existing: BrokerConsumerCursor, new: BrokerConsumerCursor
    ) -> None:
        if (
            existing.last_committed_run_id != new.last_committed_run_id
            or existing.last_committed_wal_offset != new.last_committed_wal_offset
            or existing.last_committed_event_id != new.last_committed_event_id
        ):
            raise ValueError(
                "broker cursor conflict at same offset: run_id, wal_offset, "
                "or event_id mismatch"
            )


class InMemoryRequiredConsumerCheckpointStore:
    """In-memory RequiredConsumerCheckpointStorePort implementation.

    Holds SidecarCheckpoint records; load_required_checkpoints returns a
    RequiredConsumerCheckpointSet filtered by run_id.  The set's
    required_checkpoints() method then returns only those with
    is_required_for_wal_gc=True.

    Optional upsert() enforces monotonic offsets per (sidecar_id, run_id).
    Optional replace() atomically replaces the entire checkpoint set.

    No DB code. No filesystem code. No Kafka code.
    No WalRelayCheckpoint support. No DbWriterCheckpoint support.
    """

    def __init__(self, checkpoints: tuple[SidecarCheckpoint, ...] = ()) -> None:
        self._data: dict[tuple[str, str], SidecarCheckpoint] = {}
        for cp in checkpoints:
            self._data[(str(cp.sidecar_id), str(cp.run_id))] = cp

    # ── RequiredConsumerCheckpointStorePort ───────────────────────────────────

    def load_required_checkpoints(self, run_id: RunId) -> RequiredConsumerCheckpointSet:
        """Return all checkpoints for run_id wrapped in a RequiredConsumerCheckpointSet."""
        matching = tuple(
            cp for cp in self._data.values()
            if str(cp.run_id) == str(run_id)
        )
        return RequiredConsumerCheckpointSet(run_id=run_id, checkpoints=matching)

    # ── optional helpers ──────────────────────────────────────────────────────

    def replace(self, checkpoints: tuple[SidecarCheckpoint, ...]) -> None:
        """Replace the entire checkpoint set atomically."""
        self._data = {(str(cp.sidecar_id), str(cp.run_id)): cp for cp in checkpoints}

    def upsert(self, checkpoint: SidecarCheckpoint) -> None:
        """Insert or update one checkpoint; enforces monotonic offset invariant.

        Raises ValueError if the new offset is lower than the existing, or if
        the same offset has a different sidecar_kind or is_required_for_wal_gc.
        """
        key = (str(checkpoint.sidecar_id), str(checkpoint.run_id))
        existing = self._data.get(key)
        if existing is not None:
            new_off = checkpoint.last_committed_wal_offset.value
            old_off = existing.last_committed_wal_offset.value
            if new_off < old_off:
                raise ValueError(
                    f"checkpoint offset regression: existing {old_off}, new {new_off}"
                )
            if new_off == old_off and (
                checkpoint.sidecar_kind != existing.sidecar_kind
                or checkpoint.is_required_for_wal_gc != existing.is_required_for_wal_gc
            ):
                raise ValueError(
                    f"checkpoint conflict at offset {new_off}: "
                    "sidecar_kind or is_required_for_wal_gc mismatch"
                )
        self._data[key] = checkpoint
