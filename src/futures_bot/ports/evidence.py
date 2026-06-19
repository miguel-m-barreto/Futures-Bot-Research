from __future__ import annotations

from typing import Protocol

from futures_bot.domain.evidence import (
    MarketEvidenceBuilderDescriptor,
    MarketEvidenceSet,
)
from futures_bot.domain.market_data import CrossVenueMarketFrame
from futures_bot.domain.replay import ReplayDispatchContext, ReplayTimelineEvent
from futures_bot.domain.replay_evidence import (
    ReplayMarketEvidenceLookupAuthority,
    ReplayMarketEvidenceLookupDescriptor,
    ReplayMarketEvidenceLookupResult,
    ReplayMarketEvidenceTimeline,
)
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


class ReplayMarketEvidenceLookupPort(Protocol):
    """Synchronous read-only lookup over a replay market-evidence timeline."""

    @property
    def authority(self) -> ReplayMarketEvidenceLookupAuthority:
        """Return the deterministic replay evidence lookup authority."""
        ...

    @property
    def descriptor(self) -> ReplayMarketEvidenceLookupDescriptor:
        """Return the compact replay evidence lookup descriptor."""
        ...

    def lookup(
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
    ) -> ReplayMarketEvidenceLookupResult:
        """Lookup factual market evidence for one exact replay event."""
        ...
