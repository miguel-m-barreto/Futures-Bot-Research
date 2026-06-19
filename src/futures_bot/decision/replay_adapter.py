from __future__ import annotations

import math
from typing import cast

from pydantic import BaseModel

from futures_bot.domain.decisions import DecisionIntent, NoTradeDecision
from futures_bot.domain.replay import (
    ReplayDispatchContext,
    ReplayHandlerOutputProposal,
    ReplayInputKind,
    ReplayTimelineEvent,
)
from futures_bot.domain.replay_decisions import (
    ReplayDecisionOutputEnvelope,
    ReplayDecisionOutputKind,
    ReplayDecisionStackContext,
    ReplayDecisionStackDescriptor,
    build_replay_decision_evidence_context_reference,
    build_replay_decision_handler_fingerprint,
    build_replay_decision_market_context_reference,
    build_replay_decision_output_proposal,
    build_replay_decision_stack_context,
    build_replay_decision_stack_fingerprint,
)
from futures_bot.domain.replay_evidence import (
    ReplayMarketEvidenceLookupAuthority,
    ReplayMarketEvidenceLookupDescriptor,
    ReplayMarketEvidenceLookupResult,
    build_replay_market_evidence_lookup_descriptor,
    validate_replay_market_evidence_lookup_membership,
)
from futures_bot.domain.replay_market_data import (
    ReplayMarketFrameLookupAuthority,
    ReplayMarketFrameLookupDescriptor,
    ReplayMarketFrameLookupResult,
    build_replay_market_frame_lookup_descriptor,
    validate_replay_market_frame_lookup_membership,
)
from futures_bot.ports.decision import DecisionStackOutput, DecisionStackPort
from futures_bot.ports.evidence import ReplayMarketEvidenceLookupPort
from futures_bot.ports.market_data import ReplayMarketFrameLookupPort


