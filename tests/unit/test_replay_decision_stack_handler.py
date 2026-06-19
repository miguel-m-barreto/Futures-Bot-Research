from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest
from tests.unit.replay_decision_market_fixtures import (
    replay_decision_market_fixture,
)
from tests.unit.replay_decision_market_fixtures import (
    stack_descriptor as fixture_stack_descriptor,
)

from futures_bot.decision.journal import LocalReplayDecisionJournal
from futures_bot.decision.replay_adapter import (
    ReplayDecisionStackHandler,
    _snapshot_evidence_lookup_result,
    _snapshot_market_lookup_result,
)
from futures_bot.domain.decisions import (
    DecisionIntent,
    DecisionIntentStatus,
    DecisionSourceKind,
    NoTradeDecision,
    NoTradeReasonKind,
    ProposedAction,
    TradeSide,
)
from futures_bot.domain.ids import DecisionIntentId
from futures_bot.domain.instruments import InstrumentSymbol
from futures_bot.domain.market_data import MarkPriceObservationPayload
from futures_bot.domain.replay import (
    ReplayDispatchContext,
    ReplayInputKind,
    ReplayTimelineEvent,
    build_replay_event_dispatch_receipt_id,
)
from futures_bot.domain.replay_decisions import (
    ReplayDecisionOutputEnvelope,
    ReplayDecisionOutputKind,
    ReplayDecisionStackContext,
    build_replay_decision_evidence_context_reference,
    build_replay_decision_handler_fingerprint,
    build_replay_decision_intent_id,
    build_replay_decision_market_context_reference,
    build_replay_decision_stack_context,
    decode_replay_decision_output_record,
)
from futures_bot.domain.replay_evidence import (
    ReplayMarketEvidenceLookupResult,
)
from futures_bot.domain.replay_market_data import (
    ReplayMarketFrameLookupAuthority,
    ReplayMarketFrameLookupDescriptor,
    ReplayMarketFrameLookupResult,
    build_replay_market_frame_lookup_entry,
)
from futures_bot.infrastructure.replay.in_memory import InMemoryReplayEventOutputRecordStore
from futures_bot.replay.dispatch import LocalDeterministicReplayDispatcher


class _LookupSpy:
    def __init__(self, fixture) -> None:
        self._authority = fixture.lookup.authority
        self._descriptor = fixture.lookup.descriptor
        self._result = fixture.decision_context.market
        self.calls = 0
        self.mutate_descriptor = False
        self.mutate_authority = False
        self.mutate_descriptor_during_lookup = False
        self.mutate_authority_during_lookup = False
        self.on_lookup: Callable[[ReplayDispatchContext, ReplayTimelineEvent], None] | None = (
            None
        )

    @property
    def authority(self):
        if self.mutate_authority:
            return self._authority.model_copy(update={"replay_plan_id": "other-plan"})
        return self._authority

    @property
    def descriptor(self):
        if self.mutate_descriptor:
            return self._descriptor.model_copy(update={"replay_plan_id": "other-plan"})
        return self._descriptor

    def lookup(self, context, event):
        self.calls += 1
        if self.on_lookup is not None:
            self.on_lookup(context, event)
        if self.mutate_descriptor_during_lookup:
            self.mutate_descriptor = True
        if self.mutate_authority_during_lookup:
            self.mutate_authority = True
        return self._result


class _EvidenceLookupSpy:
    def __init__(self, fixture) -> None:
        self._authority = fixture.evidence_lookup.authority
        self._descriptor = fixture.evidence_lookup.descriptor
        self._result = fixture.decision_context.evidence
        self.calls = 0
        self.mutate_descriptor = False
        self.mutate_authority = False
        self.mutate_descriptor_during_lookup = False
        self.mutate_authority_during_lookup = False
        self.on_lookup: Callable[[ReplayDispatchContext, ReplayTimelineEvent], None] | None = (
            None
        )

    @property
    def authority(self):
        if self.mutate_authority:
            return self._authority.model_copy(update={"replay_plan_id": "other-plan"})
        return self._authority

    @property
    def descriptor(self):
        if self.mutate_descriptor:
            return self._descriptor.model_copy(update={"replay_plan_id": "other-plan"})
        return self._descriptor

    def lookup(self, context, event):
        self.calls += 1
        if self.on_lookup is not None:
            self.on_lookup(context, event)
        if self.mutate_descriptor_during_lookup:
            self.mutate_descriptor = True
        if self.mutate_authority_during_lookup:
            self.mutate_authority = True
        return self._result


class _StatefulLookupResult(ReplayMarketFrameLookupResult):
    dump_count: int = 0
    first_payload: object
    later_payload: object

    def model_dump(self, *args, **kwargs):
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        if self.dump_count == 1:
            return self.first_payload
        return self.later_payload


class _StatefulEvidenceLookupResult(ReplayMarketEvidenceLookupResult):
    dump_count: int = 0
    first_payload: object
    later_payload: object

    def model_dump(self, *args, **kwargs):
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        if self.dump_count == 1:
            return self.first_payload
        return self.later_payload


class _SelfThenChangingLookupResult(ReplayMarketFrameLookupResult):
    dump_count: int = 0
    legitimate_payload: object
    forged_payload: object

    def model_dump(self, *args, **kwargs):
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        if self.dump_count == 1:
            return self
        if self.dump_count == 2:
            return self.legitimate_payload
        return self.forged_payload


class _DumpPayloadLookupDescriptor(ReplayMarketFrameLookupDescriptor):
    dump_count: int = 0
    payload: object | None = None
    return_self: bool = False

    def model_dump(self, *args, **kwargs):
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        if self.return_self:
            return self
        return self.payload


class _DumpPayloadLookupAuthority(ReplayMarketFrameLookupAuthority):
    dump_count: int = 0
    payload: object | None = None
    return_self: bool = False

    def model_dump(self, *args, **kwargs):
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        if self.return_self:
            return self
        return self.payload


class _DumpPayloadDispatchContext(ReplayDispatchContext):
    dump_count: int = 0
    payload: object | None = None
    return_self: bool = False

    def model_dump(self, *args, **kwargs):
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        if self.return_self:
            return self
        return self.payload


