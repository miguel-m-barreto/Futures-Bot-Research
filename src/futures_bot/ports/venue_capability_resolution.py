from __future__ import annotations

from typing import Protocol

from futures_bot.domain.venue_capability_resolution import (
    VenueCapabilityResolutionDecision,
    VenueCapabilityResolutionRequest,
)


class VenueCapabilityResolutionGatewayPort(Protocol):
    """Pure interface for deterministic capability snapshot resolution."""

    def resolve(
        self,
        request: VenueCapabilityResolutionRequest,
    ) -> VenueCapabilityResolutionDecision:
        """Resolve latest known capability snapshots into a validation bundle."""
        ...
