from __future__ import annotations

from pydantic import BaseModel

from futures_bot.domain.evidence import MarketEvidenceBuilderDescriptor, MarketEvidenceSet
from futures_bot.domain.replay_evidence import (
    ReplayMarketEvidenceTimeline,
    build_replay_market_evidence_projection,
    build_replay_market_evidence_timeline,
)
from futures_bot.domain.replay_market_data import (
    ReplayMarketFrameTimeline,
    build_replay_market_frame_lookup_authority,
    build_replay_market_frame_lookup_descriptor,
)
from futures_bot.evidence.frame_builder import (
    DeterministicCrossVenueMarketEvidenceBuilder,
)
from futures_bot.ports.evidence import MarketEvidenceBuilderPort


class DeterministicReplayMarketEvidenceTimelineBuilder:
    def __init__(
        self,
        evidence_builder: MarketEvidenceBuilderPort | None = None,
    ) -> None:
        self._evidence_builder = (
            evidence_builder or DeterministicCrossVenueMarketEvidenceBuilder()
        )
        self._evidence_builder_descriptor = _snapshot_model(
            MarketEvidenceBuilderDescriptor,
            self._evidence_builder.descriptor,
        )

    @property
    def evidence_builder_descriptor(self) -> MarketEvidenceBuilderDescriptor:
        return _snapshot_model(
            MarketEvidenceBuilderDescriptor,
            self._evidence_builder_descriptor,
        )

    def build(
        self,
        market_frame_timeline: ReplayMarketFrameTimeline,
    ) -> ReplayMarketEvidenceTimeline:
        timeline = _snapshot_model(ReplayMarketFrameTimeline, market_frame_timeline)
        descriptor = self.evidence_builder_descriptor
        _reject_descriptor_mutation(
            current=self._evidence_builder.descriptor,
            expected=descriptor,
        )
        authority = build_replay_market_frame_lookup_authority(timeline)
        lookup_descriptor = build_replay_market_frame_lookup_descriptor(authority)
        projections = []
        for entry, frame_projection in zip(
            authority.entries,
            timeline.frame_projections,
            strict=True,
        ):
            _reject_descriptor_mutation(
                current=self._evidence_builder.descriptor,
                expected=descriptor,
            )
            evidence_set = _snapshot_model(
                MarketEvidenceSet,
                self._evidence_builder.build(frame_projection.frame),
            )
            _reject_descriptor_mutation(
                current=self._evidence_builder.descriptor,
                expected=descriptor,
            )
            if evidence_set.builder != descriptor:
                raise ValueError("evidence builder returned stale or foreign descriptor")
            projections.append(
                build_replay_market_evidence_projection(
                    market_lookup_descriptor=lookup_descriptor,
                    market_lookup_entry=entry,
                    market_frame_projection=frame_projection,
                    evidence_set=evidence_set,
                )
            )
        _reject_descriptor_mutation(
            current=self._evidence_builder.descriptor,
            expected=descriptor,
        )
        return build_replay_market_evidence_timeline(
            market_lookup_authority=authority,
            evidence_builder=descriptor,
            projections=tuple(projections),
        )


def _reject_descriptor_mutation(
    *,
    current: MarketEvidenceBuilderDescriptor,
    expected: MarketEvidenceBuilderDescriptor,
) -> None:
    if _snapshot_model(MarketEvidenceBuilderDescriptor, current) != expected:
        raise ValueError("evidence builder descriptor mutated")


def _snapshot_model[T: BaseModel](model_type: type[T], value: object) -> T:
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json")
        if dumped is value:
            raise ValueError("model_dump must return inert plain data")
        if isinstance(value, model_type) and type(value) is not model_type:
            raise ValueError(f"expected exact {model_type.__name__}")
        model = model_type.model_validate(dumped)
    else:
        model = model_type.model_validate(value)
    if type(model) is not model_type:
        raise ValueError(f"expected exact {model_type.__name__}")
    return model
