from __future__ import annotations

from typing import Protocol

from futures_bot.domain.ids import (
    VenueCapabilitySourceId,
    VenueCapabilitySourceImportId,
    VenueCapabilitySourceRecordId,
)
from futures_bot.domain.venue_capability_sources import (
    VenueCapabilityManualImport,
    VenueCapabilityManualImportDecision,
    VenueCapabilityManualImportRequest,
    VenueCapabilitySourceDescriptor,
    VenueCapabilitySourceRecord,
)


class VenueCapabilitySourceDescriptorStorePort(Protocol):
    """Pure source descriptor store interface."""

    def put(self, descriptor: VenueCapabilitySourceDescriptor) -> None:
        """Store a source descriptor idempotently."""
        ...

    def get(
        self,
        source_id: VenueCapabilitySourceId,
    ) -> VenueCapabilitySourceDescriptor | None:
        """Return a source descriptor by ID."""
        ...

    def list_by_venue_id(
        self,
        venue_id: str,
    ) -> tuple[VenueCapabilitySourceDescriptor, ...]:
        """Return source descriptors for a venue in deterministic order."""
        ...


class VenueCapabilitySourceRecordStorePort(Protocol):
    """Pure captured source record store interface."""

    def put(self, record: VenueCapabilitySourceRecord) -> None:
        """Store a source record idempotently."""
        ...

    def get(
        self,
        record_id: VenueCapabilitySourceRecordId,
    ) -> VenueCapabilitySourceRecord | None:
        """Return a source record by ID."""
        ...

    def list_by_venue_id(
        self,
        venue_id: str,
    ) -> tuple[VenueCapabilitySourceRecord, ...]:
        """Return source records for a venue in deterministic order."""
        ...

    def get_latest_accepted(
        self,
        venue_id: str,
    ) -> VenueCapabilitySourceRecord | None:
        """Return the latest accepted source record for a venue."""
        ...


class VenueCapabilityManualImportStorePort(Protocol):
    """Pure manual official import store interface."""

    def put(self, manual_import: VenueCapabilityManualImport) -> None:
        """Store a manual official import idempotently."""
        ...

    def get(
        self,
        import_id: VenueCapabilitySourceImportId,
    ) -> VenueCapabilityManualImport | None:
        """Return a manual official import by ID."""
        ...

    def list_by_venue_id(
        self,
        venue_id: str,
    ) -> tuple[VenueCapabilityManualImport, ...]:
        """Return manual imports for a venue in deterministic order."""
        ...


class VenueCapabilityManualImportGatewayPort(Protocol):
    """Pure gateway for deterministic manual official capability imports."""

    def import_capabilities(
        self,
        request: VenueCapabilityManualImportRequest,
    ) -> VenueCapabilityManualImportDecision:
        """Import source-backed capability snapshots into resolution stores."""
        ...
