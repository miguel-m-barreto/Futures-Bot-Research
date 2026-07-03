from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tests.unit.capability_freshness_fixtures import rules, venue

from futures_bot.domain.ids import (
    VenueCapabilitySnapshotId,
    VenueInstrumentRuleSnapshotId,
)
from futures_bot.domain.venue_capability_sources import (
    VenueCapabilityManualImport,
    VenueCapabilitySourceDescriptor,
    VenueCapabilitySourceFetchMode,
    VenueCapabilitySourceHealthStatus,
    VenueCapabilitySourceKind,
    VenueCapabilitySourcePayload,
    VenueCapabilitySourceRecord,
    VenueCapabilitySourceRecordReason,
    VenueCapabilitySourceTrust,
)
from futures_bot.venue_capabilities.in_memory import (
    InMemoryVenueCapabilityManualImportStore,
    InMemoryVenueCapabilitySnapshotStore,
    InMemoryVenueCapabilitySourceDescriptorStore,
    InMemoryVenueCapabilitySourceRecordStore,
    InMemoryVenueInstrumentRuleSnapshotStore,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _descriptor(
    *,
    venue_id: str = "venue-1",
    reference_name: str = "Official export",
    created_at: datetime = NOW,
) -> VenueCapabilitySourceDescriptor:
    return VenueCapabilitySourceDescriptor(
        venue_id=venue_id,
        source_kind=VenueCapabilitySourceKind.OFFICIAL_EXCHANGE_EXPORT,
        trust=VenueCapabilitySourceTrust.OFFICIAL,
        fetch_mode=VenueCapabilitySourceFetchMode.MANUAL,
        reference_name=reference_name,
        created_at=created_at,
        metadata={},
    )


def _payload(version: int = 1) -> VenueCapabilitySourcePayload:
    return VenueCapabilitySourcePayload(
        canonical_payload={"version": version},
        content_type="application/json",
        captured_at=NOW,
        observed_at=NOW,
    )


def _record(
    *,
    descriptor: VenueCapabilitySourceDescriptor | None = None,
    payload: VenueCapabilitySourcePayload | None = None,
    recorded_at: datetime = NOW,
    accepted_for_execution: bool = True,
) -> VenueCapabilitySourceRecord:
    return VenueCapabilitySourceRecord(
        descriptor=descriptor or _descriptor(),
        payload=payload or _payload(),
        health_status=VenueCapabilitySourceHealthStatus.HEALTHY,
        reason=(
            VenueCapabilitySourceRecordReason.ACCEPTED
            if accepted_for_execution
            else VenueCapabilitySourceRecordReason.REJECTED_UNTRUSTED
        ),
        accepted_for_execution=accepted_for_execution,
        recorded_at=recorded_at,
        details={},
    )


def _manual_import(
    *,
    source_record: VenueCapabilitySourceRecord | None = None,
    imported_at: datetime = NOW,
    imported_by: str = "operator",
) -> VenueCapabilityManualImport:
    return VenueCapabilityManualImport(
        source_record=source_record or _record(),
        imported_at=imported_at,
        imported_by=imported_by,
        details={},
    )


def test_source_descriptor_store_idempotent_same_payload() -> None:
    store = InMemoryVenueCapabilitySourceDescriptorStore()
    descriptor = _descriptor()

    store.put(descriptor)
    store.put(descriptor)

    assert descriptor.source_id is not None
    assert store.get(descriptor.source_id) == descriptor


def test_source_descriptor_store_rejects_same_id_different_payload() -> None:
    store = InMemoryVenueCapabilitySourceDescriptorStore()
    descriptor = _descriptor()
    changed = descriptor.model_copy(update={"reference_name": "Changed name"})

    store.put(descriptor)
    with pytest.raises(ValueError, match="source descriptor"):
        store.put(changed)


def test_source_record_store_idempotent_same_payload() -> None:
    store = InMemoryVenueCapabilitySourceRecordStore()
    record = _record()

    store.put(record)
    store.put(record)

    assert record.record_id is not None
    assert store.get(record.record_id) == record


def test_source_record_store_rejects_same_id_different_payload() -> None:
    store = InMemoryVenueCapabilitySourceRecordStore()
    record = _record()
    changed = record.model_copy(update={"details": {"changed": True}})

    store.put(record)
    with pytest.raises(ValueError, match="source record"):
        store.put(changed)


def test_source_record_latest_accepted_by_recorded_at() -> None:
    store = InMemoryVenueCapabilitySourceRecordStore()
    older = _record(recorded_at=NOW)
    newer = _record(
        payload=_payload(version=2),
        recorded_at=NOW + timedelta(minutes=1),
    )

    store.put(newer)
    store.put(older)

    assert store.get_latest_accepted("venue-1") == newer


def test_source_record_latest_tie_broken_by_record_id() -> None:
    store = InMemoryVenueCapabilitySourceRecordStore()
    left = _record(payload=_payload(version=1))
    right = _record(payload=_payload(version=2))

    store.put(left)
    store.put(right)

    latest = max((left, right), key=lambda item: str(item.record_id))
    assert store.get_latest_accepted("venue-1") == latest


def test_manual_import_store_idempotent_same_payload() -> None:
    store = InMemoryVenueCapabilityManualImportStore()
    manual_import = _manual_import()

    store.put(manual_import)
    store.put(manual_import)

    assert manual_import.import_id is not None
    assert store.get(manual_import.import_id) == manual_import


def test_manual_import_store_rejects_same_id_different_payload() -> None:
    store = InMemoryVenueCapabilityManualImportStore()
    manual_import = _manual_import()
    changed = manual_import.model_copy(update={"imported_by": "reviewer"})

    store.put(manual_import)
    with pytest.raises(ValueError, match="manual import"):
        store.put(changed)


def test_snapshot_stores_get_by_id_for_preflight() -> None:
    venue_store = InMemoryVenueCapabilitySnapshotStore()
    rule_store = InMemoryVenueInstrumentRuleSnapshotStore()
    venue_snapshot = venue(snapshot_id=VenueCapabilitySnapshotId(value="venue-cap-50"))
    rule_snapshot = rules(snapshot_id=VenueInstrumentRuleSnapshotId(value="rules-50"))

    venue_store.put(venue_snapshot)
    rule_store.put(rule_snapshot)

    assert venue_store.get(venue_snapshot.snapshot_id) == venue_snapshot
    assert rule_store.get(rule_snapshot.snapshot_id) == rule_snapshot


def test_list_by_venue_id_is_deterministic_for_descriptors_records_and_imports() -> None:
    descriptor_store = InMemoryVenueCapabilitySourceDescriptorStore()
    record_store = InMemoryVenueCapabilitySourceRecordStore()
    import_store = InMemoryVenueCapabilityManualImportStore()
    older_descriptor = _descriptor(created_at=NOW)
    newer_descriptor = _descriptor(
        reference_name="Official export v2",
        created_at=NOW + timedelta(minutes=1),
    )
    other_descriptor = _descriptor(venue_id="venue-2")
    older_record = _record(descriptor=older_descriptor, recorded_at=NOW)
    newer_record = _record(
        descriptor=newer_descriptor,
        payload=_payload(version=2),
        recorded_at=NOW + timedelta(minutes=1),
    )
    older_import = _manual_import(source_record=older_record, imported_at=NOW)
    newer_import = _manual_import(
        source_record=newer_record,
        imported_at=NOW + timedelta(minutes=1),
    )

    descriptor_store.put(newer_descriptor)
    descriptor_store.put(other_descriptor)
    descriptor_store.put(older_descriptor)
    record_store.put(newer_record)
    record_store.put(older_record)
    import_store.put(newer_import)
    import_store.put(older_import)

    assert descriptor_store.list_by_venue_id("venue-1") == (
        older_descriptor,
        newer_descriptor,
    )
    assert record_store.list_by_venue_id("venue-1") == (older_record, newer_record)
    assert import_store.list_by_venue_id("venue-1") == (older_import, newer_import)
