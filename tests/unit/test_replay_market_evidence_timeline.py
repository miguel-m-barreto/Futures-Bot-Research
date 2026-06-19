from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.unit.replay_decision_market_fixtures import replay_decision_market_fixture

from futures_bot.domain.evidence import (
    DecimalMarketEvidenceValue,
    MarketEvidenceItem,
    MarketEvidenceSet,
    build_market_evidence_item_id,
)
from futures_bot.domain.ids import ReplayMarketEvidenceProjectionId
from futures_bot.domain.replay_evidence import (
    ReplayMarketEvidenceProjection,
    ReplayMarketEvidenceTimeline,
    build_replay_market_evidence_projection,
    build_replay_market_evidence_projection_id,
    build_replay_market_evidence_timeline,
    build_replay_market_evidence_timeline_id,
    derive_replay_market_evidence_projections,
    replay_market_evidence_projection_key,
)
from futures_bot.domain.replay_market_data import (
    ReplayMarketFrameLookupAuthority,
    build_replay_market_frame_lookup_authority,
    build_replay_market_frame_lookup_descriptor,
)
from futures_bot.evidence.frame_builder import DeterministicCrossVenueMarketEvidenceBuilder


def test_valid_projection_round_trip_deterministic_id_and_key() -> None:
    projection, _, _ = _valid_projection()

    assert ReplayMarketEvidenceProjection.model_validate(
        projection.model_dump(mode="json")
    ) == projection
    assert build_replay_market_evidence_projection_id(
        market_lookup_descriptor=projection.market_lookup_descriptor,
        market_lookup_entry=projection.market_lookup_entry,
        market_frame_projection=projection.market_frame_projection,
        evidence_set=projection.evidence_set,
    ) == projection.projection_id
    assert replay_market_evidence_projection_key(projection) == (
        projection.market_lookup_entry.event_order_index,
        projection.market_lookup_entry.event_id,
    )

    tampered = projection.model_copy(
        update={
            "projection_id": ReplayMarketEvidenceProjectionId(
                value="replay-market-evidence-projection:" + "0" * 64
            )
        }
    )
    with pytest.raises(ValidationError, match="projection_id"):
        ReplayMarketEvidenceProjection.model_validate(tampered.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("field", "match"),
    (
        ("market_lookup_descriptor", "descriptor"),
        ("market_lookup_entry", r"entry_id|event_id"),
        ("market_frame_projection", r"frame_projection_id|event_id"),
        ("evidence_set", "source_frame"),
    ),
)
def test_projection_rejects_wrong_nested_models(field: str, match: str) -> None:
    projection, _, other_projection = _valid_projection()
    replacements = {
        "market_lookup_descriptor": projection.market_lookup_descriptor.model_copy(
            update={"replay_plan_id": "other-plan"}
        ),
        "market_lookup_entry": projection.market_lookup_entry.model_copy(
            update={"event_id": "other-event"}
        ),
        "market_frame_projection": other_projection.market_frame_projection,
        "evidence_set": other_projection.evidence_set,
    }
    tampered = projection.model_copy(update={field: replacements[field]})

    with pytest.raises((ValidationError, ValueError), match=match):
        ReplayMarketEvidenceProjection.model_validate(tampered.model_dump(mode="json"))


def test_projection_rejects_entry_frame_and_builder_mismatches() -> None:
    projection, _, _ = _valid_projection()

    cases = (
        projection.market_lookup_entry.model_copy(update={"event_id": "other-event"}),
        projection.market_lookup_entry.model_copy(update={"event_order_index": 99}),
        projection.market_lookup_entry.model_copy(
            update={"event_time": projection.market_lookup_entry.event_time.replace(hour=13)}
        ),
        projection.market_lookup_entry.model_copy(
            update={
                "frame_projection_id": (
                    "replay-market-frame-projection:" + "9" * 64
                )
            }
        ),
        projection.market_lookup_entry.model_copy(
            update={"frame_id": "market-frame:" + "8" * 64}
        ),
    )
    for entry in cases:
        with pytest.raises((ValidationError, ValueError)):
            ReplayMarketEvidenceProjection.model_validate(
                projection.model_copy(update={"market_lookup_entry": entry}).model_dump(
                    mode="json"
                )
            )

    payload = projection.evidence_set.model_dump(mode="json")
    payload["builder"] = {
        **payload["builder"],
        "builder_fingerprint": "market-evidence-builder:" + "0" * 64,
    }
    with pytest.raises(ValidationError, match="builder_fingerprint"):
        ReplayMarketEvidenceProjection.model_validate(
            projection.model_copy(update={"evidence_set": payload}).model_dump(mode="json")
        )


