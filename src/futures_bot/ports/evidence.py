from __future__ import annotations

from typing import Protocol

from futures_bot.domain.evidence import (
    MarketEvidenceBuilderDescriptor,
    MarketEvidenceSet,
)
from futures_bot.domain.market_data import CrossVenueMarketFrame


class MarketEvidenceBuilderPort(Protocol):
    """Synchronous read-only builder for factual market evidence."""

    @property
    def descriptor(self) -> MarketEvidenceBuilderDescriptor:
        """Return the deterministic builder descriptor."""
        ...

    def build(self, frame: CrossVenueMarketFrame) -> MarketEvidenceSet:
        """Build factual market evidence from one validated market frame."""
        ...
