from __future__ import annotations

from typing import Protocol

from futures_bot.domain.venue_registry import (
    VenueDescriptor,
    VenueOperatingEnvironment,
    VenueProductDescriptor,
    VenueProductFamily,
    VenueSourceTemplate,
    VenueSupportStatus,
)


class VenueDescriptorRegistryPort(Protocol):
    """Read-only deterministic venue descriptor registry interface."""

    def get(self, venue_id: str) -> VenueDescriptor | None:
        """Return a venue descriptor by case-insensitive venue ID."""
        ...

    def require(self, venue_id: str) -> VenueDescriptor:
        """Return a venue descriptor or raise a deterministic not-found error."""
        ...

    def list_all(self) -> tuple[VenueDescriptor, ...]:
        """Return all descriptors in deterministic order."""
        ...

    def list_by_support_status(
        self,
        support_status: VenueSupportStatus,
    ) -> tuple[VenueDescriptor, ...]:
        """Return descriptors with a matching registry support status."""
        ...

    def list_by_environment(
        self,
        environment: VenueOperatingEnvironment,
    ) -> tuple[VenueDescriptor, ...]:
        """Return descriptors that model the requested environment."""
        ...

    def list_product_descriptors(
        self,
        venue_id: str,
        *,
        environment: VenueOperatingEnvironment | None = None,
        product_family: VenueProductFamily | None = None,
    ) -> tuple[VenueProductDescriptor, ...]:
        """Return product descriptors matching a venue and optional filters."""
        ...

    def list_source_templates(
        self,
        venue_id: str,
        *,
        environment: VenueOperatingEnvironment | None = None,
        product_family: VenueProductFamily | None = None,
    ) -> tuple[VenueSourceTemplate, ...]:
        """Return source templates matching a venue and optional filters."""
        ...
