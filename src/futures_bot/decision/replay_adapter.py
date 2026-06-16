from __future__ import annotations

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
    ReplayDecisionStackDescriptor,
    _normalize_decision_data,
    build_replay_decision_output_proposal,
    build_replay_decision_stack_fingerprint,
)
from futures_bot.ports.decision import DecisionStackOutput, DecisionStackPort


class ReplayDecisionStackHandler:
    """Replay handler adapter for synchronous deterministic DecisionStacks."""

    def __init__(self, decision_stack: DecisionStackPort) -> None:
        self._decision_stack = decision_stack
        descriptor = _descriptor_from_stack(decision_stack)
        self._descriptor = ReplayDecisionStackDescriptor.model_validate(
            descriptor.model_dump()
        )
        self._decision_stack_fingerprint = build_replay_decision_stack_fingerprint(
            self._descriptor
        )

    @property
    def handler_id(self) -> str:
        return self._decision_stack_fingerprint

    @property
    def handler_version(self) -> str:
        return self._descriptor.stack_version

    @property
    def supported_event_kinds(self) -> tuple[ReplayInputKind, ...]:
        return self._descriptor.supported_event_kinds

    @property
    def descriptor(self) -> ReplayDecisionStackDescriptor:
        return ReplayDecisionStackDescriptor.model_validate(self._descriptor.model_dump())

    @property
    def decision_stack_fingerprint(self) -> str:
        return self._decision_stack_fingerprint

    def handle(
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
    ) -> tuple[ReplayHandlerOutputProposal, ...]:
        context = _revalidate_context(context)
        event = _revalidate_event(event)
        _validate_context_matches_event(context, event)
        _require_stack_metadata_unchanged(self._decision_stack, self._descriptor)
        if event.kind not in self._descriptor.supported_event_kinds:
            raise ValueError("DecisionStack does not support replay event kind")

        outputs = self._decision_stack.decide(context, event)
        _require_stack_metadata_unchanged_after_decide(
            self._decision_stack,
            self._descriptor,
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
                    context=context,
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


def _revalidate_context(context: object) -> ReplayDispatchContext:
    if isinstance(context, ReplayDispatchContext):
        return ReplayDispatchContext.model_validate(context.model_dump())
    return ReplayDispatchContext.model_validate(context)


def _revalidate_event(event: object) -> ReplayTimelineEvent:
    if isinstance(event, ReplayTimelineEvent):
        return ReplayTimelineEvent.model_validate(event.model_dump())
    return ReplayTimelineEvent.model_validate(event)


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


def _revalidate_decision_output(output: object) -> DecisionStackOutput:
    if isinstance(output, DecisionIntent):
        return DecisionIntent.model_validate(
            _normalize_decision_data(output.model_dump(mode="json"))
        )
    if isinstance(output, NoTradeDecision):
        return NoTradeDecision.model_validate(
            _normalize_decision_data(output.model_dump(mode="json"))
        )
    raise ValueError("DecisionStack output must be DecisionIntent or NoTradeDecision")


def _envelope_for_output(
    *,
    descriptor: ReplayDecisionStackDescriptor,
    context: ReplayDispatchContext,
    decision_index: int,
    decision: DecisionStackOutput,
) -> ReplayDecisionOutputEnvelope:
    if isinstance(decision, DecisionIntent):
        return ReplayDecisionOutputEnvelope(
            run_id=context.run_id,
            event_id=context.event_id,
            event_order_index=context.event_order_index,
            event_time=context.event_time,
            event_kind=context.event_kind,
            stack_descriptor=descriptor,
            decision_index=decision_index,
            decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
            decision_intent=decision,
        )
    return ReplayDecisionOutputEnvelope(
        run_id=context.run_id,
        event_id=context.event_id,
        event_order_index=context.event_order_index,
        event_time=context.event_time,
        event_kind=context.event_kind,
        stack_descriptor=descriptor,
        decision_index=decision_index,
        decision_kind=ReplayDecisionOutputKind.NO_TRADE_DECISION,
        no_trade_decision=decision,
    )