def test_valid_timeline_round_trip_and_deterministic_id() -> None:
    timeline = _valid_timeline()

    assert ReplayMarketEvidenceTimeline.model_validate(
        timeline.model_dump(mode="json")
    ) == timeline
    assert build_replay_market_evidence_timeline_id(
        market_lookup_authority=timeline.market_lookup_authority,
        evidence_builder=timeline.evidence_builder,
        projections=timeline.projections,
    ) == timeline.evidence_timeline_id

    tampered = timeline.model_copy(update={"projections": ()})
    with pytest.raises(ValidationError, match="projections"):
        ReplayMarketEvidenceTimeline.model_validate(tampered.model_dump(mode="json"))


def test_timeline_rejects_missing_extra_reordered_and_duplicate_projection() -> None:
    fixture = replay_decision_market_fixture()
    authority = build_replay_market_frame_lookup_authority(fixture.market_timeline)
    builder = DeterministicCrossVenueMarketEvidenceBuilder().descriptor
    projections = derive_replay_market_evidence_projections(
        market_frame_timeline=fixture.market_timeline,
        market_lookup_authority=authority,
        evidence_builder=builder,
    )
    timeline = build_replay_market_evidence_timeline(
        market_lookup_authority=authority,
        evidence_builder=builder,
        projections=projections,
    )

    with pytest.raises(
        (ValidationError, ValueError),
        match=r"one evidence projection|non-empty",
    ):
        build_replay_market_evidence_timeline(
            market_lookup_authority=authority,
            evidence_builder=builder,
            projections=(),
        )
    with pytest.raises((ValidationError, ValueError), match="one evidence projection"):
        build_replay_market_evidence_timeline(
            market_lookup_authority=authority,
            evidence_builder=builder,
            projections=(*timeline.projections, timeline.projections[0]),
        )

    duplicate = timeline.model_copy(
        update={"projections": (timeline.projections[0], timeline.projections[0])}
    )
    with pytest.raises(ValidationError, match="one evidence projection"):
        ReplayMarketEvidenceTimeline.model_validate(duplicate.model_dump(mode="json"))


def test_timeline_rejects_entry_absent_changed_projection_and_stale_id() -> None:
    timeline = _valid_timeline()
    other = _valid_timeline(price="101.00")
    changed_projection = other.projections[0]

    with pytest.raises(
        (ValidationError, ValueError),
        match=r"authority entry|lookup authority",
    ):
        build_replay_market_evidence_timeline_id(
            market_lookup_authority=timeline.market_lookup_authority,
            evidence_builder=timeline.evidence_builder,
            projections=(changed_projection,),
        )
    with pytest.raises(ValidationError, match=r"authority entry|lookup authority"):
        ReplayMarketEvidenceTimeline.model_validate(
            {
                **timeline.model_dump(mode="json"),
                "projections": [changed_projection.model_dump(mode="json")],
            }
        )

    changed_evidence = _changed_evidence_value(timeline.projections[0].evidence_set)
    with pytest.raises((ValidationError, ValueError), match=r"derivation|source_frame"):
        build_replay_market_evidence_projection(
            market_lookup_descriptor=timeline.projections[0].market_lookup_descriptor,
            market_lookup_entry=timeline.projections[0].market_lookup_entry,
            market_frame_projection=timeline.projections[0].market_frame_projection,
            evidence_set=changed_evidence,
        )

    stale = timeline.model_dump(mode="json")
    stale["evidence_timeline_id"] = str(
        build_replay_market_evidence_timeline_id(
            market_lookup_authority=other.market_lookup_authority,
            evidence_builder=other.evidence_builder,
            projections=other.projections,
        )
    )
    with pytest.raises(ValidationError, match="evidence_timeline_id"):
        ReplayMarketEvidenceTimeline.model_validate(stale)


def test_duplicate_authority_entry_rejected_if_directly_constructed() -> None:
    timeline = _valid_timeline()
    authority = timeline.market_lookup_authority
    forged = ReplayMarketFrameLookupAuthority.model_construct(
        **{
            **authority.model_dump(),
            "entries": (authority.entries[0], authority.entries[0]),
        }
    )

    with pytest.raises((ValidationError, ValueError), match=r"entry IDs|one evidence"):
        build_replay_market_evidence_timeline_id(
            market_lookup_authority=forged,
            evidence_builder=timeline.evidence_builder,
            projections=(timeline.projections[0], timeline.projections[0]),
        )


