from __future__ import annotations

from typing import Protocol

from futures_bot.domain.ids import (
    VenueCapabilitySnapshotId,
    VenueInstrumentRuleSnapshotId,
)
from futures_bot.domain.venue_capabilities import (
    VenueCapabilitySnapshot,
    VenueInstrumentRuleSnapshot,
    VenueOrderValidationContext,
    VenueOrderValidationResult,
)


class VenueCapabilitySnapshotStorePort(Protocol):
    """Pure venue capability snapshot store interface."""

    def put(self, snapshot: VenueCapabilitySnapshot) -> None:
        """Store a venue capability snapshot idempotently."""
        ...

    def get(
        self,
        snapshot_id: VenueCapabilitySnapshotId,
    ) -> VenueCapabilitySnapshot | None:
        """Return a venue capability snapshot by ID."""
        ...

    def get_latest(self, venue_id: str) -> VenueCapabilitySnapshot | None:
        """Return the latest venue capability snapshot for a venue."""
        ...


class VenueInstrumentRuleSnapshotStorePort(Protocol):
    """Pure instrument rule snapshot store interface."""

    def put(self, snapshot: VenueInstrumentRuleSnapshot) -> None:
        """Store an instrument rule snapshot idempotently."""
        ...

    def get(
        self,
        snapshot_id: VenueInstrumentRuleSnapshotId,
    ) -> VenueInstrumentRuleSnapshot | None:
        """Return an instrument rule snapshot by ID."""
        ...

    def get_latest(
        self,
        venue_id: str,
        instrument_id: str,
    ) -> VenueInstrumentRuleSnapshot | None:
        """Return the latest instrument rule snapshot for a venue/instrument."""
        ...


class VenueOrderCapabilityValidatorPort(Protocol):
    """Pure order executability validator interface."""

    def validate_order_against_venue_capabilities(
        self,
        context: VenueOrderValidationContext,
    ) -> VenueOrderValidationResult:
        """Validate hard execution capability constraints for an order."""
        ...