class ReplayDecisionStackHandler:
    """Replay handler adapter for synchronous deterministic DecisionStacks."""

    def __init__(
        self,
        decision_stack: DecisionStackPort,
        market_lookup: ReplayMarketFrameLookupPort,
        evidence_lookup: ReplayMarketEvidenceLookupPort,
    ) -> None:
        self._decision_stack = decision_stack
        self._market_lookup = market_lookup
        self._evidence_lookup = evidence_lookup
        descriptor = _descriptor_from_stack(decision_stack)
        self._descriptor = _snapshot_boundary_model(
            ReplayDecisionStackDescriptor,
            descriptor,
            field_name="DecisionStack descriptor",
        )
        lookup_authority = market_lookup.authority
        self._market_lookup_authority = _snapshot_boundary_model(
            ReplayMarketFrameLookupAuthority,
            lookup_authority,
            field_name="market lookup authority",
        )
        lookup_descriptor = market_lookup.descriptor
        expected_descriptor = build_replay_market_frame_lookup_descriptor(
            self._market_lookup_authority
        )
        self._market_lookup_descriptor = _snapshot_boundary_model(
            ReplayMarketFrameLookupDescriptor,
            lookup_descriptor,
            field_name="market lookup descriptor",
        )
        if self._market_lookup_descriptor != expected_descriptor:
            raise ValueError("market lookup descriptor must match lookup authority")
        evidence_authority = evidence_lookup.authority
        self._evidence_lookup_authority = _snapshot_boundary_model(
            ReplayMarketEvidenceLookupAuthority,
            evidence_authority,
            field_name="evidence lookup authority",
        )
        evidence_descriptor = evidence_lookup.descriptor
        expected_evidence_descriptor = build_replay_market_evidence_lookup_descriptor(
            self._evidence_lookup_authority
        )
        self._evidence_lookup_descriptor = _snapshot_boundary_model(
            ReplayMarketEvidenceLookupDescriptor,
            evidence_descriptor,
            field_name="evidence lookup descriptor",
        )
        if self._evidence_lookup_descriptor != expected_evidence_descriptor:
            raise ValueError("evidence lookup descriptor must match lookup authority")
        unsupported = tuple(
            kind
            for kind in self._descriptor.supported_event_kinds
            if kind not in self._market_lookup_descriptor.supported_event_kinds
            or kind not in self._evidence_lookup_descriptor.supported_event_kinds
        )
        if unsupported:
            raise ValueError(
                "DecisionStack event kinds must be supported by market and evidence lookup"
            )
        self._decision_stack_fingerprint = build_replay_decision_stack_fingerprint(
            self._descriptor
        )
        self._decision_handler_fingerprint = build_replay_decision_handler_fingerprint(
            stack_descriptor=self._descriptor,
            market_lookup_descriptor=self._market_lookup_descriptor,
            evidence_lookup_descriptor=self._evidence_lookup_descriptor,
        )

    @property
    def handler_id(self) -> str:
        return self._decision_handler_fingerprint

    @property
    def handler_version(self) -> str:
        return self._descriptor.stack_version

    @property
    def supported_event_kinds(self) -> tuple[ReplayInputKind, ...]:
        return self._descriptor.supported_event_kinds

    @property
    def descriptor(self) -> ReplayDecisionStackDescriptor:
        return _snapshot_boundary_model(
            ReplayDecisionStackDescriptor,
            self._descriptor,
            field_name="DecisionStack descriptor",
        )

    @property
    def market_lookup_descriptor(self) -> ReplayMarketFrameLookupDescriptor:
        return _snapshot_boundary_model(
            ReplayMarketFrameLookupDescriptor,
            self._market_lookup_descriptor,
            field_name="market lookup descriptor",
        )

    @property
    def market_lookup_authority(self) -> ReplayMarketFrameLookupAuthority:
        return _snapshot_boundary_model(
            ReplayMarketFrameLookupAuthority,
            self._market_lookup_authority,
            field_name="market lookup authority",
        )

    @property
    def evidence_lookup_descriptor(self) -> ReplayMarketEvidenceLookupDescriptor:
        return _snapshot_boundary_model(
            ReplayMarketEvidenceLookupDescriptor,
            self._evidence_lookup_descriptor,
            field_name="evidence lookup descriptor",
        )

    @property
    def evidence_lookup_authority(self) -> ReplayMarketEvidenceLookupAuthority:
        return _snapshot_boundary_model(
            ReplayMarketEvidenceLookupAuthority,
            self._evidence_lookup_authority,
            field_name="evidence lookup authority",
        )

    @property
    def decision_stack_fingerprint(self) -> str:
        return self._decision_stack_fingerprint

    @property
    def decision_handler_fingerprint(self) -> str:
        return self._decision_handler_fingerprint

    def handle(  # noqa: PLR0915 - explicit replay boundary checks
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
    ) -> tuple[ReplayHandlerOutputProposal, ...]:
        trusted_context = _revalidate_context(context)
        trusted_event = _revalidate_event(event)
        _validate_context_matches_event(trusted_context, trusted_event)
        _require_stack_metadata_unchanged(self._decision_stack, self._descriptor)
        _require_lookup_descriptor_unchanged(
            self._market_lookup,
            self._market_lookup_descriptor,
        )
        _require_lookup_authority_unchanged(
            self._market_lookup,
            self._market_lookup_authority,
        )
        _require_evidence_lookup_descriptor_unchanged(
            self._evidence_lookup,
            self._evidence_lookup_descriptor,
        )
        _require_evidence_lookup_authority_unchanged(
            self._evidence_lookup,
            self._evidence_lookup_authority,
        )
        if trusted_event.kind not in self._descriptor.supported_event_kinds:
            raise ValueError("DecisionStack does not support replay event kind")

        lookup_context = _snapshot_boundary_model(
            ReplayDispatchContext,
            trusted_context,
            field_name="lookup dispatch context",
        )
        lookup_event = _snapshot_boundary_model(
            ReplayTimelineEvent,
            trusted_event,
            field_name="lookup timeline event",
        )
        raw_market = self._market_lookup.lookup(lookup_context, lookup_event)
        trusted_market = _snapshot_market_lookup_result(raw_market)
        _validate_market_result_matches_trusted_event(
            trusted_context=trusted_context,
            trusted_event=trusted_event,
            market=trusted_market,
        )
        if trusted_market.descriptor != self._market_lookup_descriptor:
            raise ValueError("market lookup result descriptor changed")
        validate_replay_market_frame_lookup_membership(
            authority=self._market_lookup_authority,
            result=trusted_market,
        )
        _require_evidence_lookup_descriptor_unchanged(
            self._evidence_lookup,
            self._evidence_lookup_descriptor,
        )
        _require_evidence_lookup_authority_unchanged(
            self._evidence_lookup,
            self._evidence_lookup_authority,
        )
        _require_lookup_descriptor_unchanged(
            self._market_lookup,
            self._market_lookup_descriptor,
        )
        _require_lookup_authority_unchanged(
            self._market_lookup,
            self._market_lookup_authority,
        )
        evidence_lookup_context = _snapshot_boundary_model(
            ReplayDispatchContext,
            trusted_context,
            field_name="evidence lookup dispatch context",
        )
        evidence_lookup_event = _snapshot_boundary_model(
            ReplayTimelineEvent,
            trusted_event,
            field_name="evidence lookup timeline event",
        )
        raw_evidence = self._evidence_lookup.lookup(
            evidence_lookup_context,
            evidence_lookup_event,
        )
        trusted_evidence = _snapshot_evidence_lookup_result(raw_evidence)
        _validate_evidence_result_matches_trusted_event(
            trusted_context=trusted_context,
            trusted_event=trusted_event,
            evidence=trusted_evidence,
        )
        if trusted_evidence.descriptor != self._evidence_lookup_descriptor:
            raise ValueError("evidence lookup result descriptor changed")
        validate_replay_market_evidence_lookup_membership(
            authority=self._evidence_lookup_authority,
            result=trusted_evidence,
        )
        _require_market_and_evidence_context_match(
            market=trusted_market,
            evidence=trusted_evidence,
        )
        _require_lookup_descriptor_unchanged(
            self._market_lookup,
            self._market_lookup_descriptor,
        )
        _require_lookup_authority_unchanged(
            self._market_lookup,
            self._market_lookup_authority,
        )
        _require_evidence_lookup_descriptor_unchanged(
            self._evidence_lookup,
            self._evidence_lookup_descriptor,
        )
        _require_evidence_lookup_authority_unchanged(
            self._evidence_lookup,
            self._evidence_lookup_authority,
        )
        trusted_decision_context = build_replay_decision_stack_context(
            dispatch_context=trusted_context,
            event=trusted_event,
            market=trusted_market,
            evidence=trusted_evidence,
        )
        _require_stack_metadata_unchanged(self._decision_stack, self._descriptor)
        _require_evidence_lookup_descriptor_unchanged(
            self._evidence_lookup,
            self._evidence_lookup_descriptor,
        )
        _require_evidence_lookup_authority_unchanged(
            self._evidence_lookup,
            self._evidence_lookup_authority,
        )
        stack_context = _snapshot_boundary_model(
            ReplayDecisionStackContext,
            trusted_decision_context,
            field_name="DecisionStack invocation context",
        )
        if stack_context != trusted_decision_context:
            raise ValueError("DecisionStack invocation context snapshot changed")
        if stack_context is trusted_decision_context:
            raise ValueError("DecisionStack invocation context was not isolated")
        outputs = self._decision_stack.decide(stack_context)
        try:
            post_decide_stack_context = _snapshot_boundary_model(
                ReplayDecisionStackContext,
                stack_context,
                field_name="DecisionStack invocation context",
            )
        except Exception as exc:
            raise ValueError("DecisionStack mutated invocation context") from exc
        if post_decide_stack_context != trusted_decision_context:
            raise ValueError("DecisionStack mutated invocation context")
        _require_stack_metadata_unchanged_after_decide(
            self._decision_stack,
            self._descriptor,
        )
        _require_lookup_descriptor_unchanged_after_decide(
            self._market_lookup,
            self._market_lookup_descriptor,
        )
        _require_lookup_authority_unchanged_after_decide(
            self._market_lookup,
            self._market_lookup_authority,
        )
        _require_evidence_lookup_descriptor_unchanged_after_decide(
            self._evidence_lookup,
            self._evidence_lookup_descriptor,
        )
        _require_evidence_lookup_authority_unchanged_after_decide(
            self._evidence_lookup,
            self._evidence_lookup_authority,
        )
        if not isinstance(outputs, tuple):
            raise ValueError("DecisionStack decide() must return a tuple")
        if not outputs:
            raise ValueError("DecisionStack must return at least one explicit outcome")

        proposals: list[ReplayHandlerOutputProposal] = []
        for decision_index, output in enumerate(outputs):
            try:
                decision = _revalidate_decision_output(output)
                envelope = _envelope_for_output(
                    descriptor=self._descriptor,
                    market_lookup_descriptor=self._market_lookup_descriptor,
                    evidence_lookup_descriptor=self._evidence_lookup_descriptor,
                    context=trusted_decision_context,
                    decision_index=decision_index,
                    decision=decision,
                )
                proposals.append(build_replay_decision_output_proposal(envelope))
            except Exception as exc:
                raise ValueError(
                    "invalid DecisionStack output "
                    f"for stack {self._descriptor.stack_id!r} "
                    f"at decision index {decision_index}"
                ) from exc
        _require_stack_metadata_unchanged_after_decide(
            self._decision_stack,
            self._descriptor,
        )
        _require_lookup_descriptor_unchanged_after_decide(
            self._market_lookup,
            self._market_lookup_descriptor,
        )
        _require_lookup_authority_unchanged_after_decide(
            self._market_lookup,
            self._market_lookup_authority,
        )
        _require_evidence_lookup_descriptor_unchanged_after_decide(
            self._evidence_lookup,
            self._evidence_lookup_descriptor,
        )
        _require_evidence_lookup_authority_unchanged_after_decide(
            self._evidence_lookup,
            self._evidence_lookup_authority,
        )
        return tuple(proposals)


