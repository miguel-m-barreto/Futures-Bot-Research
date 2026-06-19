from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel
from tests.unit.replay_decision_market_fixtures import replay_decision_market_fixture

from futures_bot.domain.evidence import (
    MarketEvidenceBuilderDescriptor,
    MarketEvidenceSet,
)
from futures_bot.domain.market_data import CrossVenueMarketFrame
from futures_bot.domain.replay_evidence import ReplayMarketEvidenceTimeline
from futures_bot.domain.replay_market_data import ReplayMarketFrameTimeline
from futures_bot.evidence.frame_builder import DeterministicCrossVenueMarketEvidenceBuilder
from futures_bot.evidence.replay_projection import (
    DeterministicReplayMarketEvidenceTimelineBuilder,
)


def test_default_builder_creates_projection_per_market_frame_in_authority_order() -> None:
    fixture = replay_decision_market_fixture()
    timeline = DeterministicReplayMarketEvidenceTimelineBuilder().build(
        fixture.market_timeline
    )

    assert len(timeline.projections) == len(fixture.market_timeline.frame_projections)
    assert tuple(
        projection.market_lookup_entry for projection in timeline.projections
    ) == timeline.market_lookup_authority.entries
    assert all(
        projection.evidence_set.source_frame == projection.market_frame_projection.frame
        for projection in timeline.projections
    )


def test_builder_is_deterministic_for_same_and_equivalent_rebuilt_timeline() -> None:
    builder = DeterministicReplayMarketEvidenceTimelineBuilder()
    fixture = replay_decision_market_fixture(price="100.00")
    first = builder.build(fixture.market_timeline)
    second = builder.build(fixture.market_timeline)
    equivalent = builder.build(replay_decision_market_fixture(price="100.00").market_timeline)

    assert first == second == equivalent


def test_changed_market_frame_and_decimal_scale_change_timeline_identity() -> None:
    builder = DeterministicReplayMarketEvidenceTimelineBuilder()
    base = builder.build(replay_decision_market_fixture(price="100.00").market_timeline)
    changed_price = builder.build(
        replay_decision_market_fixture(price="101.00").market_timeline
    )
    changed_scale = builder.build(
        replay_decision_market_fixture(price="100.0").market_timeline
    )

    assert base.evidence_timeline_id != changed_price.evidence_timeline_id
    assert base.evidence_timeline_id != changed_scale.evidence_timeline_id
    assert base.projections[0].projection_id != changed_scale.projections[0].projection_id
    assert base.projections[0].evidence_set.evidence_set_id != (
        changed_scale.projections[0].evidence_set.evidence_set_id
    )
    assert _first_decimal_item(base).evidence_item_id != (
        _first_decimal_item(changed_scale).evidence_item_id
    )


def test_builder_embeds_no_decision_fields_and_fabricates_no_health_evidence() -> None:
    timeline = DeterministicReplayMarketEvidenceTimelineBuilder().build(
        replay_decision_market_fixture().market_timeline
    )
    rendered = repr(timeline.model_dump(mode="json"))
    forbidden = {
        "DecisionStack",
        "ReplayDecisionStackContext",
        "DecisionIntent",
        "NoTradeDecision",
        "ReplayDecisionOutputEnvelope",
        "ReplayDecisionMarketContextReference",
    }
    for name in forbidden:
        assert name not in rendered
    assert all(
        item.origin.origin_kind.value != "SOURCE_HEALTH"
        for projection in timeline.projections
        for item in projection.evidence_set.items
    )


def test_builder_retains_no_mutable_caller_owned_timeline_reference() -> None:
    fixture = replay_decision_market_fixture()
    built = DeterministicReplayMarketEvidenceTimelineBuilder().build(
        fixture.market_timeline
    )
    original = built.projections[0].market_frame_projection

    object.__setattr__(fixture.market_timeline, "frame_projections", ())

    assert built.projections[0].market_frame_projection == original
    assert len(built.projections) == 1


def test_descriptor_mutation_before_build_is_rejected() -> None:
    port = _MutatingDescriptorBuilder(mutate_before_build=True)
    builder = DeterministicReplayMarketEvidenceTimelineBuilder(port)

    with pytest.raises(ValueError, match=r"descriptor|builder_fingerprint"):
        builder.build(replay_decision_market_fixture().market_timeline)


def test_descriptor_mutation_during_build_is_rejected() -> None:
    port = _MutatingDescriptorBuilder(mutate_during_build=True)
    builder = DeterministicReplayMarketEvidenceTimelineBuilder(port)

    with pytest.raises(ValueError, match=r"descriptor|builder_fingerprint"):
        builder.build(replay_decision_market_fixture().market_timeline)


def test_evidence_builder_returning_evidence_from_another_frame_is_rejected() -> None:
    other_frame = replay_decision_market_fixture(price="101.00").market_timeline
    port = _ForeignFrameEvidenceBuilder(other_frame.frame_projections[0].frame)

    with pytest.raises(ValueError, match=r"source_frame|frame"):
        DeterministicReplayMarketEvidenceTimelineBuilder(port).build(
            replay_decision_market_fixture(price="100.00").market_timeline
        )


def test_evidence_builder_returning_subclass_is_rejected_after_one_dump() -> None:
    port = _SubclassEvidenceBuilder()

    with pytest.raises(ValueError, match="expected exact MarketEvidenceSet"):
        DeterministicReplayMarketEvidenceTimelineBuilder(port).build(
            replay_decision_market_fixture().market_timeline
        )
    assert port.returned is not None
    assert port.returned.dump_count == 1


