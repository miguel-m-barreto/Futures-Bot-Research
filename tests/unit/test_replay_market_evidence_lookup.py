from __future__ import annotations

from collections import UserDict
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from tests.unit.replay_decision_market_fixtures import replay_decision_market_fixture

from futures_bot.domain.ids import (
    MarketEvidenceSetId,
    ReplayMarketEvidenceProjectionId,
    ReplayMarketFrameLookupEntryId,
    ReplayMarketFrameProjectionId,
)
from futures_bot.domain.replay import ReplayDispatchContext, ReplayInputKind, ReplayTimelineEvent
from futures_bot.domain.replay_evidence import (
    ReplayMarketEvidenceLookupAuthority,
    ReplayMarketEvidenceLookupDescriptor,
    ReplayMarketEvidenceLookupEntry,
    ReplayMarketEvidenceLookupResult,
    ReplayMarketEvidenceTimeline,
    build_replay_market_evidence_lookup_authority,
    build_replay_market_evidence_lookup_authority_fingerprint,
    build_replay_market_evidence_lookup_descriptor,
    build_replay_market_evidence_lookup_entry,
    build_replay_market_evidence_lookup_entry_id,
    build_replay_market_evidence_lookup_result,
    validate_replay_market_evidence_lookup_membership,
)
from futures_bot.evidence import replay_lookup as replay_lookup_module
from futures_bot.evidence.replay_lookup import LocalReplayMarketEvidenceLookup
from futures_bot.evidence.replay_projection import (
    DeterministicReplayMarketEvidenceTimelineBuilder,
)


def test_valid_lookup_entry_round_trip_deterministic_id_and_tampering() -> None:
    parts = _lookup_parts()
    entry = parts.entry

    assert ReplayMarketEvidenceLookupEntry.model_validate(
        entry.model_dump(mode="json")
    ) == entry
    assert build_replay_market_evidence_lookup_entry_id(
        evidence_timeline_id=entry.evidence_timeline_id,
        market_lookup_authority_fingerprint=entry.market_lookup_authority_fingerprint,
        evidence_builder_fingerprint=entry.evidence_builder_fingerprint,
        event_id=entry.event_id,
        event_order_index=entry.event_order_index,
        event_time=entry.event_time,
        event_kind=entry.event_kind,
        evidence_projection_id=entry.evidence_projection_id,
        evidence_set_id=entry.evidence_set_id,
        market_frame_projection_id=entry.market_frame_projection_id,
        market_lookup_entry_id=entry.market_lookup_entry_id,
    ) == entry.entry_id

    with pytest.raises(ValidationError, match="entry_id"):
        ReplayMarketEvidenceLookupEntry.model_validate(
            {
                **entry.model_dump(mode="json"),
                "entry_id": {
                    "value": "replay-market-evidence-lookup-entry:" + "0" * 64
                },
            }
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("entry_id", {"value": "wrong:" + "0" * 64}, "entry_id"),
        ("evidence_timeline_id", {"value": "wrong:" + "0" * 64}, "timeline"),
        ("evidence_projection_id", {"value": "wrong:" + "0" * 64}, "projection"),
        ("evidence_set_id", {"value": "wrong:" + "0" * 64}, "evidence_set"),
        (
            "market_frame_projection_id",
            {"value": "wrong:" + "0" * 64},
            "market_frame",
        ),
        ("market_lookup_entry_id", {"value": "wrong:" + "0" * 64}, "market_lookup"),
    ),
)
def test_lookup_entry_rejects_wrong_id_prefixes(
    field: str,
    value: object,
    match: str,
) -> None:
    payload = _lookup_parts().entry.model_dump(mode="json")
    payload[field] = value

    with pytest.raises(ValidationError, match=match):
        ReplayMarketEvidenceLookupEntry.model_validate(payload)


