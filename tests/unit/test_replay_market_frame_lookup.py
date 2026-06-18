from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.unit.replay_decision_market_fixtures import replay_decision_market_fixture

from futures_bot.domain.ids import (
    ReplayMarketFrameProjectionId,
    ReplayMarketObservationProjectionId,
)
from futures_bot.domain.replay import ReplayInputKind
from futures_bot.domain.replay_market_data import (
    ReplayMarketFrameLookupAuthority,
    ReplayMarketFrameLookupDescriptor,
    ReplayMarketFrameLookupResult,
    ReplayMarketFrameTimeline,
    build_replay_market_frame_lookup_authority,
    build_replay_market_frame_lookup_authority_fingerprint,
    build_replay_market_frame_lookup_descriptor,
    build_replay_market_frame_lookup_entry,
    build_replay_market_frame_lookup_entry_id,
    validate_replay_market_frame_lookup_membership,
)
from futures_bot.market_data.replay_lookup import LocalReplayMarketFrameLookup


def test_lookup_descriptor_round_trip_and_valid_result() -> None:
    fixture = replay_decision_market_fixture()
    lookup = fixture.lookup
    result = lookup.lookup(fixture.dispatch_context, fixture.event)

    assert lookup.descriptor == build_replay_market_frame_lookup_descriptor(
        lookup.authority
    )
    assert ReplayMarketFrameLookupAuthority.model_validate(
        lookup.authority.model_dump()
    ) == lookup.authority
    assert ReplayMarketFrameLookupDescriptor.model_validate(
        lookup.descriptor.model_dump()
    ) == lookup.descriptor
    assert ReplayMarketFrameLookupResult.model_validate(result.model_dump()) == result
    validate_replay_market_frame_lookup_membership(
        authority=lookup.authority,
        result=result,
    )
    assert result.frame_projection.frame == fixture.market_timeline.frame_projections[0].frame


@pytest.mark.parametrize(
    ("context_update", "event_update", "match"),
    (
        ({"timeline_id": "other-timeline"}, {}, "timeline"),
        ({"replay_plan_id": "other-plan"}, {}, "plan"),
        ({}, {"event_id": "other-event"}, "event_id"),
        ({}, {"order_index": 99}, "order_index"),
        ({}, {"event_time": replay_decision_market_fixture().event.event_time}, "event"),
        ({}, {"kind": ReplayInputKind.TRADE}, "kind"),
    ),
)
def test_lookup_rejects_context_event_mismatches(context_update, event_update, match) -> None:
    fixture = replay_decision_market_fixture()
    if "event_time" in event_update:
        event_update["event_time"] = fixture.event.event_time.replace(hour=13)
    context = fixture.dispatch_context.model_copy(update=context_update)
    event = fixture.event.model_copy(update=event_update)

    with pytest.raises((ValidationError, ValueError), match=match):
        fixture.lookup.lookup(context, event)


def test_lookup_rejects_missing_and_unsupported_projection() -> None:
    fixture = replay_decision_market_fixture()
    missing_event = fixture.event.model_copy(
        update={"event_id": "event-missing", "order_index": 1}
    )
    missing_context = fixture.dispatch_context.model_copy(
        update={"event_id": "event-missing", "event_order_index": 1}
    )

    with pytest.raises(ValueError, match="no replay market"):
        fixture.lookup.lookup(missing_context, missing_event)

    unsupported = fixture.event.model_copy(update={"kind": ReplayInputKind.TRADE})
    with pytest.raises(ValueError, match="kind"):
        fixture.lookup.lookup(
            fixture.dispatch_context.model_copy(update={"event_kind": ReplayInputKind.TRADE}),
            unsupported,
        )


def test_lookup_rejects_duplicate_projection_key_and_nested_tampering() -> None:
    fixture = replay_decision_market_fixture()
    duplicated_payload = fixture.market_timeline.model_dump()
    duplicated_payload["observation_projections"] = (
        *duplicated_payload["observation_projections"],
        duplicated_payload["observation_projections"][0],
    )
    duplicated_payload["frame_projections"] = (
        *duplicated_payload["frame_projections"],
        duplicated_payload["frame_projections"][0],
    )
    with pytest.raises((ValidationError, ValueError)):
        LocalReplayMarketFrameLookup(ReplayMarketFrameTimeline.model_validate(duplicated_payload))

    bad = fixture.lookup.lookup(fixture.dispatch_context, fixture.event).model_copy(
        update={
            "frame_projection": fixture.market_timeline.frame_projections[0].model_copy(
                update={"event_id": "other-event"}
            )
        }
    )
    with pytest.raises(ValidationError):
        ReplayMarketFrameLookupResult.model_validate(bad.model_dump())


