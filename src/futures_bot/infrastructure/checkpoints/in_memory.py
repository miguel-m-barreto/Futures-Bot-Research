"""In-memory checkpoint stores for tests and local contract validation.

No DB. No filesystem. No Kafka.
"""
from __future__ import annotations

from futures_bot.domain.ids import ConsumerId, RunId, SidecarId
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