def test_adversarial_invalid_derivations_rejected_by_model_and_id_builder() -> None:
    timeline = _valid_timeline()
    other = _valid_timeline(price="101.00")
    projection = timeline.projections[0]
    invalids = (
        projection.model_copy(update={"evidence_set": other.projections[0].evidence_set}),
        projection.model_copy(
            update={"market_frame_projection": other.projections[0].market_frame_projection}
        ),
        projection.model_copy(
            update={"market_lookup_entry": other.projections[0].market_lookup_entry}
        ),
        projection.model_copy(
            update={
                "market_lookup_descriptor": (
                    other.projections[0].market_lookup_descriptor
                )
            }
        ),
    )

    for invalid in invalids:
        with pytest.raises((ValidationError, ValueError)):
            ReplayMarketEvidenceProjection.model_validate(invalid.model_dump(mode="json"))
        with pytest.raises((ValidationError, ValueError)):
            build_replay_market_evidence_projection_id(
                market_lookup_descriptor=invalid.market_lookup_descriptor,
                market_lookup_entry=invalid.market_lookup_entry,
                market_frame_projection=invalid.market_frame_projection,
                evidence_set=invalid.evidence_set,
            )

    with pytest.raises((ValidationError, ValueError)):
        build_replay_market_evidence_timeline_id(
            market_lookup_authority=other.market_lookup_authority,
            evidence_builder=timeline.evidence_builder,
            projections=timeline.projections,
        )
    with pytest.raises((ValidationError, ValueError)):
        build_replay_market_evidence_timeline_id(
            market_lookup_authority=timeline.market_lookup_authority,
            evidence_builder=_bad_descriptor(timeline.evidence_builder),
            projections=timeline.projections,
        )


def test_derivation_rejects_authority_from_another_market_timeline() -> None:
    fixture = replay_decision_market_fixture(price="100.00")
    other = replay_decision_market_fixture(price="101.00")
    builder = DeterministicCrossVenueMarketEvidenceBuilder().descriptor

    with pytest.raises(ValueError, match="correspond exactly"):
        derive_replay_market_evidence_projections(
            market_frame_timeline=fixture.market_timeline,
            market_lookup_authority=build_replay_market_frame_lookup_authority(
                other.market_timeline
            ),
            evidence_builder=builder,
        )


def test_no_decision_stack_fields_embedded_in_projection_payloads() -> None:
    forbidden = {
        "DecisionStack",
        "ReplayDecisionStackContext",
        "DecisionIntent",
        "NoTradeDecision",
        "ReplayDecisionOutputEnvelope",
        "ReplayDecisionMarketContextReference",
    }
    dumped = _valid_timeline().model_dump(mode="json")
    rendered = repr(dumped)

    for name in forbidden:
        assert name not in rendered


def _valid_projection(
    *,
    price: str = "100.00",
):
    timeline = _valid_timeline(price=price)
    other = _valid_timeline(price="101.00" if price != "101.00" else "102.00")
    return timeline.projections[0], timeline, other.projections[0]


def _valid_timeline(*, price: str = "100.00") -> ReplayMarketEvidenceTimeline:
    fixture = replay_decision_market_fixture(price=price)
    authority = build_replay_market_frame_lookup_authority(fixture.market_timeline)
    builder = DeterministicCrossVenueMarketEvidenceBuilder().descriptor
    projections = derive_replay_market_evidence_projections(
        market_frame_timeline=fixture.market_timeline,
        market_lookup_authority=authority,
        evidence_builder=builder,
    )
    descriptor = build_replay_market_frame_lookup_descriptor(authority)
    assert projections[0].market_lookup_descriptor == descriptor
    return build_replay_market_evidence_timeline(
        market_lookup_authority=authority,
        evidence_builder=builder,
        projections=projections,
    )


def _changed_evidence_value(evidence_set: MarketEvidenceSet) -> MarketEvidenceSet:
    first = next(
        item
        for item in evidence_set.items
        if isinstance(item.value, DecimalMarketEvidenceValue)
    )
    replacement_value = DecimalMarketEvidenceValue.model_validate({"value": "999.00"})
    replacement = MarketEvidenceItem(
        evidence_item_id=build_market_evidence_item_id(
            evidence_kind=first.evidence_kind,
            origin=first.origin,
            unit=first.unit,
            value=replacement_value,
        ),
        evidence_kind=first.evidence_kind,
        origin=first.origin,
        unit=first.unit,
        value=replacement_value,
    )
    index = evidence_set.items.index(first)
    items = (*evidence_set.items[:index], replacement, *evidence_set.items[index + 1 :])
    return MarketEvidenceSet.model_construct(
        evidence_set_id=evidence_set.evidence_set_id,
        builder=evidence_set.builder,
        source_frame=evidence_set.source_frame,
        items=items,
    )


def _bad_descriptor(descriptor):
    return descriptor.model_construct(
        schema_version=descriptor.schema_version,
        builder_id=descriptor.builder_id,
        builder_version=descriptor.builder_version,
        supported_evidence_kinds=descriptor.supported_evidence_kinds,
        builder_fingerprint="market-evidence-builder:" + "0" * 64,
    )