def test_lookup_snapshot_is_immutable_after_input_mutation() -> None:
    fixture = replay_decision_market_fixture()
    lookup = LocalReplayMarketFrameLookup(fixture.market_timeline)
    original_descriptor = lookup.descriptor
    mutated = fixture.market_timeline.model_copy(update={"replay_plan_id": "other-plan"})

    assert mutated.replay_plan_id == "other-plan"
    assert lookup.descriptor == original_descriptor
    assert lookup.lookup(fixture.dispatch_context, fixture.event).descriptor == (
        original_descriptor
    )


def test_lookup_membership_rejects_forged_entry_with_original_authority() -> None:
    fixture = replay_decision_market_fixture(price="100")
    changed = replay_decision_market_fixture(price="101")
    forged_entry = build_replay_market_frame_lookup_entry(
        market_timeline_id=fixture.lookup.authority.market_timeline_id,
        replay_timeline_id=fixture.lookup.authority.replay_timeline_id,
        replay_plan_id=fixture.lookup.authority.replay_plan_id,
        adapter_fingerprint=fixture.lookup.authority.adapter_fingerprint,
        observation_projection=changed.market_timeline.observation_projections[0],
        frame_projection=changed.market_timeline.frame_projections[0],
    )
    forged = ReplayMarketFrameLookupResult(
        descriptor=fixture.lookup.descriptor,
        entry=forged_entry,
        observation_projection=changed.market_timeline.observation_projections[0],
        frame_projection=changed.market_timeline.frame_projections[0],
    )

    with pytest.raises(ValueError, match="absent"):
        validate_replay_market_frame_lookup_membership(
            authority=fixture.lookup.authority,
            result=forged,
        )


def test_lookup_authority_canonical_builder_round_trip_and_determinism() -> None:
    fixture = replay_decision_market_fixture()
    first = build_replay_market_frame_lookup_authority(fixture.market_timeline)
    second = build_replay_market_frame_lookup_authority(fixture.market_timeline)

    assert first == second
    assert first == fixture.lookup.authority
    assert ReplayMarketFrameLookupAuthority.model_validate(first.model_dump()) == first
    assert first.entries == tuple(
        sorted(first.entries, key=lambda entry: (entry.event_order_index, entry.event_id))
    )


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("duplicate_event_id", "event IDs"),
        ("duplicate_event_order_index", "event order indexes"),
        ("duplicate_event_key", "event keys"),
        ("duplicate_entry_id", "entry IDs"),
        ("duplicate_observation_projection_id", "observation projection IDs"),
        ("duplicate_frame_projection_id", "frame projection IDs"),
        ("non_canonical_ordering", "sorted"),
    ),
)
def test_lookup_authority_rejects_invalid_membership(mutation: str, match: str) -> None:
    authority = replay_decision_market_fixture().lookup.authority
    first = authority.entries[0]
    second = _lookup_entry_variant(
        first,
        event_id="event-2",
        event_order_index=1,
        observation_projection_id=ReplayMarketObservationProjectionId(
            "replay-market-observation-projection:" + "8" * 64
        ),
        frame_projection_id=ReplayMarketFrameProjectionId(
            "replay-market-frame-projection:" + "9" * 64
        ),
    )
    if mutation == "duplicate_event_id":
        second = _lookup_entry_variant(first, event_id=first.event_id, event_order_index=1)
    elif mutation == "duplicate_event_order_index":
        second = _lookup_entry_variant(
            first,
            event_id="event-2",
            event_order_index=first.event_order_index,
        )
    elif mutation == "duplicate_event_key":
        second = _lookup_entry_variant(
            first,
            event_id=first.event_id,
            event_order_index=first.event_order_index,
            observation_projection_id=ReplayMarketObservationProjectionId(
                "replay-market-observation-projection:" + "6" * 64
            ),
            frame_projection_id=ReplayMarketFrameProjectionId(
                "replay-market-frame-projection:" + "7" * 64
            ),
        )
    elif mutation == "duplicate_entry_id":
        second = first
    elif mutation == "duplicate_observation_projection_id":
        second = _lookup_entry_variant(
            first,
            event_id="event-2",
            event_order_index=1,
            frame_projection_id=ReplayMarketFrameProjectionId(
                "replay-market-frame-projection:" + "2" * 64
            ),
        )
    elif mutation == "duplicate_frame_projection_id":
        second = _lookup_entry_variant(
            first,
            event_id="event-2",
            event_order_index=1,
            observation_projection_id=ReplayMarketObservationProjectionId(
                "replay-market-observation-projection:" + "3" * 64
            ),
        )
    entries = (first, second)
    if mutation == "non_canonical_ordering":
        entries = (second, first)

    with pytest.raises(ValidationError, match=match):
        ReplayMarketFrameLookupAuthority.model_validate(
            _lookup_authority_payload(authority, entries)
        )