def test_lookup_entry_builder_derives_from_complete_projection() -> None:
    parts = _lookup_parts()
    rebuilt = build_replay_market_evidence_lookup_entry(
        evidence_timeline_id=parts.timeline.evidence_timeline_id,
        market_lookup_authority_fingerprint=(
            parts.timeline.market_lookup_authority.lookup_authority_fingerprint
        ),
        evidence_builder_fingerprint=parts.timeline.evidence_builder.builder_fingerprint,
        projection=parts.projection,
    )

    assert rebuilt == parts.entry
    assert rebuilt.event_id == parts.projection.market_lookup_entry.event_id
    assert rebuilt.evidence_set_id == parts.projection.evidence_set.evidence_set_id


def test_valid_lookup_authority_descriptor_and_result_round_trip() -> None:
    parts = _lookup_parts()

    assert ReplayMarketEvidenceLookupAuthority.model_validate(
        parts.authority.model_dump(mode="json")
    ) == parts.authority
    assert build_replay_market_evidence_lookup_authority_fingerprint(
        evidence_timeline_id=parts.authority.evidence_timeline_id,
        market_lookup_authority_fingerprint=(
            parts.authority.market_lookup_authority_fingerprint
        ),
        evidence_builder_fingerprint=parts.authority.evidence_builder_fingerprint,
        replay_timeline_id=parts.authority.replay_timeline_id,
        replay_plan_id=parts.authority.replay_plan_id,
        supported_event_kinds=parts.authority.supported_event_kinds,
        entries=parts.authority.entries,
    ) == parts.authority.lookup_authority_fingerprint
    assert build_replay_market_evidence_lookup_descriptor(parts.authority) == (
        parts.descriptor
    )
    assert ReplayMarketEvidenceLookupDescriptor.model_validate(
        parts.descriptor.model_dump(mode="json")
    ) == parts.descriptor
    assert ReplayMarketEvidenceLookupResult.model_validate(
        parts.result.model_dump(mode="json")
    ) == parts.result


def test_lookup_authority_rejects_stale_fingerprint_and_invalid_membership() -> None:
    authority = _lookup_parts().authority

    with pytest.raises(ValidationError, match="lookup_authority_fingerprint"):
        ReplayMarketEvidenceLookupAuthority.model_validate(
            {
                **authority.model_dump(mode="json"),
                "lookup_authority_fingerprint": (
                    "replay-market-evidence-lookup-authority:" + "0" * 64
                ),
            }
        )

    duplicate = _entry_variant(
        authority.entries[0],
        event_id="event-2",
        event_order_index=1,
    )
    with pytest.raises((ValidationError, ValueError)):
        build_replay_market_evidence_lookup_authority_fingerprint(
            evidence_timeline_id=authority.evidence_timeline_id,
            market_lookup_authority_fingerprint=(
                authority.market_lookup_authority_fingerprint
            ),
            evidence_builder_fingerprint=authority.evidence_builder_fingerprint,
            replay_timeline_id=authority.replay_timeline_id,
            replay_plan_id=authority.replay_plan_id,
            supported_event_kinds=authority.supported_event_kinds,
            entries=(authority.entries[0], duplicate),
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("duplicate_event_id", "event_id"),
        ("duplicate_event_order_index", "event_order_index"),
        ("duplicate_event_key", "event_id|event key"),
        ("duplicate_entry_id", "entry_id"),
        ("duplicate_evidence_projection_id", "evidence_projection_id"),
        ("duplicate_evidence_set_id", "evidence_set_id"),
        ("duplicate_market_frame_projection_id", "market_frame_projection_id"),
        ("duplicate_market_lookup_entry_id", "market_lookup_entry_id"),
        ("non_canonical_order", "sorted"),
    ),
)
def test_lookup_authority_rejects_duplicate_membership(
    mutation: str,
    match: str,
) -> None:
    authority = _lookup_parts().authority
    first = authority.entries[0]
    second = _entry_variant(
        first,
        event_id="event-2",
        event_order_index=1,
        evidence_projection_id=ReplayMarketEvidenceProjectionId(
            value="replay-market-evidence-projection:" + "1" * 64
        ),
        evidence_set_id=MarketEvidenceSetId(
            value="market-evidence-set:" + "2" * 64
        ),
        market_frame_projection_id=ReplayMarketFrameProjectionId(
            value="replay-market-frame-projection:" + "3" * 64
        ),
        market_lookup_entry_id=ReplayMarketFrameLookupEntryId(
            value="replay-market-frame-lookup-entry:" + "4" * 64
        ),
    )
    if mutation == "duplicate_event_id":
        second = _entry_variant(second, event_id=first.event_id)
    elif mutation == "duplicate_event_order_index":
        second = _entry_variant(second, event_order_index=first.event_order_index)
    elif mutation == "duplicate_event_key":
        second = _entry_variant(
            second,
            event_id=first.event_id,
            event_order_index=first.event_order_index,
        )
    elif mutation == "duplicate_entry_id":
        second = first
    elif mutation == "duplicate_evidence_projection_id":
        second = _entry_variant(
            second,
            evidence_projection_id=first.evidence_projection_id,
        )
    elif mutation == "duplicate_evidence_set_id":
        second = _entry_variant(second, evidence_set_id=first.evidence_set_id)
    elif mutation == "duplicate_market_frame_projection_id":
        second = _entry_variant(
            second,
            market_frame_projection_id=first.market_frame_projection_id,
        )
    elif mutation == "duplicate_market_lookup_entry_id":
        second = _entry_variant(
            second,
            market_lookup_entry_id=first.market_lookup_entry_id,
        )
    entries = (first, second)
    if mutation == "non_canonical_order":
        entries = (second, first)

    with pytest.raises((ValidationError, ValueError), match=match):
        ReplayMarketEvidenceLookupAuthority.model_validate(
            _authority_payload(authority, entries)
        )