def _descriptor_from_stack(
    decision_stack: DecisionStackPort,
) -> ReplayDecisionStackDescriptor:
    return ReplayDecisionStackDescriptor(
        stack_id=decision_stack.stack_id,
        stack_version=decision_stack.stack_version,
        bot_id=decision_stack.bot_id,
        source_kind=decision_stack.source_kind,
        supported_event_kinds=decision_stack.supported_event_kinds,
    )


def _require_stack_metadata_unchanged(
    decision_stack: DecisionStackPort,
    descriptor: ReplayDecisionStackDescriptor,
) -> None:
    current = _descriptor_from_stack(decision_stack)
    if current != descriptor:
        raise ValueError("DecisionStack metadata changed after handler construction")


def _require_stack_metadata_unchanged_after_decide(
    decision_stack: DecisionStackPort,
    descriptor: ReplayDecisionStackDescriptor,
) -> None:
    current = _descriptor_from_stack(decision_stack)
    if current != descriptor:
        raise ValueError("DecisionStack metadata changed during invocation")


def _require_lookup_descriptor_unchanged(
    market_lookup: ReplayMarketFrameLookupPort,
    descriptor: ReplayMarketFrameLookupDescriptor,
) -> None:
    current = _snapshot_boundary_model(
        ReplayMarketFrameLookupDescriptor,
        market_lookup.descriptor,
        field_name="market lookup descriptor",
    )
    if current != descriptor:
        raise ValueError("market lookup descriptor changed after handler construction")


