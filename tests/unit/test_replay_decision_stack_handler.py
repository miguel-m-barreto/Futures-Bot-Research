from __future__ import annotations

from datetime import UTC, datetime

import pytest

from futures_bot.decision.replay_adapter import ReplayDecisionStackHandler
from futures_bot.domain.assets import AssetAmount
from futures_bot.domain.decisions import (
    DecisionIntent,
    DecisionIntentStatus,
    DecisionSourceKind,
    NoTradeDecision,
    NoTradeReasonKind,
    ProposedAction,
    TradeSide,
)
from futures_bot.domain.ids import BotId, DecisionIntentId
from futures_bot.domain.replay import (
    ReplayDispatchContext,
    ReplayInputKind,
    ReplayInstrumentRef,
    ReplayTimelineEvent,
    build_replay_dispatcher_fingerprint,
    build_replay_event_dispatch_receipt_id,
)
from futures_bot.domain.replay_decisions import (
    ReplayDecisionOutputKind,
    ReplayDecisionStackDescriptor,
    build_replay_decision_intent_id,
    build_replay_decision_stack_fingerprint,
    decode_replay_decision_output_record,
)
from futures_bot.ports.replay import ReplayEventHandlerPort
from futures_bot.replay.dispatch import LocalDeterministicReplayDispatcher


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _event(kind: ReplayInputKind = ReplayInputKind.MARK_PRICE) -> ReplayTimelineEvent:
    return ReplayTimelineEvent(
        event_id="event-1",
        batch_id="batch-1",
        input_dataset_id="input-ds-1",
        record_id="record-1",
        kind=kind,
        instrument=ReplayInstrumentRef(
            venue="binance",
            symbol="BTCUSDT",
            market_type="stablecoin-collateral-futures",
            settlement_asset="USDT",
        ),
        event_time=_utc(),
        source_sequence=0,
        order_index=0,
    )


def _context(
    handler: ReplayDecisionStackHandler,
    event: ReplayTimelineEvent,
) -> ReplayDispatchContext:
    dispatcher_fingerprint = build_replay_dispatcher_fingerprint(
        (
            LocalDeterministicReplayDispatcher((handler,)).descriptors[0],
        )
    )
    return ReplayDispatchContext(
        run_id="run-1",
        manifest_id="manifest-1",
        replay_plan_id="plan-1",
        timeline_id="timeline-1",
        timeline_fingerprint_id="fp-1",
        dispatcher_fingerprint=dispatcher_fingerprint,
        event_id=event.event_id,
        event_order_index=event.order_index,
        event_time=event.event_time,
        event_kind=event.kind,
    )


class _Stack:
    def __init__(self) -> None:
        self.stack_id = "stack-1"
        self.stack_version = "1"
        self.bot_id = BotId("bot-1")
        self.source_kind = DecisionSourceKind.ML_MODEL
        self.supported_event_kinds = (ReplayInputKind.MARK_PRICE,)
        self.calls = 0
        self.outputs: tuple[DecisionIntent | NoTradeDecision, ...] = ()
        self.fail = False
        self.mutate_during_decide: tuple[str, object] | None = None

    def descriptor(self) -> ReplayDecisionStackDescriptor:
        return ReplayDecisionStackDescriptor(
            stack_id=self.stack_id,
            stack_version=self.stack_version,
            bot_id=self.bot_id,
            source_kind=self.source_kind,
            supported_event_kinds=self.supported_event_kinds,
        )

    def decision_id(self, context: ReplayDispatchContext, index: int) -> DecisionIntentId:
        return build_replay_decision_intent_id(
            run_id=context.run_id,
            event_order_index=context.event_order_index,
            event_id=context.event_id,
            decision_stack_fingerprint=build_replay_decision_stack_fingerprint(
                self.descriptor()
            ),
            decision_index=index,
        )

    def intent(
        self,
        context: ReplayDispatchContext,
        index: int = 0,
        *,
        status: DecisionIntentStatus = DecisionIntentStatus.PROPOSED,
        decision_id: DecisionIntentId | None = None,
    ) -> DecisionIntent:
        return DecisionIntent(
            decision_intent_id=decision_id or self.decision_id(context, index),
            bot_id=self.bot_id,
            instrument="BTC/USDT",
            side=TradeSide.LONG,
            proposed_action=ProposedAction.OPEN_POSITION,
            source_kind=self.source_kind,
            source_id=self.stack_id,
            created_at=context.event_time,
            proposed_margin=AssetAmount(asset="USDT", amount="12.3400"),
            confidence="0.8",
            status=status,
        )

    def no_trade(self, context: ReplayDispatchContext, index: int = 0) -> NoTradeDecision:
        return NoTradeDecision(
            decision_intent_id=self.decision_id(context, index),
            bot_id=self.bot_id,
            instrument="BTC/USDT",
            source_kind=self.source_kind,
            source_id=self.stack_id,
            created_at=context.event_time,
            reasons=(NoTradeReasonKind.MARKET_TOO_UNCERTAIN,),
        )

    def decide(
        self,
        context: ReplayDispatchContext,
        event: ReplayTimelineEvent,
    ) -> tuple[DecisionIntent | NoTradeDecision, ...]:
        self.calls += 1
        if self.fail:
            raise ValueError("boom")
        if self.mutate_during_decide is not None:
            field_name, value = self.mutate_during_decide
            setattr(self, field_name, value)
        return self.outputs