def test_result_and_membership_reject_changed_entry_projection_and_absent_entry() -> None:
    parts = _lookup_parts()
    other = _lookup_parts(price="101.00")

    with pytest.raises((ValidationError, ValueError)):
        build_replay_market_evidence_lookup_result(
            descriptor=parts.descriptor,
            entry=parts.entry,
            projection=other.projection,
        )
    changed_entry = _entry_variant(
        parts.entry,
        event_id=parts.entry.event_id,
        evidence_set_id=MarketEvidenceSetId(
            value="market-evidence-set:" + "8" * 64
        ),
    )
    with pytest.raises((ValidationError, ValueError)):
        build_replay_market_evidence_lookup_result(
            descriptor=parts.descriptor,
            entry=changed_entry,
            projection=parts.projection,
        )
    absent_result = ReplayMarketEvidenceLookupResult.model_construct(
        descriptor=parts.descriptor,
        entry=other.entry,
        projection=other.projection,
    )
    with pytest.raises((ValidationError, ValueError)):
        validate_replay_market_evidence_lookup_membership(
            authority=parts.authority,
            result=absent_result,
        )
    same_key_changed = ReplayMarketEvidenceLookupResult.model_construct(
        descriptor=parts.descriptor,
        entry=changed_entry,
        projection=parts.projection,
    )
    with pytest.raises((ValidationError, ValueError)):
        validate_replay_market_evidence_lookup_membership(
            authority=parts.authority,
            result=same_key_changed,
        )


def test_local_lookup_snapshots_exposes_snapshots_and_exact_event_lookup() -> None:
    parts = _lookup_parts()
    lookup = LocalReplayMarketEvidenceLookup(parts.timeline)
    result = lookup.lookup(parts.fixture.dispatch_context, parts.fixture.event)
    authority_snapshot = lookup.authority
    descriptor_snapshot = lookup.descriptor

    assert result == parts.result
    assert type(authority_snapshot) is ReplayMarketEvidenceLookupAuthority
    assert type(descriptor_snapshot) is ReplayMarketEvidenceLookupDescriptor
    object.__setattr__(authority_snapshot, "entries", ())
    object.__setattr__(descriptor_snapshot, "supported_event_kinds", ())
    assert lookup.authority.entries == parts.authority.entries
    assert lookup.descriptor.supported_event_kinds == parts.descriptor.supported_event_kinds