class _DumpPayloadTimelineEvent(ReplayTimelineEvent):
    dump_count: int = 0
    payload: object | None = None
    return_self: bool = False

    def model_dump(self, *args, **kwargs):
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        if self.return_self:
            return self
        return self.payload


class _DumpPayloadDecisionIntent(DecisionIntent):
    dump_count: int = 0
    payload: object | None = None
    return_self: bool = False
    on_dump: Callable[[], None] | None = None

    def model_dump(self, *args, **kwargs):
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        if self.on_dump is not None:
            self.on_dump()
        if self.return_self:
            return self
        return self.payload


class _DumpPayloadNoTradeDecision(NoTradeDecision):
    dump_count: int = 0
    payload: object | None = None
    return_self: bool = False
    on_dump: Callable[[], None] | None = None

    def model_dump(self, *args, **kwargs):
        object.__setattr__(self, "dump_count", self.dump_count + 1)
        if self.on_dump is not None:
            self.on_dump()
        if self.return_self:
            return self
        return self.payload


class _CustomDict(dict):
    pass


class _CustomList(list):
    pass


class _CustomMapping(Mapping[object, object]):
    def __init__(self, payload: Mapping[str, object]) -> None:
        self._payload = cast(dict[object, object], dict(payload))

    def __getitem__(self, key: object) -> object:
        return self._payload[key]

    def __iter__(self) -> Iterator[object]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)


class _ValidationTrap:
    def __init__(self) -> None:
        self.model_validate_calls = 0
        self.model_dump_calls = 0

    def model_dump(self):
        self.model_dump_calls += 1
        return {}

    def model_validate(self, value):
        self.model_validate_calls += 1
        return value


class _Stack:
    def __init__(self, fixture) -> None:
        descriptor = fixture.stack_descriptor
        self.stack_id = descriptor.stack_id
        self.stack_version = descriptor.stack_version
        self.bot_id = descriptor.bot_id
        self.source_kind = descriptor.source_kind
        self.supported_event_kinds = descriptor.supported_event_kinds
        self.calls = 0
        self.received: ReplayDecisionStackContext | None = None
        self.outputs: tuple[DecisionIntent | NoTradeDecision, ...] = ()
        self.fail = False
        self.exception: Exception | None = None
        self.mutate_during_decide: tuple[str, object] | None = None
        self.on_decide: Callable[[], None] | None = None
        self.on_decide_context: Callable[[ReplayDecisionStackContext], None] | None = None
        self.output_factory: (
            Callable[
                [ReplayDecisionStackContext],
                tuple[DecisionIntent | NoTradeDecision, ...],
            ]
            | None
        ) = None

    def descriptor(self):
        return fixture_stack_descriptor(
            stack_id=self.stack_id,
            stack_version=self.stack_version,
            bot_id=self.bot_id,
            source_kind=self.source_kind,
            supported_event_kinds=self.supported_event_kinds,
        )

    def intent(
        self,
        context: ReplayDecisionStackContext,
        index: int = 0,
        *,
        status: DecisionIntentStatus = DecisionIntentStatus.PROPOSED,
        decision_intent_id: DecisionIntentId | None = None,
    ) -> DecisionIntent:
        return DecisionIntent(
            decision_intent_id=decision_intent_id or decision_id_for_context(context, index),
            bot_id=self.bot_id,
            instrument=InstrumentSymbol("BTC/USDT"),
            side=TradeSide.LONG,
            proposed_action=ProposedAction.OPEN_POSITION,
            source_kind=self.source_kind,
            source_id=self.stack_id,
            created_at=context.event.event_time,
            confidence=Decimal("0.8"),
            status=status,
        )

    def no_trade(
        self,
        context: ReplayDecisionStackContext,
        index: int = 0,
    ) -> NoTradeDecision:
        return NoTradeDecision(
            decision_intent_id=decision_id_for_context(context, index),
            bot_id=self.bot_id,
            instrument=InstrumentSymbol("BTC/USDT"),
            source_kind=self.source_kind,
            source_id=self.stack_id,
            created_at=context.event.event_time,
            reasons=(NoTradeReasonKind.MARKET_TOO_UNCERTAIN,),
        )

    def decide(
        self,
        context: ReplayDecisionStackContext,
    ) -> tuple[DecisionIntent | NoTradeDecision, ...]:
        self.calls += 1
        self.received = context
        if self.exception is not None:
            raise self.exception
        if self.fail:
            raise ValueError("boom")
        if self.mutate_during_decide is not None:
            field_name, value = self.mutate_during_decide
            setattr(self, field_name, value)
        if self.on_decide is not None:
            self.on_decide()
        if self.on_decide_context is not None:
            self.on_decide_context(context)
        if self.output_factory is not None:
            return self.output_factory(context)
        return self.outputs


def decision_id_for_context(context: ReplayDecisionStackContext, index: int):
    descriptor = fixture_stack_descriptor()
    return build_replay_decision_intent_id(
        run_id=context.dispatch_context.run_id,
        event_order_index=context.dispatch_context.event_order_index,
        event_id=context.dispatch_context.event_id,
        decision_handler_fingerprint=build_replay_decision_handler_fingerprint(
            stack_descriptor=descriptor,
            market_lookup_descriptor=context.market.descriptor,
            evidence_lookup_descriptor=context.evidence.descriptor,
        ),
        market_context_reference_id=build_replay_decision_market_context_reference(
            context
        ).reference_id,
        evidence_context_reference_id=build_replay_decision_evidence_context_reference(
            context
        ).reference_id,
        decision_index=index,
    )


def _handler_bundle():
    fixture = replay_decision_market_fixture()
    lookup = _LookupSpy(fixture)
    evidence_lookup = _EvidenceLookupSpy(fixture)
    stack = _Stack(fixture)
    handler = ReplayDecisionStackHandler(stack, lookup, evidence_lookup)
    return fixture, lookup, evidence_lookup, stack, handler


