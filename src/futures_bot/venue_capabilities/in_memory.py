from __future__ import annotations

from futures_bot.domain.ids import (
    VenueCapabilityFreshnessDecisionId,
    VenueCapabilitySourceId,
    VenueCapabilitySourceImportId,
    VenueCapabilitySourceRecordId,
)
from futures_bot.domain.venue_capabilities import (
    VenueCapabilitySnapshot,
    VenueInstrumentRuleSnapshot,
)
from futures_bot.domain.venue_capability_freshness import VenueCapabilityFreshnessDecision
from futures_bot.domain.venue_capability_sources import (
    VenueCapabilityManualImport,
    VenueCapabilitySourceDescriptor,
    VenueCapabilitySourceRecord,
)


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


class InMemoryVenueCapabilitySourceDescriptorStore:
    """Deterministic source descriptor store test double."""

    def __init__(self) -> None:
        self._descriptors_by_id: dict[str, VenueCapabilitySourceDescriptor] = {}
        self._descriptor_ids_by_venue: dict[str, set[str]] = {}

    def put(self, descriptor: VenueCapabilitySourceDescriptor) -> None:
        if descriptor.source_id is None:
            raise ValueError("source descriptor must have source_id")
        key = str(descriptor.source_id)
        existing = self._descriptors_by_id.get(key)
        if existing is not None:
            if existing != descriptor:
                raise ValueError("venue capability source descriptor id collision")
            return
        self._descriptors_by_id[key] = descriptor
        self._descriptor_ids_by_venue.setdefault(descriptor.venue_id, set()).add(key)

    def get(
        self,
        source_id: VenueCapabilitySourceId,
    ) -> VenueCapabilitySourceDescriptor | None:
        return self._descriptors_by_id.get(str(source_id))

    def list_by_venue_id(
        self,
        venue_id: str,
    ) -> tuple[VenueCapabilitySourceDescriptor, ...]:
        source_ids = self._descriptor_ids_by_venue.get(venue_id, set())
        descriptors = tuple(self._descriptors_by_id[source_id] for source_id in source_ids)
        return tuple(
            sorted(descriptors, key=lambda item: (item.created_at, str(item.source_id)))
        )


class InMemoryVenueCapabilitySourceRecordStore:
    """Deterministic captured source record store test double."""

    def __init__(self) -> None:
        self._records_by_id: dict[str, VenueCapabilitySourceRecord] = {}
        self._record_ids_by_venue: dict[str, set[str]] = {}

    def put(self, record: VenueCapabilitySourceRecord) -> None:
        if record.record_id is None:
            raise ValueError("source record must have record_id")
        key = str(record.record_id)
        existing = self._records_by_id.get(key)
        if existing is not None:
            if existing != record:
                raise ValueError("venue capability source record id collision")
            return
        self._records_by_id[key] = record
        self._record_ids_by_venue.setdefault(record.descriptor.venue_id, set()).add(key)

    def get(
        self,
        record_id: VenueCapabilitySourceRecordId,
    ) -> VenueCapabilitySourceRecord | None:
        return self._records_by_id.get(str(record_id))

    def list_by_venue_id(
        self,
        venue_id: str,
    ) -> tuple[VenueCapabilitySourceRecord, ...]:
        record_ids = self._record_ids_by_venue.get(venue_id, set())
        records = tuple(self._records_by_id[record_id] for record_id in record_ids)
        return tuple(
            sorted(records, key=lambda item: (item.recorded_at, str(item.record_id)))
        )

    def get_latest_accepted(
        self,
        venue_id: str,
    ) -> VenueCapabilitySourceRecord | None:
        records = tuple(
            record
            for record in self.list_by_venue_id(venue_id)
            if record.accepted_for_execution
        )
        if not records:
            return None
        return max(records, key=lambda item: (item.recorded_at, str(item.record_id)))


class InMemoryVenueCapabilityManualImportStore:
    """Deterministic manual official import store test double."""

    def __init__(self) -> None:
        self._imports_by_id: dict[str, VenueCapabilityManualImport] = {}
        self._import_ids_by_venue: dict[str, set[str]] = {}

    def put(self, manual_import: VenueCapabilityManualImport) -> None:
        if manual_import.import_id is None:
            raise ValueError("manual import must have import_id")
        key = str(manual_import.import_id)
        existing = self._imports_by_id.get(key)
        if existing is not None:
            if existing != manual_import:
                raise ValueError("venue capability manual import id collision")
            return
        self._imports_by_id[key] = manual_import
        venue_id = manual_import.source_record.descriptor.venue_id
        self._import_ids_by_venue.setdefault(venue_id, set()).add(key)

    def get(
        self,
        import_id: VenueCapabilitySourceImportId,
    ) -> VenueCapabilityManualImport | None:
        return self._imports_by_id.get(str(import_id))

    def list_by_venue_id(
        self,
        venue_id: str,
    ) -> tuple[VenueCapabilityManualImport, ...]:
        import_ids = self._import_ids_by_venue.get(venue_id, set())
        imports = tuple(self._imports_by_id[import_id] for import_id in import_ids)
        return tuple(
            sorted(imports, key=lambda item: (item.imported_at, str(item.import_id)))
        )
