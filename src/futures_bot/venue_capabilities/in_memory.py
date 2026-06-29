from __future__ import annotations

from futures_bot.domain.ids import VenueCapabilityFreshnessDecisionId
from futures_bot.domain.venue_capabilities import (
    VenueCapabilitySnapshot,
    VenueInstrumentRuleSnapshot,
)
from futures_bot.domain.venue_capability_freshness import VenueCapabilityFreshnessDecision


class InMemoryVenueCapabilitySnapshotStore:
    """Deterministic venue capability snapshot store test double."""

    def __init__(self) -> None:
        self._snapshots_by_id: dict[str, VenueCapabilitySnapshot] = {}
        self._snapshot_ids_by_venue: dict[str, set[str]] = {}

    def put(self, snapshot: VenueCapabilitySnapshot) -> None:
        key = str(snapshot.snapshot_id)
        existing = self._snapshots_by_id.get(key)
        if existing is not None:
            if existing != snapshot:
                raise ValueError("venue capability snapshot id collision")
            return
        self._snapshots_by_id[key] = snapshot
        self._snapshot_ids_by_venue.setdefault(snapshot.venue_id, set()).add(key)

    def get_latest(self, venue_id: str) -> VenueCapabilitySnapshot | None:
        snapshot_ids = self._snapshot_ids_by_venue.get(venue_id, set())
        snapshots = tuple(self._snapshots_by_id[snapshot_id] for snapshot_id in snapshot_ids)
        if not snapshots:
            return None
        return max(snapshots, key=lambda item: (item.captured_at, str(item.snapshot_id)))


class InMemoryVenueInstrumentRuleSnapshotStore:
    """Deterministic venue/instrument rule snapshot store test double."""

    def __init__(self) -> None:
        self._snapshots_by_id: dict[str, VenueInstrumentRuleSnapshot] = {}
        self._snapshot_ids_by_scope: dict[tuple[str, str], set[str]] = {}

    def put(self, snapshot: VenueInstrumentRuleSnapshot) -> None:
        key = str(snapshot.snapshot_id)
        existing = self._snapshots_by_id.get(key)
        if existing is not None:
            if existing != snapshot:
                raise ValueError("venue instrument rule snapshot id collision")
            return
        self._snapshots_by_id[key] = snapshot
        scope = (snapshot.venue_id, snapshot.instrument_id)
        self._snapshot_ids_by_scope.setdefault(scope, set()).add(key)

    def get_latest(
        self,
        venue_id: str,
        instrument_id: str,
    ) -> VenueInstrumentRuleSnapshot | None:
        snapshot_ids = self._snapshot_ids_by_scope.get((venue_id, instrument_id), set())
        snapshots = tuple(self._snapshots_by_id[snapshot_id] for snapshot_id in snapshot_ids)
        if not snapshots:
            return None
        return max(snapshots, key=lambda item: (item.captured_at, str(item.snapshot_id)))


class InMemoryVenueCapabilityFreshnessDecisionStore:
    """Deterministic idempotent freshness decision store test double."""

    def __init__(self) -> None:
        self._decisions_by_id: dict[str, VenueCapabilityFreshnessDecision] = {}
        self._append_order: list[str] = []

    def put(self, decision: VenueCapabilityFreshnessDecision) -> None:
        key = str(decision.decision_id)
        existing = self._decisions_by_id.get(key)
        if existing is not None:
            if existing != decision:
                raise ValueError("venue capability freshness decision id collision")
            return
        self._decisions_by_id[key] = decision
        self._append_order.append(key)

    def get(
        self,
        decision_id: VenueCapabilityFreshnessDecisionId,
    ) -> VenueCapabilityFreshnessDecision | None:
        return self._decisions_by_id.get(str(decision_id))

    def list_decisions(self) -> tuple[VenueCapabilityFreshnessDecision, ...]:
        return tuple(self._decisions_by_id[key] for key in self._append_order)