def test_snapshot_market_lookup_result_accepts_base_mapping_and_subclass_once() -> None:
    fixture = replay_decision_market_fixture()
    result = fixture.decision_context.market
    from_base = _snapshot_market_lookup_result(result)
    from_mapping = _snapshot_market_lookup_result(result.model_dump(mode="json"))
    changed = replay_decision_market_fixture(price="101")
    stateful = _StatefulLookupResult(
        **result.model_dump(mode="json"),
        first_payload=result.model_dump(mode="json"),
        later_payload=changed.decision_context.market.model_dump(mode="json"),
    )

    from_subclass = _snapshot_market_lookup_result(stateful)

    assert type(from_base) is ReplayMarketFrameLookupResult
    assert type(from_mapping) is ReplayMarketFrameLookupResult
    assert type(from_subclass) is ReplayMarketFrameLookupResult
    assert from_subclass == result
    assert stateful.dump_count == 1


def test_snapshot_evidence_lookup_result_accepts_base_mapping_and_subclass_once() -> None:
    fixture = replay_decision_market_fixture()
    result = fixture.decision_context.evidence
    from_base = _snapshot_evidence_lookup_result(result)
    from_mapping = _snapshot_evidence_lookup_result(result.model_dump(mode="json"))
    changed = replay_decision_market_fixture(price="101")
    stateful = _StatefulEvidenceLookupResult(
        **result.model_dump(mode="json"),
        first_payload=result.model_dump(mode="json"),
        later_payload=changed.decision_context.evidence.model_dump(mode="json"),
    )

    from_subclass = _snapshot_evidence_lookup_result(stateful)

    assert type(from_base) is ReplayMarketEvidenceLookupResult
    assert type(from_mapping) is ReplayMarketEvidenceLookupResult
    assert type(from_subclass) is ReplayMarketEvidenceLookupResult
    assert from_subclass == result
    assert stateful.dump_count == 1


def test_snapshot_market_lookup_result_rejects_tampering_extra_and_arbitrary_object() -> None:
    fixture = replay_decision_market_fixture()
    result = fixture.decision_context.market
    tampered = result.model_copy(
        update={
            "descriptor": result.descriptor.model_copy(
                update={"replay_plan_id": "other-plan"}
            )
        }
    )
    extra = {**result.model_dump(mode="json"), "extra": "field"}
    trap = _ValidationTrap()

    with pytest.raises(ValueError):
        _snapshot_market_lookup_result(tampered)
    with pytest.raises(ValueError):
        _snapshot_market_lookup_result(extra)
    with pytest.raises(ValueError):
        _snapshot_market_lookup_result(trap)
    assert trap.model_dump_calls == 0
    assert trap.model_validate_calls == 0


def test_snapshot_market_lookup_result_rejects_self_dumping_subclass_once() -> None:
    fixture = replay_decision_market_fixture()
    changed = replay_decision_market_fixture(price="101")
    result = fixture.decision_context.market
    stateful = _SelfThenChangingLookupResult(
        **result.model_dump(mode="json"),
        legitimate_payload=result.model_dump(mode="json"),
        forged_payload=changed.decision_context.market.model_dump(mode="json"),
    )

    with pytest.raises(ValueError, match="plain JSON"):
        _snapshot_market_lookup_result(stateful)

    assert stateful.dump_count == 1


def test_snapshot_market_lookup_result_rejects_nested_custom_objects() -> None:
    fixture = replay_decision_market_fixture()
    result = fixture.decision_context.market
    payloads = []

    descriptor_payload = result.model_dump(mode="json")
    descriptor_payload["descriptor"] = result.descriptor
    payloads.append(descriptor_payload)

    entry_payload = result.model_dump(mode="json")
    entry_payload["entry"] = _CustomMapping(entry_payload["entry"])
    payloads.append(entry_payload)

    projection_payload = result.model_dump(mode="json")
    projection_payload["observation_projection"] = result.observation_projection
    payloads.append(projection_payload)

    frame_projection_payload = result.model_dump(mode="json")
    frame_projection_payload["frame_projection"] = result.frame_projection
    payloads.append(frame_projection_payload)

    nested_observation_payload = result.model_dump(mode="json")
    nested_observation_payload["frame_projection"]["frame"]["observations"][0][
        "payload"
    ] = _ValidationTrap()
    payloads.append(nested_observation_payload)

    for payload in payloads:
        stateful = _StatefulLookupResult(
            **result.model_dump(mode="json"),
            first_payload=payload,
            later_payload=result.model_dump(mode="json"),
        )

        with pytest.raises(ValueError, match="plain JSON"):
            _snapshot_market_lookup_result(stateful)

        assert stateful.dump_count == 1


def test_snapshot_market_lookup_result_requires_exact_plain_dict_mapping() -> None:
    fixture = replay_decision_market_fixture()
    result = fixture.decision_context.market
    payload = result.model_dump(mode="json")

    snapshot = _snapshot_market_lookup_result(payload)

    assert type(snapshot) is ReplayMarketFrameLookupResult
    assert snapshot == result

    bad_non_string_key = cast(
        dict[object, object],
        dict(result.model_dump(mode="json")),
    )
    bad_non_string_key[1] = "bad"
    bad_values = (
        _CustomDict(payload),
        _CustomMapping(payload),
        tuple(payload.items()),
        {**payload, "bad": datetime.now(UTC)},
        {**payload, "bad": Decimal("1")},
        {**payload, "bad": result.descriptor},
        {**payload, "bad": _CustomList()},
        bad_non_string_key,
        {**payload, "bad": float("nan")},
        {**payload, "bad": float("inf")},
        {**payload, "bad": float("-inf")},
    )

    for value in bad_values:
        with pytest.raises(ValueError):
            _snapshot_market_lookup_result(value)


def test_handler_structurally_conforms_and_snapshots_descriptors() -> None:
    fixture, lookup, evidence_lookup, stack, handler = _handler_bundle()

    assert handler.handler_id == build_replay_decision_handler_fingerprint(
        stack_descriptor=fixture.stack_descriptor,
        market_lookup_descriptor=lookup.descriptor,
        evidence_lookup_descriptor=evidence_lookup.descriptor,
    )
    assert handler.decision_stack_fingerprint.startswith("decision-stack:")
    assert handler.handler_version == fixture.stack_descriptor.stack_version
    assert handler.market_lookup_descriptor == lookup.descriptor
    assert handler.evidence_lookup_descriptor == evidence_lookup.descriptor

    stack.stack_version = "2"
    assert handler.handler_version == "1"


