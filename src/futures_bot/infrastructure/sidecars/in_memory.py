"""In-memory sidecar health store for local tests and contract validation.

No DB. No filesystem. No Kafka. No process management.
"""
from __future__ import annotations

from futures_bot.domain.ids import SidecarId
from futures_bot.domain.sidecars import SidecarHealthSnapshot, SidecarKind


class InMemorySidecarHealthStore:
    """In-memory SidecarHealthStorePort implementation."""

    def __init__(self) -> None:
        self._snapshots: dict[str, SidecarHealthSnapshot] = {}

    def save(self, snapshot: SidecarHealthSnapshot) -> None:
        """Save latest snapshot, rejecting checked_at regressions."""
        key = str(snapshot.sidecar_id)
        existing = self._snapshots.get(key)
        if existing is not None and snapshot.checked_at < existing.checked_at:
            raise ValueError(
                "sidecar health checked_at regression: "
                f"existing {existing.checked_at.isoformat()}, "
                f"new {snapshot.checked_at.isoformat()}"
            )
        self._snapshots[key] = snapshot

    def latest(self, sidecar_id: SidecarId) -> SidecarHealthSnapshot | None:
        """Return latest snapshot for sidecar_id, or None."""
        return self._snapshots.get(str(sidecar_id))

    def list_all(self) -> tuple[SidecarHealthSnapshot, ...]:
        """Return all latest snapshots sorted by sidecar_id."""
        return tuple(
            self._snapshots[key] for key in sorted(self._snapshots)
        )

    def list_by_kind(
        self, sidecar_kind: SidecarKind
    ) -> tuple[SidecarHealthSnapshot, ...]:
        """Return latest snapshots of sidecar_kind sorted by sidecar_id."""
        return tuple(
            snapshot
            for snapshot in self.list_all()
            if snapshot.sidecar_kind is sidecar_kind
        )