def _require_lookup_authority_unchanged(
    market_lookup: ReplayMarketFrameLookupPort,
    authority: ReplayMarketFrameLookupAuthority,
) -> None:
    try:
        current = _snapshot_boundary_model(
            ReplayMarketFrameLookupAuthority,
            market_lookup.authority,
            field_name="market lookup authority",
        )
    except Exception as exc:
        raise ValueError(
            "market lookup authority changed after handler construction"
        ) from exc
    if current != authority:
        raise ValueError("market lookup authority changed after handler construction")


def _require_lookup_descriptor_unchanged_after_decide(
    market_lookup: ReplayMarketFrameLookupPort,
    descriptor: ReplayMarketFrameLookupDescriptor,
) -> None:
    current = _snapshot_boundary_model(
        ReplayMarketFrameLookupDescriptor,
        market_lookup.descriptor,
        field_name="market lookup descriptor",
    )
    if current != descriptor:
        raise ValueError("market lookup descriptor changed during invocation")


def _require_lookup_authority_unchanged_after_decide(
    market_lookup: ReplayMarketFrameLookupPort,
    authority: ReplayMarketFrameLookupAuthority,
) -> None:
    try:
        current = _snapshot_boundary_model(
            ReplayMarketFrameLookupAuthority,
            market_lookup.authority,
            field_name="market lookup authority",
        )
    except Exception as exc:
        raise ValueError("market lookup authority changed during invocation") from exc
    if current != authority:
        raise ValueError("market lookup authority changed during invocation")