@pytest.mark.parametrize(
    ("context_update", "event_update", "match"),
    (
        ({"timeline_id": "other-timeline"}, {}, "timeline"),
        ({"replay_plan_id": "other-plan"}, {}, "plan"),
        ({"event_id": "missing-event"}, {"event_id": "missing-event"}, "no replay"),
        (
            {"event_order_index": 99},
            {"order_index": 99},
            "no replay",
        ),
        (
            {"event_time": datetime(2026, 1, 1, 13, tzinfo=UTC)},
            {"event_time": datetime(2026, 1, 1, 13, tzinfo=UTC)},
            "event_time",
        ),
        (
            {"event_kind": ReplayInputKind.TRADE},
            {"kind": ReplayInputKind.TRADE},
            "kind",
        ),
        ({}, {"event_id": "other-event"}, "context event_id"),
    ),
)
def test_local_lookup_rejects_context_event_and_lookup_mismatches(
    context_update: dict[str, object],
    event_update: dict[str, object],
    match: str,
) -> None:
    parts = _lookup_parts()
    lookup = LocalReplayMarketEvidenceLookup(parts.timeline)

    with pytest.raises(ValueError, match=match):
        lookup.lookup(
            parts.fixture.dispatch_context.model_copy(update=context_update),
            parts.fixture.event.model_copy(update=event_update),
        )


def test_local_lookup_rejects_ambiguous_or_malformed_timeline() -> None:
    parts = _lookup_parts()
    malformed = ReplayMarketEvidenceTimeline.model_construct(
        **{
            **parts.timeline.model_dump(),
            "projections": (parts.timeline.projections[0], parts.timeline.projections[0]),
        }
    )

    with pytest.raises((ValidationError, ValueError)):
        LocalReplayMarketEvidenceLookup(malformed)


def test_local_lookup_validates_membership_before_return(monkeypatch: pytest.MonkeyPatch) -> None:
    parts = _lookup_parts()
    lookup = LocalReplayMarketEvidenceLookup(parts.timeline)

    def _reject_membership(**kwargs: object) -> None:
        raise ValueError("membership checked")

    monkeypatch.setattr(
        replay_lookup_module,
        "validate_replay_market_evidence_lookup_membership",
        _reject_membership,
    )

    with pytest.raises(ValueError, match="membership checked"):
        lookup.lookup(parts.fixture.dispatch_context, parts.fixture.event)


def test_local_lookup_is_deterministic_and_changes_with_timeline() -> None:
    first = _lookup_parts()
    same = _lookup_parts()
    changed = _lookup_parts(price="101.00")

    assert first.result == same.result
    assert first.authority == same.authority
    assert first.descriptor == same.descriptor
    assert first.authority != changed.authority
    assert first.descriptor != changed.descriptor
    assert first.result != changed.result


def test_local_lookup_external_mutation_after_construction_cannot_affect_lookup() -> None:
    parts = _lookup_parts()
    lookup = LocalReplayMarketEvidenceLookup(parts.timeline)
    object.__setattr__(parts.timeline, "projections", ())

    assert lookup.lookup(parts.fixture.dispatch_context, parts.fixture.event) == parts.result


def test_local_lookup_accepts_exact_dict_and_rejects_custom_mapping() -> None:
    parts = _lookup_parts()
    payload: Any = parts.timeline.model_dump(mode="json")
    lookup = LocalReplayMarketEvidenceLookup(payload)

    assert lookup.lookup(parts.fixture.dispatch_context, parts.fixture.event) == parts.result
    custom_mapping: Any = UserDict(parts.timeline.model_dump(mode="json"))
    with pytest.raises(ValueError, match="exact built-in dict"):
        LocalReplayMarketEvidenceLookup(custom_mapping)


def test_authority_and_descriptor_properties_reject_stateful_subclasses() -> None:
    parts = _lookup_parts()
    lookup = LocalReplayMarketEvidenceLookup(parts.timeline)
    authority = _FlippingAuthority.model_validate(
        parts.authority.model_dump(mode="json")
    )
    descriptor = _FlippingDescriptor.model_validate(
        parts.descriptor.model_dump(mode="json")
    )
    object.__setattr__(lookup, "_authority", authority)
    object.__setattr__(lookup, "_descriptor", descriptor)

    with pytest.raises(ValueError, match="expected exact ReplayMarketEvidenceLookupAuthority"):
        _ = lookup.authority
    with pytest.raises(ValueError, match="expected exact ReplayMarketEvidenceLookupDescriptor"):
        _ = lookup.descriptor
    assert authority.dump_count == 1
    assert descriptor.dump_count == 1


