from __future__ import annotations

import hashlib

import pytest
from tests.unit.replay_decision_market_fixtures import (
    decision_id,
    replay_decision_market_fixture,
)

from futures_bot.decision.journal import LocalReplayDecisionJournal
from futures_bot.domain.decisions import DecisionIntent, ProposedAction, TradeSide
from futures_bot.domain.replay import (
    ReplayEventOutputRecord,
    build_replay_event_dispatch_receipt_id,
    build_replay_event_output_record_id,
)
from futures_bot.domain.replay_decisions import (
    ReplayDecisionOutputEnvelope,
    ReplayDecisionOutputKind,
    build_replay_decision_evidence_context_reference,
    build_replay_decision_market_context_reference,
    build_replay_decision_output_proposal,
)
from futures_bot.infrastructure.replay.in_memory import InMemoryReplayEventOutputRecordStore


def _envelope(decision_index: int = 0) -> ReplayDecisionOutputEnvelope:
    fixture = replay_decision_market_fixture()
    decision = DecisionIntent(
        decision_intent_id=decision_id(fixture, decision_index),
        bot_id=fixture.stack_descriptor.bot_id,
        instrument="BTC/USDT",
        side=TradeSide.LONG,
        proposed_action=ProposedAction.OPEN_POSITION,
        source_kind=fixture.stack_descriptor.source_kind,
        source_id=fixture.stack_descriptor.stack_id,
        created_at=fixture.event.event_time,
    )
    return ReplayDecisionOutputEnvelope(
        run_id=fixture.dispatch_context.run_id,
        manifest_id=fixture.dispatch_context.manifest_id,
        replay_plan_id=fixture.dispatch_context.replay_plan_id,
        timeline_id=fixture.dispatch_context.timeline_id,
        timeline_fingerprint_id=fixture.dispatch_context.timeline_fingerprint_id,
        dispatcher_fingerprint=fixture.dispatch_context.dispatcher_fingerprint,
        event_id=fixture.event.event_id,
        event_order_index=fixture.event.order_index,
        event_time=fixture.event.event_time,
        event_kind=fixture.event.kind,
        stack_descriptor=fixture.stack_descriptor,
        market_lookup_descriptor=fixture.lookup.descriptor,
        evidence_lookup_descriptor=fixture.evidence_lookup.descriptor,
        market_context_reference=build_replay_decision_market_context_reference(
            fixture.decision_context
        ),
        evidence_context_reference=build_replay_decision_evidence_context_reference(
            fixture.decision_context
        ),
        decision_index=decision_index,
        decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
        decision_intent=decision,
    )


def _record(envelope: ReplayDecisionOutputEnvelope):
    fixture = replay_decision_market_fixture()
    proposal = build_replay_decision_output_proposal(envelope)
    payload_sha256 = hashlib.sha256(proposal.canonical_payload.encode("utf-8")).hexdigest()
    return ReplayEventOutputRecord(
        output_record_id=build_replay_event_output_record_id(
            run_id=envelope.run_id,
            event_order_index=envelope.event_order_index,
            event_id=envelope.event_id,
            handler_id=fixture.handler_fingerprint,
            handler_version=envelope.stack_descriptor.stack_version,
            handler_output_index=envelope.decision_index,
            output_kind=proposal.output_kind,
            payload_sha256=payload_sha256,
        ),
        dispatch_receipt_id=build_replay_event_dispatch_receipt_id(
            envelope.run_id,
            envelope.event_order_index,
            envelope.event_id,
        ),
        run_id=envelope.run_id,
        manifest_id=envelope.manifest_id,
        replay_plan_id=envelope.replay_plan_id,
        timeline_id=envelope.timeline_id,
        timeline_fingerprint_id=envelope.timeline_fingerprint_id,
        dispatcher_fingerprint=envelope.dispatcher_fingerprint,
        event_id=envelope.event_id,
        event_order_index=envelope.event_order_index,
        event_time=envelope.event_time,
        event_kind=envelope.event_kind,
        handler_id=fixture.handler_fingerprint,
        handler_version=envelope.stack_descriptor.stack_version,
        handler_output_index=envelope.decision_index,
        output_kind=proposal.output_kind,
        canonical_payload=proposal.canonical_payload,
        payload_sha256=payload_sha256,
    )


def test_journal_ignores_unrelated_outputs_and_preserves_store_order() -> None:
    store = InMemoryReplayEventOutputRecordStore()
    first = _envelope(0)
    second = _envelope(1)
    store.save(_record(first))
    unrelated = _record(first).model_copy(
        update={"output_kind": "unrelated.output"}
    )
    unrelated = unrelated.model_copy(
        update={
            "output_record_id": build_replay_event_output_record_id(
                run_id=unrelated.run_id,
                event_order_index=unrelated.event_order_index,
                event_id=unrelated.event_id,
                handler_id=unrelated.handler_id,
                handler_version=unrelated.handler_version,
                handler_output_index=unrelated.handler_output_index,
                output_kind=unrelated.output_kind,
                payload_sha256=unrelated.payload_sha256,
            )
        }
    )
    store.save(unrelated)
    store.save(_record(second))

    journal = LocalReplayDecisionJournal(store)

    assert journal.decisions_for_run("run-1") == (first, second)
    assert journal.decisions_for_event("run-1", 0) == (first, second)


def test_journal_validates_inputs_and_malformed_recognized_output() -> None:
    store = InMemoryReplayEventOutputRecordStore()
    envelope = _envelope()
    malformed = _record(envelope)
    store._records[malformed.output_record_id] = malformed.model_construct(
        **{**malformed.model_dump(), "canonical_payload": "{}"}
    )
    journal = LocalReplayDecisionJournal(store)

    with pytest.raises(ValueError):
        journal.decisions_for_run(" ")
    with pytest.raises(ValueError):
        journal.decisions_for_event("run-1", -1)
    with pytest.raises(ValueError):
        journal.decisions_for_run("run-1")