def _require_evidence_lookup_descriptor_unchanged(
    evidence_lookup: ReplayMarketEvidenceLookupPort,
    descriptor: ReplayMarketEvidenceLookupDescriptor,
) -> None:
    current = _snapshot_boundary_model(
        ReplayMarketEvidenceLookupDescriptor,
        evidence_lookup.descriptor,
        field_name="evidence lookup descriptor",
    )
    if current != descriptor:
        raise ValueError("evidence lookup descriptor changed after handler construction")


def _require_evidence_lookup_authority_unchanged(
    evidence_lookup: ReplayMarketEvidenceLookupPort,
    authority: ReplayMarketEvidenceLookupAuthority,
) -> None:
    try:
        current = _snapshot_boundary_model(
            ReplayMarketEvidenceLookupAuthority,
            evidence_lookup.authority,
            field_name="evidence lookup authority",
        )
    except Exception as exc:
        raise ValueError(
            "evidence lookup authority changed after handler construction"
        ) from exc
    if current != authority:
        raise ValueError("evidence lookup authority changed after handler construction")


def _require_evidence_lookup_descriptor_unchanged_after_decide(
    evidence_lookup: ReplayMarketEvidenceLookupPort,
    descriptor: ReplayMarketEvidenceLookupDescriptor,
) -> None:
    current = _snapshot_boundary_model(
        ReplayMarketEvidenceLookupDescriptor,
        evidence_lookup.descriptor,
        field_name="evidence lookup descriptor",
    )
    if current != descriptor:
        raise ValueError("evidence lookup descriptor changed during invocation")


def _require_evidence_lookup_authority_unchanged_after_decide(
    evidence_lookup: ReplayMarketEvidenceLookupPort,
    authority: ReplayMarketEvidenceLookupAuthority,
) -> None:
    try:
        current = _snapshot_boundary_model(
            ReplayMarketEvidenceLookupAuthority,
            evidence_lookup.authority,
            field_name="evidence lookup authority",
        )
    except Exception as exc:
        raise ValueError("evidence lookup authority changed during invocation") from exc
    if current != authority:
        raise ValueError("evidence lookup authority changed during invocation")


def _revalidate_context(context: object) -> ReplayDispatchContext:
    return _snapshot_boundary_model(
        ReplayDispatchContext,
        context,
        field_name="dispatch context",
    )


def _revalidate_event(event: object) -> ReplayTimelineEvent:
    return _snapshot_boundary_model(
        ReplayTimelineEvent,
        event,
        field_name="timeline event",
    )


def _snapshot_market_lookup_result(value: object) -> ReplayMarketFrameLookupResult:
    return _snapshot_boundary_model(
        ReplayMarketFrameLookupResult,
        value,
        field_name="market lookup result",
    )


def _snapshot_evidence_lookup_result(
    value: object,
) -> ReplayMarketEvidenceLookupResult:
    return _snapshot_boundary_model(
        ReplayMarketEvidenceLookupResult,
        value,
        field_name="evidence lookup result",
    )


def _snapshot_boundary_model[T: BaseModel](
    model_type: type[T],
    value: object,
    *,
    field_name: str,
) -> T:
    if isinstance(value, model_type):
        payload = value.model_dump(mode="json")
    elif type(value) is dict:
        payload = value
    else:
        raise ValueError(f"{field_name} must be a {model_type.__name__} or plain dict")
    _require_plain_json_tree(payload, path=field_name)
    snapshot = model_type.model_validate(payload)
    if type(snapshot) is not model_type:
        raise ValueError(f"{field_name} snapshot must be exact {model_type.__name__}")
    return snapshot