def test_lookup_called_once_and_stack_receives_exact_frame() -> None:
    fixture, lookup, evidence_lookup, stack, handler = _handler_bundle()
    stack.outputs = (
        stack.intent(fixture.decision_context, 0),
        stack.no_trade(fixture.decision_context, 1),
    )

    proposals = handler.handle(fixture.dispatch_context, fixture.event)

    assert lookup.calls == 1
    assert evidence_lookup.calls == 1
    assert stack.calls == 1
    assert stack.received is not None
    assert stack.received.market.frame_projection.frame == (
        fixture.decision_context.market.frame_projection.frame
    )
    assert stack.received.evidence.projection.evidence_set == (
        fixture.decision_context.evidence.projection.evidence_set
    )
    assert [proposal.output_kind for proposal in proposals] == [
        ReplayDecisionOutputKind.DECISION_INTENT.value,
        ReplayDecisionOutputKind.NO_TRADE_DECISION.value,
    ]


@pytest.mark.parametrize("field_name", ("descriptor", "authority"))
def test_evidence_lookup_metadata_mutation_before_lookup_rejected_without_stack_call(
    field_name: str,
) -> None:
    fixture, lookup, evidence_lookup, stack, handler = _handler_bundle()
    stack.outputs = (stack.intent(fixture.decision_context),)
    setattr(evidence_lookup, f"mutate_{field_name}", True)

    with pytest.raises(ValueError, match=f"evidence lookup {field_name} changed"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert lookup.calls == 0
    assert evidence_lookup.calls == 0
    assert stack.calls == 0


@pytest.mark.parametrize("field_name", ("descriptor", "authority"))
def test_evidence_lookup_metadata_mutation_during_lookup_rejected_before_stack_call(
    field_name: str,
) -> None:
    fixture, lookup, evidence_lookup, stack, handler = _handler_bundle()
    stack.outputs = (stack.intent(fixture.decision_context),)
    setattr(evidence_lookup, f"mutate_{field_name}_during_lookup", True)

    with pytest.raises(ValueError, match=f"evidence lookup {field_name} changed"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert lookup.calls == 1
    assert evidence_lookup.calls == 1
    assert stack.calls == 0


def test_handler_rejects_evidence_lookup_result_from_another_frame_before_stack() -> None:
    fixture, lookup, evidence_lookup, stack, handler = _handler_bundle()
    changed = replay_decision_market_fixture(price="101")
    evidence_lookup._result = changed.decision_context.evidence
    stack.outputs = (stack.intent(fixture.decision_context),)

    with pytest.raises(ValueError, match=r"descriptor changed|market lookup entry"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert lookup.calls == 1
    assert evidence_lookup.calls == 1
    assert stack.calls == 0


def test_stack_decision_with_correct_market_but_wrong_evidence_id_rejected() -> None:
    fixture, _lookup, _evidence_lookup, stack, handler = _handler_bundle()
    wrong_id = build_replay_decision_intent_id(
        run_id=fixture.dispatch_context.run_id,
        event_order_index=fixture.dispatch_context.event_order_index,
        event_id=fixture.dispatch_context.event_id,
        decision_handler_fingerprint=fixture.handler_fingerprint,
        market_context_reference_id=build_replay_decision_market_context_reference(
            fixture.decision_context
        ).reference_id,
        evidence_context_reference_id=(
            "replay-decision-evidence-context-reference:" + "1" * 64
        ),
        decision_index=0,
    )
    stack.outputs = (
        stack.intent(fixture.decision_context, decision_intent_id=wrong_id),
    )

    with pytest.raises(ValueError, match="decision index 0"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert stack.calls == 1


def test_lookup_context_run_id_mutation_does_not_reach_stack_or_envelope() -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    stack.output_factory = lambda context: (stack.intent(context),)
    lookup.on_lookup = lambda context, _event: object.__setattr__(
        context,
        "run_id",
        "forged-run",
    )

    proposals = handler.handle(fixture.dispatch_context, fixture.event)

    assert lookup.calls == 1
    assert stack.calls == 1
    assert stack.received is not None
    assert stack.received.dispatch_context.run_id == fixture.dispatch_context.run_id
    envelope = _proposal_envelope(proposals[0])
    assert envelope.run_id == fixture.dispatch_context.run_id
    assert envelope.market_context_reference.run_id == fixture.dispatch_context.run_id


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("event_id", "forged-event"),
        ("order_index", 99),
        ("event_time", datetime(2026, 1, 2, tzinfo=UTC)),
        ("kind", ReplayInputKind.TRADE),
    ),
)
def test_lookup_event_metadata_mutation_does_not_reach_stack(
    field_name: str,
    value: object,
) -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    stack.output_factory = lambda context: (stack.intent(context),)
    lookup.on_lookup = lambda _context, event: object.__setattr__(
        event,
        field_name,
        value,
    )

    proposals = handler.handle(fixture.dispatch_context, fixture.event)

    assert lookup.calls == 1
    assert stack.calls == 1
    assert stack.received is not None
    assert stack.received.event == fixture.event
    assert stack.received.dispatch_context == fixture.dispatch_context
    envelope = _proposal_envelope(proposals[0])
    assert envelope.event_id == fixture.event.event_id
    assert envelope.event_order_index == fixture.event.order_index
    assert envelope.event_time == fixture.event.event_time
    assert envelope.event_kind == fixture.event.kind


def test_decision_stack_receives_isolated_context_copy() -> None:
    fixture, _lookup, _evidence_lookup, stack, handler = _handler_bundle()
    expected_context = build_replay_decision_stack_context(
        dispatch_context=fixture.dispatch_context,
        event=fixture.event,
        market=fixture.decision_context.market,
        evidence=fixture.decision_context.evidence,
    )
    stack.output_factory = lambda context: (stack.intent(context),)

    proposals = handler.handle(fixture.dispatch_context, fixture.event)

    assert stack.received == expected_context
    assert stack.received is not expected_context
    assert type(stack.received) is ReplayDecisionStackContext
    assert proposals
    assert stack.received is not None
    object.__setattr__(stack.received.dispatch_context, "run_id", "mutated-after")
    envelope = _proposal_envelope(proposals[0])
    assert envelope.run_id == fixture.dispatch_context.run_id
    assert envelope.market_context_reference.run_id == fixture.dispatch_context.run_id


def test_constructor_rejects_stack_kinds_not_supported_by_lookup() -> None:
    fixture = replay_decision_market_fixture()
    lookup = _LookupSpy(fixture)
    evidence_lookup = _EvidenceLookupSpy(fixture)
    stack = _Stack(fixture)
    stack.supported_event_kinds = (*stack.supported_event_kinds, ReplayInputKind.TRADE)

    with pytest.raises(ValueError, match="supported"):
        ReplayDecisionStackHandler(stack, lookup, evidence_lookup)


def test_unsupported_event_rejected_before_lookup_and_stack() -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    unsupported_event = fixture.event.model_copy(update={"kind": ReplayInputKind.TRADE})
    unsupported_context = fixture.dispatch_context.model_copy(
        update={"event_kind": ReplayInputKind.TRADE}
    )

    with pytest.raises(ValueError, match="does not support"):
        handler.handle(unsupported_context, unsupported_event)

    assert lookup.calls == 0
    assert stack.calls == 0


@pytest.mark.parametrize("field_name", ("context", "event"))
@pytest.mark.parametrize("payload_kind", ("self", "nested_model"))
def test_context_and_event_subclasses_rejected_before_lookup(
    field_name: str,
    payload_kind: str,
) -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    if field_name == "context":
        attacker = _dispatch_context_attacker(
            fixture.dispatch_context,
            payload_kind=payload_kind,
            nested_model=fixture.event,
        )
        context = attacker
        event = fixture.event
    else:
        attacker = _timeline_event_attacker(
            fixture.event,
            payload_kind=payload_kind,
            nested_model=fixture.dispatch_context,
        )
        context = fixture.dispatch_context
        event = attacker

    with pytest.raises(ValueError):
        handler.handle(context, event)

    assert lookup.calls == 0
    assert stack.calls == 0
    assert attacker.dump_count == 1


def test_empty_non_tuple_wrong_id_and_wrong_status_are_rejected() -> None:
    fixture, _lookup, _evidence_lookup, stack, handler = _handler_bundle()

    with pytest.raises(ValueError, match="at least one"):
        handler.handle(fixture.dispatch_context, fixture.event)

    stack.outputs = (
        stack.intent(
            fixture.decision_context,
            decision_intent_id=DecisionIntentId.from_str("bad"),
        ),
    )
    with pytest.raises(ValueError, match="decision index 0"):
        handler.handle(fixture.dispatch_context, fixture.event)

    stack.outputs = (stack.intent(fixture.decision_context, status=DecisionIntentStatus.CANCELLED),)
    with pytest.raises(ValueError, match="decision index 0"):
        handler.handle(fixture.dispatch_context, fixture.event)

    stack.decide = lambda context: []  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="tuple"):
        handler.handle(fixture.dispatch_context, fixture.event)


@pytest.mark.parametrize("decision_kind", ("intent", "no_trade"))
@pytest.mark.parametrize("payload_kind", ("self", "custom_mapping", "nested_model"))
def test_decision_output_subclass_dump_rejected_as_invalid_output(
    decision_kind: str,
    payload_kind: str,
) -> None:
    fixture, _lookup, _evidence_lookup, stack, handler = _handler_bundle()
    if decision_kind == "intent":
        base = stack.intent(fixture.decision_context)
        attacker = _decision_intent_attacker(
            base,
            payload_kind=payload_kind,
            nested_model=fixture.event,
        )
    else:
        base = stack.no_trade(fixture.decision_context)
        attacker = _no_trade_attacker(
            base,
            payload_kind=payload_kind,
            nested_model=fixture.event,
        )
    stack.outputs = (attacker,)

    with pytest.raises(ValueError, match="decision index 0"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert stack.calls == 1
    assert attacker.dump_count == 1


@pytest.mark.parametrize("decision_kind", ("intent", "no_trade"))
@pytest.mark.parametrize("mutation_target", ("stack", "lookup_descriptor", "lookup_authority"))
def test_output_model_dump_metadata_side_effect_rejected_before_return(
    decision_kind: str,
    mutation_target: str,
) -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()

    def mutate() -> None:
        if mutation_target == "stack":
            stack.stack_id = "mutated-during-output-dump"
        elif mutation_target == "lookup_descriptor":
            lookup.mutate_descriptor = True
        else:
            lookup.mutate_authority = True

    base = (
        stack.intent(fixture.decision_context)
        if decision_kind == "intent"
        else stack.no_trade(fixture.decision_context)
    )
    attacker = _decision_output_attacker(base, on_dump=mutate)
    stack.outputs = (attacker,)

    with pytest.raises(ValueError, match="during invocation"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert stack.calls == 1
    assert attacker.dump_count == 1


def test_second_output_side_effect_rejects_without_partial_dispatch_or_journal() -> None:
    fixture, lookup, evidence_lookup, stack, handler = _handler_bundle()
    dispatcher = LocalDeterministicReplayDispatcher((handler,))
    dispatch_context = fixture.dispatch_context.model_copy(
        update={"dispatcher_fingerprint": dispatcher.dispatcher_fingerprint}
    )
    decision_context = build_replay_decision_stack_context(
        dispatch_context=dispatch_context,
        event=fixture.event,
        market=lookup.lookup(dispatch_context, fixture.event),
        evidence=evidence_lookup.lookup(dispatch_context, fixture.event),
    )
    lookup.calls = 0
    first = stack.intent(decision_context, 0)
    second_base = stack.no_trade(decision_context, 1)
    second = _decision_output_attacker(
        second_base,
        on_dump=lambda: setattr(lookup, "mutate_authority", True),
    )
    stack.outputs = (first, second)
    store = InMemoryReplayEventOutputRecordStore()
    journal = LocalReplayDecisionJournal(store)

    with pytest.raises(ValueError, match="during invocation"):
        handler.handle(dispatch_context, fixture.event)
    lookup.mutate_authority = False
    with pytest.raises(RuntimeError, match="replay handler"):
        dispatcher.plan_dispatch(
            dispatch_context,
            fixture.event,
            dispatch_receipt_id=build_replay_event_dispatch_receipt_id(
                dispatch_context.run_id,
                dispatch_context.event_order_index,
                dispatch_context.event_id,
            ),
        )

    assert second.dump_count == 2
    assert journal.decisions_for_run(fixture.dispatch_context.run_id) == ()


def test_invalid_second_output_rejects_without_partial_dispatch_or_journal() -> None:
    fixture, lookup, evidence_lookup, stack, handler = _handler_bundle()
    dispatcher = LocalDeterministicReplayDispatcher((handler,))
    dispatch_context = fixture.dispatch_context.model_copy(
        update={"dispatcher_fingerprint": dispatcher.dispatcher_fingerprint}
    )
    decision_context = build_replay_decision_stack_context(
        dispatch_context=dispatch_context,
        event=fixture.event,
        market=lookup.lookup(dispatch_context, fixture.event),
        evidence=evidence_lookup.lookup(dispatch_context, fixture.event),
    )
    lookup.calls = 0
    stack.outputs = (
        stack.intent(decision_context, 0),
        stack.intent(
            decision_context,
            1,
            decision_intent_id=DecisionIntentId.from_str("bad"),
        ),
    )
    store = InMemoryReplayEventOutputRecordStore()
    journal = LocalReplayDecisionJournal(store)

    with pytest.raises(ValueError, match="decision index 1"):
        handler.handle(dispatch_context, fixture.event)
    with pytest.raises(RuntimeError, match="replay handler") as exc_info:
        dispatcher.plan_dispatch(
            dispatch_context,
            fixture.event,
            dispatch_receipt_id=build_replay_event_dispatch_receipt_id(
                dispatch_context.run_id,
                dispatch_context.event_order_index,
                dispatch_context.event_id,
            ),
        )
    assert exc_info.value.__cause__ is not None
    assert "decision index 1" in str(exc_info.value.__cause__)

    assert stack.calls == 2
    assert journal.decisions_for_run(fixture.dispatch_context.run_id) == ()


def test_stack_exception_propagates_exact_instance() -> None:
    fixture, _lookup, _evidence_lookup, stack, handler = _handler_bundle()
    error = RuntimeError("stack exploded")
    stack.exception = error

    with pytest.raises(RuntimeError) as exc_info:
        handler.handle(fixture.dispatch_context, fixture.event)

    assert exc_info.value is error
    assert stack.calls == 1


def test_stack_and_lookup_metadata_mutation_rejected() -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    stack.outputs = (stack.intent(fixture.decision_context),)

    stack.stack_id = "other"
    with pytest.raises(ValueError, match="metadata changed"):
        handler.handle(fixture.dispatch_context, fixture.event)

    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    stack.outputs = (stack.intent(fixture.decision_context),)
    lookup.mutate_descriptor = True
    with pytest.raises(ValueError, match="lookup descriptor changed"):
        handler.handle(fixture.dispatch_context, fixture.event)

    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    stack.outputs = (stack.intent(fixture.decision_context),)
    stack.mutate_during_decide = ("stack_id", "other")
    with pytest.raises(ValueError, match="during invocation"):
        handler.handle(fixture.dispatch_context, fixture.event)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("stack_id", "other-stack"),
        ("stack_version", "2"),
        ("bot_id", fixture_stack_descriptor().bot_id.model_copy(update={"value": "bot-2"})),
        ("source_kind", DecisionSourceKind.RULE_BASED),
        ("supported_event_kinds", (ReplayInputKind.MARK_PRICE, ReplayInputKind.TRADE)),
    ),
)
def test_stack_descriptor_field_mutation_before_decide_rejected_without_stack_call(
    field_name: str,
    value: object,
) -> None:
    fixture, _lookup, _evidence_lookup, stack, handler = _handler_bundle()
    stack.outputs = (stack.intent(fixture.decision_context),)
    setattr(stack, field_name, value)

    with pytest.raises(ValueError, match="metadata changed"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert stack.calls == 0


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("stack_id", "other-stack"),
        ("stack_version", "2"),
        ("bot_id", fixture_stack_descriptor().bot_id.model_copy(update={"value": "bot-2"})),
        ("source_kind", DecisionSourceKind.RULE_BASED),
        ("supported_event_kinds", (ReplayInputKind.MARK_PRICE, ReplayInputKind.TRADE)),
    ),
)
def test_stack_descriptor_field_mutation_during_decide_rejected_after_stack_call(
    field_name: str,
    value: object,
) -> None:
    fixture, _lookup, _evidence_lookup, stack, handler = _handler_bundle()
    stack.outputs = (stack.intent(fixture.decision_context),)
    stack.mutate_during_decide = (field_name, value)

    with pytest.raises(ValueError, match="during invocation"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert stack.calls == 1


def test_stack_context_market_replacement_rejected_before_output_escape() -> None:
    fixture, _lookup, _evidence_lookup, stack, handler = _handler_bundle()
    changed = replay_decision_market_fixture(price="101")
    forged_market = _forged_result_for_authority(fixture, changed)

    def mutate_context(context: ReplayDecisionStackContext) -> None:
        object.__setattr__(context, "market", forged_market)

    stack.on_decide_context = mutate_context
    stack.output_factory = lambda _context: (stack.intent(fixture.decision_context),)

    with pytest.raises(ValueError, match="mutated invocation context"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert stack.calls == 1
    assert stack.received is not None
    assert _received_frame_price(stack) == "101"


@pytest.mark.parametrize("field_name", ("descriptor", "authority"))
def test_lookup_metadata_mutation_before_lookup_rejected_without_stack_call(
    field_name: str,
) -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    stack.outputs = (stack.intent(fixture.decision_context),)
    setattr(lookup, f"mutate_{field_name}", True)

    with pytest.raises(ValueError, match=f"lookup {field_name} changed"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert lookup.calls == 0
    assert stack.calls == 0


@pytest.mark.parametrize("field_name", ("descriptor", "authority"))
def test_lookup_metadata_mutation_during_lookup_rejected_before_stack_call(
    field_name: str,
) -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    stack.outputs = (stack.intent(fixture.decision_context),)
    setattr(lookup, f"mutate_{field_name}_during_lookup", True)

    with pytest.raises(ValueError, match=f"lookup {field_name} changed"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert lookup.calls == 1
    assert stack.calls == 0


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("stack_id", "lookup-mutated-stack"),
        ("stack_version", "lookup-mutated-version"),
        ("bot_id", fixture_stack_descriptor().bot_id.model_copy(update={"value": "bot-3"})),
        ("source_kind", DecisionSourceKind.RULE_BASED),
        ("supported_event_kinds", (ReplayInputKind.MARK_PRICE, ReplayInputKind.TRADE)),
    ),
)
def test_lookup_mutating_stack_metadata_rejected_before_decide(
    field_name: str,
    value: object,
) -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    stack.output_factory = lambda context: (stack.intent(context),)
    lookup.on_lookup = lambda _context, _event: setattr(stack, field_name, value)

    with pytest.raises(ValueError, match="metadata changed"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert lookup.calls == 1
    assert stack.calls == 0


@pytest.mark.parametrize("field_name", ("descriptor", "authority"))
@pytest.mark.parametrize("payload_kind", ("self", "custom_mapping", "nested_model"))
def test_lookup_metadata_subclass_dump_rejected_at_construction(
    field_name: str,
    payload_kind: str,
) -> None:
    fixture = replay_decision_market_fixture()
    lookup = _LookupSpy(fixture)
    evidence_lookup = _EvidenceLookupSpy(fixture)
    stack = _Stack(fixture)
    base = getattr(lookup, field_name)
    if payload_kind == "self":
        attacker = _lookup_metadata_attacker(field_name, base, return_self=True)
    elif payload_kind == "custom_mapping":
        attacker = _lookup_metadata_attacker(
            field_name,
            base,
            payload=_CustomMapping(base.model_dump(mode="json")),
        )
    else:
        attacker_payload = {**base.model_dump(mode="json"), "bad": fixture.event}
        attacker = _lookup_metadata_attacker(
            field_name,
            base,
            payload=attacker_payload,
        )
    setattr(lookup, f"_{field_name}", attacker)

    with pytest.raises(ValueError):
        ReplayDecisionStackHandler(stack, lookup, evidence_lookup)

    assert lookup.calls == 0
    assert stack.calls == 0
    assert attacker.dump_count == 1


@pytest.mark.parametrize("field_name", ("descriptor", "authority"))
def test_lookup_metadata_subclass_dump_rejected_before_lookup(
    field_name: str,
) -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    base = getattr(lookup, field_name)
    attacker = _lookup_metadata_attacker(field_name, base, return_self=True)
    setattr(lookup, f"_{field_name}", attacker)
    stack.outputs = (stack.intent(fixture.decision_context),)

    with pytest.raises(ValueError):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert lookup.calls == 0
    assert stack.calls == 0
    assert attacker.dump_count == 1


@pytest.mark.parametrize("field_name", ("descriptor", "authority"))
def test_lookup_metadata_mutation_during_decide_rejected_after_stack_call(
    field_name: str,
) -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    stack.outputs = (stack.intent(fixture.decision_context),)
    stack.on_decide = lambda: setattr(lookup, f"mutate_{field_name}", True)

    with pytest.raises(ValueError, match="during invocation"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert lookup.calls == 1
    assert stack.calls == 1


def test_handler_rejects_forged_lookup_result_before_stack_call() -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    changed = replay_decision_market_fixture(price="101")
    forged_entry = build_replay_market_frame_lookup_entry(
        market_timeline_id=lookup.authority.market_timeline_id,
        replay_timeline_id=lookup.authority.replay_timeline_id,
        replay_plan_id=lookup.authority.replay_plan_id,
        adapter_fingerprint=lookup.authority.adapter_fingerprint,
        observation_projection=changed.market_timeline.observation_projections[0],
        frame_projection=changed.market_timeline.frame_projections[0],
    )
    lookup._result = ReplayMarketFrameLookupResult(
        descriptor=lookup.descriptor,
        entry=forged_entry,
        observation_projection=changed.market_timeline.observation_projections[0],
        frame_projection=changed.market_timeline.frame_projections[0],
    )
    stack.outputs = (stack.intent(fixture.decision_context),)

    with pytest.raises(ValueError, match="absent"):
        handler.handle(fixture.dispatch_context, fixture.event)
    assert stack.calls == 0


def test_handler_snapshots_subclass_result_once_and_never_uses_forged_later_dump() -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    changed = replay_decision_market_fixture(price="101")
    stateful = _StatefulLookupResult(
        **fixture.decision_context.market.model_dump(mode="json"),
        first_payload=fixture.decision_context.market.model_dump(mode="json"),
        later_payload=changed.decision_context.market.model_dump(mode="json"),
    )
    lookup._result = stateful
    stack.outputs = (stack.intent(fixture.decision_context),)

    proposals = handler.handle(fixture.dispatch_context, fixture.event)

    assert len(proposals) == 1
    assert stack.calls == 1
    assert stack.received is not None
    assert type(stack.received.market) is ReplayMarketFrameLookupResult
    assert _received_frame_price(stack) == "100"
    assert stateful.dump_count == 1


def test_handler_rejects_self_dumping_lookup_result_before_stack_call() -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    changed = replay_decision_market_fixture(price="101")
    stateful = _SelfThenChangingLookupResult(
        **fixture.decision_context.market.model_dump(mode="json"),
        legitimate_payload=fixture.decision_context.market.model_dump(mode="json"),
        forged_payload=changed.decision_context.market.model_dump(mode="json"),
    )
    lookup._result = stateful
    stack.outputs = (stack.intent(fixture.decision_context),)

    with pytest.raises(ValueError, match="plain JSON"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert lookup.calls == 1
    assert stack.calls == 0
    assert stateful.dump_count == 1


def test_handler_rejects_subclass_result_with_forged_first_dump_before_stack_call() -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    changed = replay_decision_market_fixture(price="101")
    forged = _forged_result_for_authority(fixture, changed)
    stateful = _StatefulLookupResult(
        **fixture.decision_context.market.model_dump(mode="json"),
        first_payload=forged.model_dump(mode="json"),
        later_payload=fixture.decision_context.market.model_dump(mode="json"),
    )
    lookup._result = stateful
    stack.outputs = (stack.intent(fixture.decision_context),)

    with pytest.raises(ValueError, match="absent"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert stack.calls == 0
    assert stateful.dump_count == 1


def test_handler_rejects_arbitrary_lookup_object_without_invoking_validation_trap() -> None:
    fixture, lookup, _evidence_lookup, stack, handler = _handler_bundle()
    trap = _ValidationTrap()
    lookup._result = trap
    stack.outputs = (stack.intent(fixture.decision_context),)

    with pytest.raises(ValueError, match="ReplayMarketFrameLookupResult"):
        handler.handle(fixture.dispatch_context, fixture.event)

    assert stack.calls == 0
    assert trap.model_dump_calls == 0
    assert trap.model_validate_calls == 0


def test_dispatcher_records_decode_back_to_typed_v3_envelopes() -> None:
    fixture, _lookup, _evidence_lookup, stack, handler = _handler_bundle()
    dispatcher = LocalDeterministicReplayDispatcher((handler,))
    context = fixture.dispatch_context.model_copy(
        update={"dispatcher_fingerprint": dispatcher.dispatcher_fingerprint}
    )
    decision_context = build_replay_decision_stack_context(
        dispatch_context=context,
        event=fixture.event,
        market=fixture.lookup.lookup(context, fixture.event),
        evidence=fixture.evidence_lookup.lookup(context, fixture.event),
    )
    stack.outputs = (stack.intent(decision_context),)
    plan = dispatcher.plan_dispatch(
        context,
        fixture.event,
        dispatch_receipt_id=build_replay_event_dispatch_receipt_id(
            context.run_id,
            context.event_order_index,
            context.event_id,
        ),
    )

    decoded = decode_replay_decision_output_record(plan.output_records[0])
    assert decoded.market_context_reference.context_id == (
        decision_context.context_id
    )


def _forged_result_for_authority(fixture, changed) -> ReplayMarketFrameLookupResult:
    forged_entry = build_replay_market_frame_lookup_entry(
        market_timeline_id=fixture.lookup.authority.market_timeline_id,
        replay_timeline_id=fixture.lookup.authority.replay_timeline_id,
        replay_plan_id=fixture.lookup.authority.replay_plan_id,
        adapter_fingerprint=fixture.lookup.authority.adapter_fingerprint,
        observation_projection=changed.market_timeline.observation_projections[0],
        frame_projection=changed.market_timeline.frame_projections[0],
    )
    return ReplayMarketFrameLookupResult(
        descriptor=fixture.lookup.descriptor,
        entry=forged_entry,
        observation_projection=changed.market_timeline.observation_projections[0],
        frame_projection=changed.market_timeline.frame_projections[0],
    )


def _lookup_metadata_attacker(
    field_name: str,
    base: ReplayMarketFrameLookupDescriptor | ReplayMarketFrameLookupAuthority,
    *,
    payload: object | None = None,
    return_self: bool = False,
) -> _DumpPayloadLookupDescriptor | _DumpPayloadLookupAuthority:
    if field_name == "descriptor":
        return _DumpPayloadLookupDescriptor(
            **base.model_dump(mode="json"),
            payload=payload,
            return_self=return_self,
        )
    return _DumpPayloadLookupAuthority(
        **base.model_dump(mode="json"),
        payload=payload,
        return_self=return_self,
    )


def _dispatch_context_attacker(
    base: ReplayDispatchContext,
    *,
    payload_kind: str,
    nested_model: object,
) -> _DumpPayloadDispatchContext:
    return _DumpPayloadDispatchContext(
        **base.model_dump(mode="json"),
        payload=_payload_for_kind(base, payload_kind, nested_model),
        return_self=payload_kind == "self",
    )


def _timeline_event_attacker(
    base: ReplayTimelineEvent,
    *,
    payload_kind: str,
    nested_model: object,
) -> _DumpPayloadTimelineEvent:
    return _DumpPayloadTimelineEvent(
        **base.model_dump(mode="json"),
        payload=_payload_for_kind(base, payload_kind, nested_model),
        return_self=payload_kind == "self",
    )


def _decision_intent_attacker(
    base: DecisionIntent,
    *,
    payload_kind: str,
    nested_model: object,
) -> _DumpPayloadDecisionIntent:
    return _DumpPayloadDecisionIntent(
        **base.model_dump(mode="json"),
        payload=_payload_for_kind(base, payload_kind, nested_model),
        return_self=payload_kind == "self",
    )


def _no_trade_attacker(
    base: NoTradeDecision,
    *,
    payload_kind: str,
    nested_model: object,
) -> _DumpPayloadNoTradeDecision:
    return _DumpPayloadNoTradeDecision(
        **base.model_dump(mode="json"),
        payload=_payload_for_kind(base, payload_kind, nested_model),
        return_self=payload_kind == "self",
    )


def _decision_output_attacker(
    base: DecisionIntent | NoTradeDecision,
    *,
    on_dump: Callable[[], None],
) -> _DumpPayloadDecisionIntent | _DumpPayloadNoTradeDecision:
    if isinstance(base, DecisionIntent):
        return _DumpPayloadDecisionIntent(
            **base.model_dump(mode="json"),
            payload=base.model_dump(mode="json"),
            on_dump=on_dump,
        )
    return _DumpPayloadNoTradeDecision(
        **base.model_dump(mode="json"),
        payload=base.model_dump(mode="json"),
        on_dump=on_dump,
    )


def _payload_for_kind(base, payload_kind: str, nested_model: object) -> object:
    if payload_kind == "self":
        return None
    if payload_kind == "custom_mapping":
        return _CustomMapping(base.model_dump(mode="json"))
    payload = base.model_dump(mode="json")
    payload["bad"] = nested_model
    return payload


def _proposal_envelope(
    proposal,
) -> ReplayDecisionOutputEnvelope:
    return ReplayDecisionOutputEnvelope.model_validate(
        json.loads(proposal.canonical_payload)
    )


def _received_frame_price(stack: _Stack) -> str:
    assert stack.received is not None
    observation = stack.received.market.frame_projection.frame.observations[0]
    payload = cast(MarkPriceObservationPayload, observation.payload)
    return str(payload.price)
