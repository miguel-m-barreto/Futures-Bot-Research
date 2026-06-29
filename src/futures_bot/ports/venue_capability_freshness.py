from __future__ import annotations

from typing import Protocol

from futures_bot.domain.ids import VenueCapabilityFreshnessDecisionId
from futures_bot.domain.venue_capability_freshness import (
    VenueCapabilityFreshnessCheck,
    VenueCapabilityFreshnessDecision,
)


class VenueCapabilityFreshnessValidatorPort(Protocol):
    """Pure interface for deterministic capability freshness validation."""

    def validate(
        self,
        check: VenueCapabilityFreshnessCheck,
    ) -> VenueCapabilityFreshnessDecision:
        """Validate explicit capability snapshot freshness."""
        ...


class VenueCapabilityFreshnessDecisionStorePort(Protocol):
    """Pure idempotent store for freshness decisions."""

    def put(self, decision: VenueCapabilityFreshnessDecision) -> None:
        """Store a freshness decision idempotently."""
        ...

    def get(
        self,
        decision_id: VenueCapabilityFreshnessDecisionId,
    ) -> VenueCapabilityFreshnessDecision | None:
        """Return a freshness decision by ID, or None."""
        ...
