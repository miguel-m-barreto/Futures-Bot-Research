from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from futures_bot.decision.journal import LocalReplayDecisionJournal
from futures_bot.domain.decisions import (
    DecisionIntent,
    DecisionSourceKind,
    NoTradeDecision,
    NoTradeReasonKind,
    ProposedAction,
    TradeSide,
)
from futures_bot.domain.ids import BotId
from futures_bot.domain.replay import (
    ReplayEventOutputRecord,
    ReplayInputKind,
    build_replay_event_dispatch_receipt_id,
    build_replay_event_output_record_id,
)
from futures_bot.domain.replay_decisions import (
    ReplayDecisionOutputEnvelope,
    ReplayDecisionOutputKind,
    ReplayDecisionStackDescriptor,
    build_replay_decision_intent_id,
    build_replay_decision_output_proposal,
    build_replay_decision_stack_fingerprint,
    decode_replay_decision_output_record,
)
from futures_bot.infrastructure.replay.in_memory import (
    InMemoryReplayEventOutputRecordStore,
)


def _utc(minute: int = 0) -> datetime:
    return datetime(2026, 1, 1, 0, minute, tzinfo=UTC)


def _descriptor(stack_id: str = "stack-1") -> ReplayDecisionStackDescriptor:
    return ReplayDecisionStackDescriptor(
        stack_id=stack_id,
        stack_version="1",
        bot_id=BotId(f"bot-{stack_id[-1]}"),
        source_kind=DecisionSourceKind.ML_MODEL,
        supported_event_kinds=(ReplayInputKind.MARK_PRICE,),
    )


def _decision_id(
    descriptor: ReplayDecisionStackDescriptor,
    index: int,
    *,
    event_order_index: int = 0,
    event_id: str = "event-1",
) -> object:
    return build_replay_decision_intent_id(
        run_id="run-1",
        event_order_index=event_order_index,
        event_id=event_id,
        decision_stack_fingerprint=build_replay_decision_stack_fingerprint(descriptor),
        decision_index=index,
    )


def _envelope(
    *,
    stack_id: str = "stack-1",
    decision_index: int = 0,
    event_order_index: int = 0,
    no_trade: bool = False,
) -> ReplayDecisionOutputEnvelope:
    descriptor = _descriptor(stack_id)
    event_id = f"event-{event_order_index + 1}"
    if no_trade:
        return ReplayDecisionOutputEnvelope(
            run_id="run-1",
            event_id=event_id,
            event_order_index=event_order_index,
            event_time=_utc(event_order_index),
            event_kind=ReplayInputKind.MARK_PRICE,
            stack_descriptor=descriptor,
            decision_index=decision_index,
            decision_kind=ReplayDecisionOutputKind.NO_TRADE_DECISION,
            no_trade_decision=NoTradeDecision(
                decision_intent_id=_decision_id(
                    descriptor,
                    decision_index,
                    event_order_index=event_order_index,
                    event_id=event_id,
                ),
                bot_id=descriptor.bot_id,
                instrument="BTC/USDT",
                source_kind=descriptor.source_kind,
                source_id=descriptor.stack_id,
                created_at=_utc(event_order_index),
                reasons=(NoTradeReasonKind.MARKET_TOO_UNCERTAIN,),
            ),
        )
    return ReplayDecisionOutputEnvelope(
        run_id="run-1",
        event_id=event_id,
        event_order_index=event_order_index,
        event_time=_utc(event_order_index),
        event_kind=ReplayInputKind.MARK_PRICE,
        stack_descriptor=descriptor,
        decision_index=decision_index,
        decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
        decision_intent=DecisionIntent(
            decision_intent_id=_decision_id(
                descriptor,
                decision_index,
                event_order_index=event_order_index,
                event_id=event_id,
            ),
            bot_id=descriptor.bot_id,
            instrument="BTC/USDT",
            side=TradeSide.LONG,
            proposed_action=ProposedAction.OPEN_POSITION,
            source_kind=descriptor.source_kind,
            source_id=descriptor.stack_id,
            created_at=_utc(event_order_index),
        ),
    )


def _record(
    envelope: ReplayDecisionOutputEnvelope,
    *,
    output_kind: str | None = None,
    payload: str | None = None,
) -> ReplayEventOutputRecord:
    proposal = build_replay_decision_output_proposal(envelope)
    selected_payload = payload or proposal.canonical_payload
    selected_kind = output_kind or proposal.output_kind
    payload_sha256 = hashlib.sha256(selected_payload.encode()).hexdigest()
    handler_id = build_replay_decision_stack_fingerprint(envelope.stack_descriptor)
    return ReplayEventOutputRecord(
        output_record_id=build_replay_event_output_record_id(
            run_id=envelope.run_id,
            event_order_index=envelope.event_order_index,
            event_id=envelope.event_id,
            handler_id=handler_id,
            handler_version=envelope.stack_descriptor.stack_version,
            handler_output_index=envelope.decision_index,
            output_kind=selected_kind,
            payload_sha256=payload_sha256,
        ),
        dispatch_receipt_id=build_replay_event_dispatch_receipt_id(
            envelope.run_id,
            envelope.event_order_index,
            envelope.event_id,
        ),
        run_id=envelope.run_id,
        manifest_id="manifest-1",
        replay_plan_id="plan-1",
        timeline_id="timeline-1",
        timeline_fingerprint_id="fp-1",
        dispatcher_fingerprint="replay-dispatcher:" + "0" * 64,
        event_id=envelope.event_id,
        event_order_index=envelope.event_order_index,
        event_time=envelope.event_time,
        event_kind=envelope.event_kind,
        handler_id=handler_id,
        handler_version=envelope.stack_descriptor.stack_version,
        handler_output_index=envelope.decision_index,
        output_kind=selected_kind,
        canonical_payload=selected_payload,
        payload_sha256=payload_sha256,
    )


def test_journal_ignores_unrelated_outputs_and_preserves_store_order() -> None:
    store = InMemoryReplayEventOutputRecordStore()
    first = _envelope(stack_id="stack-1", event_order_index=0)
    second = _envelope(stack_id="stack-2", event_order_index=0, decision_index=0)
    third = _envelope(stack_id="stack-1", event_order_index=1, no_trade=True)
    for envelope in (third, first, second):
        store.save(_record(envelope))
    store.save(_record(first, output_kind="audit"))

    journal = LocalReplayDecisionJournal(store)
    expected_run = tuple(
        decode_replay_decision_output_record(record)
        for record in store.list_for_run("run-1")
        if record.output_kind != "audit"
    )
    expected_event = tuple(
        decode_replay_decision_output_record(record)
        for record in store.list_for_event("run-1", 0)
        if record.output_kind != "audit"
    )

    assert journal.decisions_for_run("run-1") == expected_run
    assert journal.decisions_for_event("run-1", 0) == expected_event
    assert {first, second, third} == set(expected_run)


def test_journal_validates_inputs_and_raises_on_malformed_recognized_output() -> None:
    store = InMemoryReplayEventOutputRecordStore()
    envelope = _envelope()
    store.save(
        _record(
            envelope,
            payload='{"schema_version":1}',
        )
    )
    journal = LocalReplayDecisionJournal(store)

    with pytest.raises(ValueError, match="run_id"):
        journal.decisions_for_run(" ")
    with pytest.raises(ValueError, match="event_order_index"):
        journal.decisions_for_event("run-1", True)
    with pytest.raises(ValidationError):
        journal.decisions_for_run("run-1")