def test_handler_structurally_conforms_and_snapshots_descriptor() -> None:
    stack = _Stack()
    handler: ReplayEventHandlerPort = ReplayDecisionStackHandler(stack)

    assert handler.handler_id == build_replay_decision_stack_fingerprint(
        stack.descriptor()
    )
    assert handler.handler_version == "1"
    assert handler.supported_event_kinds == (ReplayInputKind.MARK_PRICE,)

    stack.stack_version = "2"
    assert handler.handler_version == "1"


def test_unsupported_event_rejected_without_calling_stack() -> None:
    stack = _Stack()
    handler = ReplayDecisionStackHandler(stack)
    event = _event(ReplayInputKind.TRADE)
    context = _context(handler, event)

    with pytest.raises(ValueError, match="support"):
        handler.handle(context, event)
    assert stack.calls == 0


def test_stack_called_once_and_output_order_is_preserved() -> None:
    stack = _Stack()
    handler = ReplayDecisionStackHandler(stack)
    event = _event()
    context = _context(handler, event)
    stack.outputs = (stack.intent(context, 0), stack.no_trade(context, 1))

    proposals = handler.handle(context, event)

    assert stack.calls == 1
    assert [proposal.output_kind for proposal in proposals] == [
        ReplayDecisionOutputKind.DECISION_INTENT.value,
        ReplayDecisionOutputKind.NO_TRADE_DECISION.value,
    ]


def test_empty_tuple_wrong_id_and_wrong_status_are_rejected() -> None:
    stack = _Stack()
    handler = ReplayDecisionStackHandler(stack)
    event = _event()
    context = _context(handler, event)

    with pytest.raises(ValueError, match="at least one"):
        handler.handle(context, event)

    stack.outputs = (
        stack.intent(context, decision_id=DecisionIntentId("bad-id")),
    )
    with pytest.raises(ValueError, match="decision index 0"):
        handler.handle(context, event)

    stack.outputs = (
        stack.intent(context, status=DecisionIntentStatus.CANCELLED),
    )
    with pytest.raises(ValueError, match="decision index 0"):
        handler.handle(context, event)


def test_invalid_second_output_returns_no_partial_tuple() -> None:
    stack = _Stack()
    handler = ReplayDecisionStackHandler(stack)
    event = _event()
    context = _context(handler, event)
    stack.outputs = (
        stack.intent(context, 0),
        stack.intent(context, 1, decision_id=DecisionIntentId("bad-id")),
    )

    with pytest.raises(ValueError, match="decision index 1"):
        handler.handle(context, event)


def test_mutable_metadata_after_construction_rejected_before_decide() -> None:
    stack = _Stack()
    handler = ReplayDecisionStackHandler(stack)
    event = _event()
    context = _context(handler, event)
    stack.outputs = (stack.intent(context),)
    stack.stack_id = "other"

    with pytest.raises(ValueError, match="metadata changed"):
        handler.handle(context, event)
    assert stack.calls == 0


def test_stack_exception_is_propagated() -> None:
    stack = _Stack()
    handler = ReplayDecisionStackHandler(stack)
    event = _event()
    context = _context(handler, event)
    stack.outputs = (stack.intent(context),)
    stack.fail = True

    with pytest.raises(ValueError, match="boom"):
        handler.handle(context, event)


def test_dispatcher_records_decode_back_to_typed_envelopes() -> None:
    stack = _Stack()
    handler = ReplayDecisionStackHandler(stack)
    dispatcher = LocalDeterministicReplayDispatcher((handler,))
    event = _event()
    context = ReplayDispatchContext(
        **{
            **_context(handler, event).model_dump(),
            "dispatcher_fingerprint": dispatcher.dispatcher_fingerprint,
        }
    )
    stack.outputs = (stack.intent(context),)
    plan = dispatcher.plan_dispatch(
        context,
        event,
        dispatch_receipt_id=build_replay_event_dispatch_receipt_id(
            context.run_id,
            context.event_order_index,
            context.event_id,
        ),
    )

    assert decode_replay_decision_output_record(
        plan.output_records[0]
    ).decision_intent == stack.outputs[0]


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("stack_id", "other-stack"),
        ("stack_version", "2"),
        ("bot_id", BotId("bot-2")),
        ("source_kind", DecisionSourceKind.RULE_BASED),
        ("supported_event_kinds", (ReplayInputKind.TRADE,)),
    ),
)
def test_metadata_mutation_during_decide_is_rejected_after_single_call(
    field_name: str,
    value: object,
) -> None:
    stack = _Stack()
    handler = ReplayDecisionStackHandler(stack)
    event = _event()
    context = _context(handler, event)
    stack.outputs = (stack.intent(context),)
    stack.mutate_during_decide = (field_name, value)

    with pytest.raises(ValueError, match="metadata changed during invocation"):
        handler.handle(context, event)
    assert stack.calls == 1
