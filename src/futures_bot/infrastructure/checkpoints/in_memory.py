"""In-memory checkpoint store for tests and local contract validation.

No DB. No filesystem. No Kafka.
"""
from __future__ import annotations

from futures_bot.domain.ids import RunId, SidecarId
from futures_bot.domain.sidecars import WalRelayCheckpoint


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
