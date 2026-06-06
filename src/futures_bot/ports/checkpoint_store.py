from __future__ import annotations

from typing import Protocol

from futures_bot.domain.ids import ConsumerId, RunId, SidecarId
from futures_bot.domain.sidecars import (
    DbWriterCheckpoint,
    RequiredConsumerCheckpointSet,
    SidecarCheckpoint,
    WalRelayCheckpoint,
)


class WalRelayCheckpointStorePort(Protocol):
    """Persistence contract for WAL relay (broker publish) progress checkpoints.

    This store is NOT a GC authority.  WAL GC eligibility is determined by
    RequiredConsumerCheckpointStorePort, not by relay checkpoint progress.
    WAL_RELAY checkpoints record broker-side delivery progress only.
    """

    def load(
        self, relay_id: SidecarId, run_id: RunId
    ) -> WalRelayCheckpoint | None:
        """Return the relay checkpoint for the given relay and run, or None."""
        ...

    def save(self, checkpoint: WalRelayCheckpoint) -> None:
        """Persist a relay checkpoint."""
        ...


class DbWriterCheckpointStorePort(Protocol):
    """Persistence contract for DB writer commit progress checkpoints.

    DB writer checkpoints record durable DB commit progress.  They are written
    in the same DB transaction as event ingestion and are the canonical source
    for WAL GC eligibility via RequiredConsumerCheckpointSet.
    """

    def load(
        self, consumer_id: ConsumerId, run_id: RunId
    ) -> DbWriterCheckpoint | None:
        """Return the DB writer checkpoint for the given consumer and run, or None."""
        ...

    def save(self, checkpoint: DbWriterCheckpoint) -> None:
        """Persist a DB writer checkpoint."""
        ...


class RequiredConsumerCheckpointStorePort(Protocol):
    """Source of truth for required consumer checkpoints consumed by GC logic.

    WAL GC depends on this store, not on WalRelayCheckpointStorePort.
    WAL_RELAY cannot appear as a required checkpoint — the SidecarCheckpoint
    model validator enforces this by construction.
    """

    def load_required_checkpoints(
        self, run_id: RunId
    ) -> RequiredConsumerCheckpointSet:
        """Return the full required-consumer checkpoint set for the given run."""
        ...


class RequiredConsumerCheckpointWriterPort(Protocol):
    """Write-side contract for required-consumer checkpoint progress.

    Stores SidecarCheckpoint records because RequiredConsumerCheckpointSet is
    the GC authority input.  This port intentionally does not expose
    WalRelayCheckpoint or DbWriterCheckpoint.
    """

    def upsert(self, checkpoint: SidecarCheckpoint) -> None:
        """Insert or advance one required-consumer checkpoint."""
        ...
