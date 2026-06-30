from __future__ import annotations

from futures_bot.domain.venue_capability_sources import (
    VenueCapabilityManualImport,
    VenueCapabilitySourceHealthStatus,
    VenueCapabilitySourceKind,
    VenueCapabilitySourceRecord,
    VenueCapabilitySourceRecordReason,
    VenueCapabilitySourceTrust,
)


def ensure_source_record_accepted_for_execution(
    record: VenueCapabilitySourceRecord,
) -> VenueCapabilitySourceRecord:
    """Return an accepted official source record or raise a deterministic error."""
    if not record.accepted_for_execution:
        raise ValueError("source record is not accepted for execution")
    if record.reason is not VenueCapabilitySourceRecordReason.ACCEPTED:
        raise ValueError("source record accepted_for_execution requires ACCEPTED reason")
    if record.descriptor.trust is not VenueCapabilitySourceTrust.OFFICIAL:
        raise ValueError("source record accepted_for_execution requires OFFICIAL trust")
    if record.descriptor.source_kind is VenueCapabilitySourceKind.UNKNOWN:
        raise ValueError("source record accepted_for_execution rejects UNKNOWN source_kind")
    if record.health_status is not VenueCapabilitySourceHealthStatus.HEALTHY:
        raise ValueError("source record accepted_for_execution requires HEALTHY status")
    return record


def validate_manual_official_import(
    manual_import: VenueCapabilityManualImport,
) -> VenueCapabilityManualImport:
    """Return a validated deterministic manual import contract."""
    ensure_source_record_accepted_for_execution(manual_import.source_record)
    return manual_import