def _require_plain_json_tree(value: object, *, path: str) -> None:
    value_type = type(value)
    if value is None or value_type in {str, int, bool}:
        return
    if value_type is float:
        if not math.isfinite(cast(float, value)):
            raise ValueError(f"{path} must not contain non-finite floats")
        return
    if value_type is dict:
        for key, nested in cast(dict[object, object], value).items():
            if type(key) is not str:
                raise ValueError(f"{path} keys must be strings")
            _require_plain_json_tree(nested, path=f"{path}.{key}")
        return
    if value_type is list:
        for index, nested in enumerate(cast(list[object], value)):
            _require_plain_json_tree(nested, path=f"{path}[{index}]")
        return
    raise ValueError(f"{path} must be a plain JSON-compatible tree")


def _validate_context_matches_event(
    context: ReplayDispatchContext,
    event: ReplayTimelineEvent,
) -> None:
    if context.event_id != event.event_id:
        raise ValueError("dispatch context event_id does not match event")
    if context.event_order_index != event.order_index:
        raise ValueError("dispatch context event_order_index does not match event")
    if context.event_time != event.event_time:
        raise ValueError("dispatch context event_time does not match event")
    if context.event_kind != event.kind:
        raise ValueError("dispatch context event_kind does not match event")


def _validate_market_result_matches_trusted_event(
    *,
    trusted_context: ReplayDispatchContext,
    trusted_event: ReplayTimelineEvent,
    market: ReplayMarketFrameLookupResult,
) -> None:
    _validate_context_matches_event(trusted_context, trusted_event)
    event_values = (
        ("event_id", market.entry.event_id, trusted_context.event_id),
        (
            "event_order_index",
            market.entry.event_order_index,
            trusted_context.event_order_index,
        ),
        ("event_time", market.entry.event_time, trusted_context.event_time),
        ("event_kind", market.entry.event_kind, trusted_context.event_kind),
        ("event_id", market.observation_projection.event_id, trusted_event.event_id),
        (
            "event_order_index",
            market.observation_projection.event_order_index,
            trusted_event.order_index,
        ),
        (
            "event_time",
            market.observation_projection.event_time,
            trusted_event.event_time,
        ),
        ("event_kind", market.observation_projection.event_kind, trusted_event.kind),
        ("event_id", market.frame_projection.event_id, trusted_event.event_id),
        (
            "event_order_index",
            market.frame_projection.event_order_index,
            trusted_event.order_index,
        ),
        ("event_time", market.frame_projection.event_time, trusted_event.event_time),
    )
    for field_name, actual, expected in event_values:
        if actual != expected:
            raise ValueError(f"market lookup result {field_name} changed")


def _validate_evidence_result_matches_trusted_event(
    *,
    trusted_context: ReplayDispatchContext,
    trusted_event: ReplayTimelineEvent,
    evidence: ReplayMarketEvidenceLookupResult,
) -> None:
    _validate_context_matches_event(trusted_context, trusted_event)
    if trusted_context.timeline_id != evidence.descriptor.replay_timeline_id:
        raise ValueError("evidence lookup result timeline_id changed")
    if trusted_context.replay_plan_id != evidence.descriptor.replay_plan_id:
        raise ValueError("evidence lookup result replay_plan_id changed")
    event_values = (
        ("event_id", evidence.entry.event_id, trusted_context.event_id),
        (
            "event_order_index",
            evidence.entry.event_order_index,
            trusted_context.event_order_index,
        ),
        ("event_time", evidence.entry.event_time, trusted_context.event_time),
        ("event_kind", evidence.entry.event_kind, trusted_context.event_kind),
        (
            "event_id",
            evidence.projection.market_lookup_entry.event_id,
            trusted_event.event_id,
        ),
        (
            "event_order_index",
            evidence.projection.market_lookup_entry.event_order_index,
            trusted_event.order_index,
        ),
        (
            "event_time",
            evidence.projection.market_lookup_entry.event_time,
            trusted_event.event_time,
        ),
        (
            "event_kind",
            evidence.projection.market_lookup_entry.event_kind,
            trusted_event.kind,
        ),
        (
            "event_id",
            evidence.projection.market_frame_projection.event_id,
            trusted_event.event_id,
        ),
        (
            "event_order_index",
            evidence.projection.market_frame_projection.event_order_index,
            trusted_event.order_index,
        ),
        (
            "event_time",
            evidence.projection.market_frame_projection.event_time,
            trusted_event.event_time,
        ),
    )
    for field_name, actual, expected in event_values:
        if actual != expected:
            raise ValueError(f"evidence lookup result {field_name} changed")


