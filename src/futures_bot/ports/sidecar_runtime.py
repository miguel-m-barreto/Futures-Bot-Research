from __future__ import annotations

from typing import Protocol

from futures_bot.domain.ids import SidecarId
from futures_bot.domain.sidecars import SidecarHealthSnapshot, SidecarKind


class SidecarHealthStorePort(Protocol):
    """Observability-only sidecar health snapshot store."""

    def save(self, snapshot: SidecarHealthSnapshot) -> None:
        """Persist the latest health snapshot for a sidecar."""
        ...

    def latest(self, sidecar_id: SidecarId) -> SidecarHealthSnapshot | None:
        """Return the latest snapshot for sidecar_id, or None."""
        ...

    def list_all(self) -> tuple[SidecarHealthSnapshot, ...]:
        """Return latest snapshots for all sidecars."""
        ...

    def list_by_kind(
        self, sidecar_kind: SidecarKind
    ) -> tuple[SidecarHealthSnapshot, ...]:
        """Return latest snapshots for sidecars of the requested kind."""
        ...