def test_timeline_subclass_model_dump_self_rejected() -> None:
    bad = _SelfDumpTimeline.model_validate(_lookup_parts().timeline.model_dump(mode="json"))

    with pytest.raises(ValueError, match="inert plain data"):
        LocalReplayMarketEvidenceLookup(bad)
    assert bad.dump_count == 1


def test_timeline_subclass_first_dump_valid_later_forged_only_dumped_once() -> None:
    parts = _lookup_parts()
    flaky = _FlippingTimeline.model_validate(parts.timeline.model_dump(mode="json"))

    with pytest.raises(ValueError, match="expected exact ReplayMarketEvidenceTimeline"):
        LocalReplayMarketEvidenceLookup(flaky)
    assert flaky.dump_count == 1


def test_nested_custom_object_inside_timeline_dump_rejected() -> None:
    bad = _CustomDumpTimeline.model_validate(_lookup_parts().timeline.model_dump(mode="json"))

    with pytest.raises(ValueError):
        LocalReplayMarketEvidenceLookup(bad)


def test_context_and_event_subclasses_rejected_after_single_dump() -> None:
    parts = _lookup_parts()
    lookup = LocalReplayMarketEvidenceLookup(parts.timeline)
    context = _FlippingDispatchContext.model_validate(
        parts.fixture.dispatch_context.model_dump(mode="json")
    )
    event = _FlippingTimelineEvent.model_validate(
        parts.fixture.event.model_dump(mode="json")
    )

    with pytest.raises(ValueError, match="expected exact ReplayDispatchContext"):
        lookup.lookup(context, parts.fixture.event)
    with pytest.raises(ValueError, match="expected exact ReplayTimelineEvent"):
        lookup.lookup(parts.fixture.dispatch_context, event)
    assert context.dump_count == 1
    assert event.dump_count == 1


def test_no_decision_stack_fields_in_lookup_payloads() -> None:
    rendered = repr(_lookup_parts().result.model_dump(mode="json"))
    forbidden = {
        "DecisionStack",
        "ReplayDecisionStackContext",
        "DecisionIntent",
        "NoTradeDecision",
        "ReplayDecisionOutputEnvelope",
        "ReplayDecisionMarketContextReference",
        "RiskBehaviorModel",
        "HardRiskGate",
        "ExecutionIntent",
        "OrderIntent",
        "Ledger",
        "PnL",
    }
    for name in forbidden:
        assert name not in rendered


class _LookupParts:
    def __init__(self, *, price: str = "100.00") -> None:
        self.fixture = replay_decision_market_fixture(price=price)
        self.timeline = DeterministicReplayMarketEvidenceTimelineBuilder().build(
            self.fixture.market_timeline
        )
        self.authority = build_replay_market_evidence_lookup_authority(self.timeline)
        self.descriptor = build_replay_market_evidence_lookup_descriptor(self.authority)
        self.entry = self.authority.entries[0]
        self.projection = self.timeline.projections[0]
        self.result = build_replay_market_evidence_lookup_result(
            descriptor=self.descriptor,
            entry=self.entry,
            projection=self.projection,
        )
        validate_replay_market_evidence_lookup_membership(
            authority=self.authority,
            result=self.result,
        )


class _SelfDumpTimeline(ReplayMarketEvidenceTimeline):
    dump_count: int = 0

    def model_dump(self, *args: Any, **kwargs: Any) -> BaseModel:
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        return self


class _FlippingTimeline(ReplayMarketEvidenceTimeline):
    dump_count: int = 0

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, object]:
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        dumped = super().model_dump(*args, **kwargs)
        if self.dump_count > 1:
            dumped["projections"] = []
        return dumped


class _FlippingAuthority(ReplayMarketEvidenceLookupAuthority):
    dump_count: int = 0

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, object]:
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        dumped = super().model_dump(*args, **kwargs)
        if self.dump_count > 1:
            dumped["entries"] = []
        return dumped