def test_lookup_authority_named_regressions_duplicate_projection_and_order() -> None:
    authority = replay_decision_market_fixture().lookup.authority
    first = authority.entries[0]
    duplicate_projection_ids = _lookup_entry_variant(
        first,
        event_id="event-2",
        event_order_index=1,
    )
    same_order_index = _lookup_entry_variant(
        first,
        event_id="event-2",
        event_order_index=first.event_order_index,
        observation_projection_id=ReplayMarketObservationProjectionId(
            "replay-market-observation-projection:" + "4" * 64
        ),
        frame_projection_id=ReplayMarketFrameProjectionId(
            "replay-market-frame-projection:" + "5" * 64
        ),
    )

    with pytest.raises(ValidationError, match="observation projection IDs"):
        ReplayMarketFrameLookupAuthority.model_validate(
            _lookup_authority_payload(authority, (first, duplicate_projection_ids))
        )
    with pytest.raises(ValidationError, match="event order indexes"):
        ReplayMarketFrameLookupAuthority.model_validate(
            _lookup_authority_payload(authority, (first, same_order_index))
        )


def test_lookup_authority_model_copy_tampering_and_fingerprint_builder_reject_invalid() -> None:
    authority = replay_decision_market_fixture().lookup.authority
    first = authority.entries[0]
    duplicate = _lookup_entry_variant(first, event_id="event-2", event_order_index=1)
    tampered = authority.model_copy(update={"entries": (first, duplicate)})

    with pytest.raises(ValidationError, match="observation projection IDs"):
        ReplayMarketFrameLookupAuthority.model_validate(tampered.model_dump())
    with pytest.raises(ValueError, match="observation projection IDs"):
        build_replay_market_frame_lookup_authority_fingerprint(
            market_timeline_id=authority.market_timeline_id,
            replay_timeline_id=authority.replay_timeline_id,
            replay_plan_id=authority.replay_plan_id,
            adapter_fingerprint=authority.adapter_fingerprint,
            supported_event_kinds=authority.supported_event_kinds,
            entries=(first, duplicate),
        )


def _lookup_authority_payload(
    authority: ReplayMarketFrameLookupAuthority,
    entries: tuple,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "market_timeline_id": authority.market_timeline_id.model_dump(mode="json"),
        "replay_timeline_id": authority.replay_timeline_id,
        "replay_plan_id": authority.replay_plan_id,
        "adapter_fingerprint": authority.adapter_fingerprint,
        "supported_event_kinds": [kind.value for kind in authority.supported_event_kinds],
        "entries": [entry.model_dump(mode="json") for entry in entries],
        "lookup_authority_fingerprint": "replay-market-frame-lookup-authority:" + "0" * 64,
    }


def _lookup_entry_variant(
    entry,
    *,
    event_id: str,
    event_order_index: int,
    observation_projection_id=None,
    frame_projection_id=None,
):
    observation_projection_id = observation_projection_id or entry.observation_projection_id
    frame_projection_id = frame_projection_id or entry.frame_projection_id
    entry_id = build_replay_market_frame_lookup_entry_id(
        market_timeline_id=entry.market_timeline_id,
        replay_timeline_id=entry.replay_timeline_id,
        replay_plan_id=entry.replay_plan_id,
        adapter_fingerprint=entry.adapter_fingerprint,
        event_id=event_id,
        event_order_index=event_order_index,
        event_time=entry.event_time,
        event_kind=entry.event_kind,
        observation_projection_id=observation_projection_id,
        frame_projection_id=frame_projection_id,
        frame_id=entry.frame_id,
        triggering_observation_id=entry.triggering_observation_id,
        binding_authority_fingerprint=entry.binding_authority_fingerprint,
    )
    return entry.model_copy(
        update={
            "entry_id": entry_id,
            "event_id": event_id,
            "event_order_index": event_order_index,
            "observation_projection_id": observation_projection_id,
            "frame_projection_id": frame_projection_id,
        }
    )