def test_evidence_builder_returning_model_dump_self_is_rejected() -> None:
    port = _SelfDumpEvidenceBuilder()

    with pytest.raises(ValueError, match="inert plain data"):
        DeterministicReplayMarketEvidenceTimelineBuilder(port).build(
            replay_decision_market_fixture().market_timeline
        )
    assert port.returned is not None
    assert port.returned.dump_count == 1


def test_market_frame_timeline_subclass_model_dump_self_is_rejected() -> None:
    fixture = replay_decision_market_fixture()
    bad = _SelfDumpTimeline.model_validate(fixture.market_timeline.model_dump(mode="json"))

    with pytest.raises(ValueError, match="inert plain data"):
        DeterministicReplayMarketEvidenceTimelineBuilder().build(bad)
    assert bad.dump_count == 1


def test_nested_custom_object_in_returned_evidence_set_is_rejected() -> None:
    port = _NestedCustomEvidenceBuilder()

    with pytest.raises(ValueError):
        DeterministicReplayMarketEvidenceTimelineBuilder(port).build(
            replay_decision_market_fixture().market_timeline
        )


class _MutatingDescriptorBuilder:
    def __init__(
        self,
        *,
        mutate_before_build: bool = False,
        mutate_during_build: bool = False,
    ) -> None:
        self._delegate = DeterministicCrossVenueMarketEvidenceBuilder()
        self._mutate_before_build = mutate_before_build
        self._mutate_during_build = mutate_during_build
        self._descriptor_calls = 0

    @property
    def descriptor(self) -> MarketEvidenceBuilderDescriptor:
        self._descriptor_calls += 1
        if self._mutate_before_build and self._descriptor_calls > 1:
            return _bad_descriptor()
        if self._mutate_during_build and self._descriptor_calls > 2:
            return _bad_descriptor()
        return self._delegate.descriptor

    def build(self, frame: CrossVenueMarketFrame) -> MarketEvidenceSet:
        return self._delegate.build(frame)


class _ForeignFrameEvidenceBuilder:
    def __init__(self, foreign_frame: CrossVenueMarketFrame) -> None:
        self._delegate = DeterministicCrossVenueMarketEvidenceBuilder()
        self._foreign_frame = foreign_frame

    @property
    def descriptor(self) -> MarketEvidenceBuilderDescriptor:
        return self._delegate.descriptor

    def build(self, frame: CrossVenueMarketFrame) -> MarketEvidenceSet:
        return self._delegate.build(self._foreign_frame)


class _SubclassEvidenceBuilder:
    def __init__(self) -> None:
        self._delegate = DeterministicCrossVenueMarketEvidenceBuilder()
        self.returned: _FlippingEvidenceSet | None = None

    @property
    def descriptor(self) -> MarketEvidenceBuilderDescriptor:
        return self._delegate.descriptor

    def build(self, frame: CrossVenueMarketFrame) -> MarketEvidenceSet:
        valid = self._delegate.build(frame)
        self.returned = _FlippingEvidenceSet.model_validate(valid.model_dump(mode="json"))
        return self.returned


class _SelfDumpEvidenceBuilder:
    def __init__(self) -> None:
        self._delegate = DeterministicCrossVenueMarketEvidenceBuilder()
        self.returned: _SelfDumpEvidenceSet | None = None

    @property
    def descriptor(self) -> MarketEvidenceBuilderDescriptor:
        return self._delegate.descriptor

    def build(self, frame: CrossVenueMarketFrame) -> MarketEvidenceSet:
        valid = self._delegate.build(frame)
        self.returned = _SelfDumpEvidenceSet.model_validate(valid.model_dump(mode="json"))
        return self.returned


class _NestedCustomEvidenceBuilder:
    def __init__(self) -> None:
        self._delegate = DeterministicCrossVenueMarketEvidenceBuilder()

    @property
    def descriptor(self) -> MarketEvidenceBuilderDescriptor:
        return self._delegate.descriptor

    def build(self, frame: CrossVenueMarketFrame) -> MarketEvidenceSet:
        valid = self._delegate.build(frame)
        return _CustomDumpEvidenceSet.model_validate(valid.model_dump(mode="json"))


class _FlippingEvidenceSet(MarketEvidenceSet):
    dump_count: int = 0

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, object]:
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        dumped = super().model_dump(*args, **kwargs)
        if self.dump_count > 1:
            dumped["items"] = []
        return dumped


class _SelfDumpEvidenceSet(MarketEvidenceSet):
    dump_count: int = 0

    def model_dump(self, *args: Any, **kwargs: Any) -> BaseModel:
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        return self


class _CustomDumpEvidenceSet(MarketEvidenceSet):
    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, object]:
        dumped = super().model_dump(*args, **kwargs)
        dumped["source_frame"] = object()
        return dumped


class _SelfDumpTimeline(ReplayMarketFrameTimeline):
    dump_count: int = 0

    def model_dump(self, *args: Any, **kwargs: Any) -> BaseModel:
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        return self


def _bad_descriptor() -> MarketEvidenceBuilderDescriptor:
    valid = DeterministicCrossVenueMarketEvidenceBuilder().descriptor
    return MarketEvidenceBuilderDescriptor.model_construct(
        schema_version=valid.schema_version,
        builder_id=valid.builder_id,
        builder_version=valid.builder_version,
        supported_evidence_kinds=valid.supported_evidence_kinds,
        builder_fingerprint="market-evidence-builder:" + "0" * 64,
    )


def _first_decimal_item(timeline: ReplayMarketEvidenceTimeline):
    return next(
        item
        for item in timeline.projections[0].evidence_set.items
        if item.value.value_kind.value == "DECIMAL"
    )