class _FlippingDescriptor(ReplayMarketEvidenceLookupDescriptor):
    dump_count: int = 0

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, object]:
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        dumped = super().model_dump(*args, **kwargs)
        if self.dump_count > 1:
            dumped["supported_event_kinds"] = []
        return dumped


class _CustomDumpTimeline(ReplayMarketEvidenceTimeline):
    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, object]:
        dumped = super().model_dump(*args, **kwargs)
        dumped["market_lookup_authority"] = object()
        return dumped


class _FlippingDispatchContext(ReplayDispatchContext):
    dump_count: int = 0

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, object]:
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        dumped = super().model_dump(*args, **kwargs)
        if self.dump_count > 1:
            dumped["event_id"] = "forged"
        return dumped


class _FlippingTimelineEvent(ReplayTimelineEvent):
    dump_count: int = 0

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, object]:
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        dumped = super().model_dump(*args, **kwargs)
        if self.dump_count > 1:
            dumped["event_id"] = "forged"
        return dumped


def _lookup_parts(*, price: str = "100.00") -> _LookupParts:
    return _LookupParts(price=price)


def _authority_payload(
    authority: ReplayMarketEvidenceLookupAuthority,
    entries: tuple[ReplayMarketEvidenceLookupEntry, ...],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "evidence_timeline_id": authority.evidence_timeline_id.model_dump(mode="json"),
        "market_lookup_authority_fingerprint": (
            authority.market_lookup_authority_fingerprint
        ),
        "evidence_builder_fingerprint": authority.evidence_builder_fingerprint,
        "replay_timeline_id": authority.replay_timeline_id,
        "replay_plan_id": authority.replay_plan_id,
        "supported_event_kinds": [
            kind.value for kind in authority.supported_event_kinds
        ],
        "entries": [entry.model_dump(mode="json") for entry in entries],
        "lookup_authority_fingerprint": (
            "replay-market-evidence-lookup-authority:" + "0" * 64
        ),
    }


def _entry_variant(  # noqa: PLR0913
    entry: ReplayMarketEvidenceLookupEntry,
    *,
    event_id: str | None = None,
    event_order_index: int | None = None,
    evidence_projection_id: ReplayMarketEvidenceProjectionId | None = None,
    evidence_set_id: MarketEvidenceSetId | None = None,
    market_frame_projection_id: ReplayMarketFrameProjectionId | None = None,
    market_lookup_entry_id: ReplayMarketFrameLookupEntryId | None = None,
) -> ReplayMarketEvidenceLookupEntry:
    event_id = event_id if event_id is not None else entry.event_id
    event_order_index = (
        event_order_index
        if event_order_index is not None
        else entry.event_order_index
    )
    evidence_projection_id = evidence_projection_id or entry.evidence_projection_id
    evidence_set_id = evidence_set_id or entry.evidence_set_id
    market_frame_projection_id = (
        market_frame_projection_id or entry.market_frame_projection_id
    )
    market_lookup_entry_id = market_lookup_entry_id or entry.market_lookup_entry_id
    entry_id = build_replay_market_evidence_lookup_entry_id(
        evidence_timeline_id=entry.evidence_timeline_id,
        market_lookup_authority_fingerprint=(
            entry.market_lookup_authority_fingerprint
        ),
        evidence_builder_fingerprint=entry.evidence_builder_fingerprint,
        event_id=event_id,
        event_order_index=event_order_index,
        event_time=entry.event_time,
        event_kind=entry.event_kind,
        evidence_projection_id=evidence_projection_id,
        evidence_set_id=evidence_set_id,
        market_frame_projection_id=market_frame_projection_id,
        market_lookup_entry_id=market_lookup_entry_id,
    )
    return entry.model_copy(
        update={
            "entry_id": entry_id,
            "event_id": event_id,
            "event_order_index": event_order_index,
            "evidence_projection_id": evidence_projection_id,
            "evidence_set_id": evidence_set_id,
            "market_frame_projection_id": market_frame_projection_id,
            "market_lookup_entry_id": market_lookup_entry_id,
        }
    )
