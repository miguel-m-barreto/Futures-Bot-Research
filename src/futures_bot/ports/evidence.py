from __future__ import annotations

from typing import Protocol

from futures_bot.domain.evidence import (
    MarketEvidenceBuilderDescriptor,
    MarketEvidenceSet,
)
from futures_bot.domain.market_data import CrossVenueMarketFrame
from futures_bot.domain.replay_evidence import ReplayMarketEvidenceTimeline
from futures_bot.domain.replay_market_data import ReplayMarketFrameTimeline


class MarketEvidenceBuilderPort(Protocol):
    """Synchronous read-only builder for factual market evidence."""

    @property
    def descriptor(self) -> MarketEvidenceBuilderDescriptor:
        """Return the deterministic builder descriptor."""
        ...

    def build(self, frame: CrossVenueMarketFrame) -> MarketEvidenceSet:
        """Build factual market evidence from one validated market frame."""
        ...


class ReplayMarketEvidenceTimelineBuilderPort(Protocol):
    """Synchronous read-only builder for deterministic replay evidence timelines."""

    @property
    def evidence_builder_descriptor(self) -> MarketEvidenceBuilderDescriptor:
        """Return the deterministic factual evidence builder descriptor."""
        ...

    def build(
        self,
        market_frame_timeline: ReplayMarketFrameTimeline,
    ) -> ReplayMarketEvidenceTimeline:
        """Build one factual evidence projection per replay market frame."""
        ...