def _require_market_and_evidence_context_match(
    *,
    market: ReplayMarketFrameLookupResult,
    evidence: ReplayMarketEvidenceLookupResult,
) -> None:
    if market.entry != evidence.projection.market_lookup_entry:
        raise ValueError("market lookup entry does not match evidence projection")
    if market.frame_projection != evidence.projection.market_frame_projection:
        raise ValueError("market frame projection does not match evidence projection")
    if market.frame_projection.frame != evidence.projection.evidence_set.source_frame:
        raise ValueError("market frame does not match evidence set source frame")
    values = (
        ("event_id", market.entry.event_id, evidence.entry.event_id),
        (
            "event_order_index",
            market.entry.event_order_index,
            evidence.entry.event_order_index,
        ),
        ("event_time", market.entry.event_time, evidence.entry.event_time),
        ("event_kind", market.entry.event_kind, evidence.entry.event_kind),
    )
    for field_name, actual, expected in values:
        if actual != expected:
            raise ValueError(f"market and evidence {field_name} mismatch")


def _revalidate_decision_output(output: object) -> DecisionStackOutput:
    if isinstance(output, DecisionIntent):
        return _snapshot_boundary_model(
            DecisionIntent,
            output,
            field_name="DecisionStack DecisionIntent output",
        )
    if isinstance(output, NoTradeDecision):
        return _snapshot_boundary_model(
            NoTradeDecision,
            output,
            field_name="DecisionStack NoTradeDecision output",
        )
    raise ValueError("DecisionStack output must be DecisionIntent or NoTradeDecision")


def _envelope_for_output(  # noqa: PLR0913 - explicit envelope material
    *,
    descriptor: ReplayDecisionStackDescriptor,
    market_lookup_descriptor: ReplayMarketFrameLookupDescriptor,
    evidence_lookup_descriptor: ReplayMarketEvidenceLookupDescriptor,
    context: ReplayDecisionStackContext,
    decision_index: int,
    decision: DecisionStackOutput,
) -> ReplayDecisionOutputEnvelope:
    dispatch_context = context.dispatch_context
    market_reference = build_replay_decision_market_context_reference(context)
    evidence_reference = build_replay_decision_evidence_context_reference(context)
    if isinstance(decision, DecisionIntent):
        return ReplayDecisionOutputEnvelope(
            run_id=dispatch_context.run_id,
            manifest_id=dispatch_context.manifest_id,
            replay_plan_id=dispatch_context.replay_plan_id,
            timeline_id=dispatch_context.timeline_id,
            timeline_fingerprint_id=dispatch_context.timeline_fingerprint_id,
            dispatcher_fingerprint=dispatch_context.dispatcher_fingerprint,
            event_id=dispatch_context.event_id,
            event_order_index=dispatch_context.event_order_index,
            event_time=dispatch_context.event_time,
            event_kind=dispatch_context.event_kind,
            stack_descriptor=descriptor,
            market_lookup_descriptor=market_lookup_descriptor,
            evidence_lookup_descriptor=evidence_lookup_descriptor,
            market_context_reference=market_reference,
            evidence_context_reference=evidence_reference,
            decision_index=decision_index,
            decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
            decision_intent=decision,
        )
    return ReplayDecisionOutputEnvelope(
        run_id=dispatch_context.run_id,
        manifest_id=dispatch_context.manifest_id,
        replay_plan_id=dispatch_context.replay_plan_id,
        timeline_id=dispatch_context.timeline_id,
        timeline_fingerprint_id=dispatch_context.timeline_fingerprint_id,
        dispatcher_fingerprint=dispatch_context.dispatcher_fingerprint,
        event_id=dispatch_context.event_id,
        event_order_index=dispatch_context.event_order_index,
        event_time=dispatch_context.event_time,
        event_kind=dispatch_context.event_kind,
        stack_descriptor=descriptor,
        market_lookup_descriptor=market_lookup_descriptor,
        evidence_lookup_descriptor=evidence_lookup_descriptor,
        market_context_reference=market_reference,
        evidence_context_reference=evidence_reference,
        decision_index=decision_index,
        decision_kind=ReplayDecisionOutputKind.NO_TRADE_DECISION,
        no_trade_decision=decision,
    )
