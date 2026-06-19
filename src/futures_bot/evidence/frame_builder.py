from __future__ import annotations

from futures_bot.domain.evidence import (
    MarketEvidenceBuilderDescriptor,
    MarketEvidenceSet,
    build_market_evidence_builder_descriptor,
    build_market_evidence_set,
    derive_market_evidence_items,
)
from futures_bot.domain.market_data import CrossVenueMarketFrame


class DeterministicCrossVenueMarketEvidenceBuilder:
    """Build direct factual evidence from one cross-venue market frame."""

    def __init__(self) -> None:
        self._descriptor = build_market_evidence_builder_descriptor()

    @property
    def descriptor(self) -> MarketEvidenceBuilderDescriptor:
        return MarketEvidenceBuilderDescriptor.model_validate(
            self._descriptor.model_dump()
        )

    def build(self, frame: CrossVenueMarketFrame) -> MarketEvidenceSet:
        source_frame = CrossVenueMarketFrame.model_validate(frame.model_dump())
        builder = self.descriptor
        items = derive_market_evidence_items(
            source_frame=source_frame,
            builder=builder,
        )
        return build_market_evidence_set(
            builder=builder,
            source_frame=source_frame,
            items=items,
        )
