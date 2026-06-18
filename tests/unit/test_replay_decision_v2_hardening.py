from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError
from tests.unit.replay_decision_market_fixtures import (
    decision_id,
    replay_decision_market_fixture,
    stack_descriptor,
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
from futures_bot.domain.ids import (
    BotId,
    DecisionIntentId,
    ReplayDecisionMarketContextReferenceId,
)
from futures_bot.domain.replay import ReplayInputKind
from futures_bot.domain.replay_decisions import (
    ReplayDecisionOutputEnvelope,
    ReplayDecisionOutputKind,
    ReplayDecisionStackDescriptor,
    build_replay_decision_intent_id,
    build_replay_decision_market_context_reference,
    build_replay_decision_stack_fingerprint,
)


def _reference_id(fixture) -> ReplayDecisionMarketContextReferenceId:
    return build_replay_decision_market_context_reference(
        fixture.decision_context
    ).reference_id


def _intent(  # noqa: PLR0913
    fixture,
    *,
    decision_index: int = 0,
    decision_intent_id: DecisionIntentId | None = None,
    bot_id: BotId | None = None,
    source_kind: DecisionSourceKind | None = None,
    source_id: str | None = None,
    created_at=None,
    status: DecisionIntentStatus = DecisionIntentStatus.PROPOSED,
) -> DecisionIntent:
    descriptor = fixture.stack_descriptor
    return DecisionIntent(
        decision_intent_id=decision_intent_id or decision_id(fixture, decision_index),
        bot_id=bot_id or descriptor.bot_id,
        instrument="BTC/USDT",
        side=TradeSide.LONG,
        proposed_action=ProposedAction.OPEN_POSITION,
        source_kind=source_kind or descriptor.source_kind,
        source_id=source_id or descriptor.stack_id,
        created_at=created_at or fixture.event.event_time,
        confidence="0.7",
        status=status,
    )


def _no_trade(fixture, *, decision_index: int = 0) -> NoTradeDecision:
    descriptor = fixture.stack_descriptor
    return NoTradeDecision(
        decision_intent_id=decision_id(fixture, decision_index),
        bot_id=descriptor.bot_id,
        instrument="BTC/USDT",
        source_kind=descriptor.source_kind,
        source_id=descriptor.stack_id,
        created_at=fixture.event.event_time,
        reasons=(NoTradeReasonKind.MARKET_TOO_UNCERTAIN,),
    )


def _envelope(
    fixture,
    *,
    decision_kind: ReplayDecisionOutputKind = ReplayDecisionOutputKind.DECISION_INTENT,
    decision_intent: DecisionIntent | None = None,
    no_trade_decision: NoTradeDecision | None = None,
) -> ReplayDecisionOutputEnvelope:
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
        market_context_reference=build_replay_decision_market_context_reference(
            fixture.decision_context
        ),
        decision_index=0,
        decision_kind=decision_kind,
        decision_intent=decision_intent,
        no_trade_decision=no_trade_decision,
    )


@pytest.mark.parametrize(
    ("payload", "match"),
    (
        ({"stack_id": ""}, "stack_id"),
        ({"stack_version": ""}, "stack_version"),
        (
            {"supported_event_kinds": (ReplayInputKind.MARK_PRICE, ReplayInputKind.MARK_PRICE)},
            "duplicate",
        ),
        (
            {"supported_event_kinds": (ReplayInputKind.TRADE, ReplayInputKind.MARK_PRICE)},
            "sorted",
        ),
    ),
)
def test_stack_descriptor_validation(payload: dict[str, object], match: str) -> None:
    descriptor = stack_descriptor(
        supported_event_kinds=(ReplayInputKind.MARK_PRICE, ReplayInputKind.TRADE)
    )
    with pytest.raises(ValidationError, match=match):
        ReplayDecisionStackDescriptor.model_validate(
            descriptor.model_copy(update=payload).model_dump()
        )


def test_stack_fingerprint_changes_for_each_descriptor_field() -> None:
    base = stack_descriptor()
    base_fingerprint = build_replay_decision_stack_fingerprint(base)
    variants = (
        base.model_copy(update={"stack_id": "stack-2"}),
        base.model_copy(update={"stack_version": "2"}),
        base.model_copy(update={"bot_id": BotId("bot-2")}),
        base.model_copy(update={"source_kind": DecisionSourceKind.RULE_BASED}),
        base.model_copy(
            update={
                "supported_event_kinds": (
                    ReplayInputKind.MARK_PRICE,
                    ReplayInputKind.TRADE,
                )
            }
        ),
    )

    assert all(
        build_replay_decision_stack_fingerprint(variant) != base_fingerprint
        for variant in variants
    )


def test_decision_id_hardening_and_delimiter_safety() -> None:
    fixture = replay_decision_market_fixture()
    reference_id = _reference_id(fixture)
    base = build_replay_decision_intent_id(
        run_id="run|a",
        event_order_index=0,
        event_id="event|b",
        decision_handler_fingerprint=fixture.handler_fingerprint,
        market_context_reference_id=reference_id,
        decision_index=0,
    )

    assert base == build_replay_decision_intent_id(
        run_id="run|a",
        event_order_index=0,
        event_id="event|b",
        decision_handler_fingerprint=fixture.handler_fingerprint,
        market_context_reference_id=reference_id,
        decision_index=0,
    )
    assert base != build_replay_decision_intent_id(
        run_id="run|a",
        event_order_index=0,
        event_id="event|b",
        decision_handler_fingerprint=fixture.handler_fingerprint,
        market_context_reference_id=reference_id,
        decision_index=1,
    )
    assert base != build_replay_decision_intent_id(
        run_id="run|a",
        event_order_index=0,
        event_id="event|b",
        decision_handler_fingerprint="replay-decision-handler:" + "0" * 64,
        market_context_reference_id=reference_id,
        decision_index=0,
    )
    assert base != build_replay_decision_intent_id(
        run_id="run|a",
        event_order_index=0,
        event_id="event|b",
        decision_handler_fingerprint=fixture.handler_fingerprint,
        market_context_reference_id=ReplayDecisionMarketContextReferenceId(
            "replay-decision-market-context-reference:" + "1" * 64
        ),
        decision_index=0,
    )
    assert build_replay_decision_intent_id(
        run_id="a|b",
        event_order_index=0,
        event_id="c",
        decision_handler_fingerprint=fixture.handler_fingerprint,
        market_context_reference_id=reference_id,
        decision_index=0,
    ) != build_replay_decision_intent_id(
        run_id="a",
        event_order_index=0,
        event_id="b|c",
        decision_handler_fingerprint=fixture.handler_fingerprint,
        market_context_reference_id=reference_id,
        decision_index=0,
    )


@pytest.mark.parametrize(
    "kwargs",
    (
        {"event_order_index": True},
        {"decision_index": True},
        {"event_order_index": -1},
        {"decision_index": -1},
        {"decision_handler_fingerprint": "bad"},
        {"market_context_reference_id": ReplayDecisionMarketContextReferenceId("bad")},
    ),
)
def test_decision_id_rejects_invalid_material(kwargs: dict[str, object]) -> None:
    fixture = replay_decision_market_fixture()
    values = {
        "run_id": fixture.dispatch_context.run_id,
        "event_order_index": fixture.dispatch_context.event_order_index,
        "event_id": fixture.dispatch_context.event_id,
        "decision_handler_fingerprint": fixture.handler_fingerprint,
        "market_context_reference_id": _reference_id(fixture),
        "decision_index": 0,
    }
    values.update(kwargs)

    with pytest.raises(ValueError):
        build_replay_decision_intent_id(**values)


@pytest.mark.parametrize("no_trade", [False, True])
def test_valid_v2_envelopes(no_trade: bool) -> None:
    fixture = replay_decision_market_fixture()
    envelope = _envelope(
        fixture,
        decision_kind=(
            ReplayDecisionOutputKind.NO_TRADE_DECISION
            if no_trade
            else ReplayDecisionOutputKind.DECISION_INTENT
        ),
        decision_intent=None if no_trade else _intent(fixture),
        no_trade_decision=_no_trade(fixture) if no_trade else None,
    )

    assert ReplayDecisionOutputEnvelope.model_validate(envelope.model_dump()) == envelope


@pytest.mark.parametrize(
    ("updates", "match"),
    (
        ({"decision_intent": None, "no_trade_decision": None}, "exactly one"),
        (
            {"decision_intent": "intent", "no_trade_decision": "no_trade"},
            "exactly one",
        ),
        (
            {"decision_kind": ReplayDecisionOutputKind.NO_TRADE_DECISION},
            "decision_kind",
        ),
        ({"event_kind": ReplayInputKind.TRADE}, "event_kind"),
        ({"schema_version": 1}, "schema_version"),
    ),
)
def test_v2_envelope_rejects_payload_and_metadata_mismatches(
    updates: dict[str, object],
    match: str,
) -> None:
    fixture = replay_decision_market_fixture()
    payload = _envelope(fixture, decision_intent=_intent(fixture)).model_dump()
    if updates.get("decision_intent") == "intent":
        updates = {
            **updates,
            "decision_intent": _intent(fixture).model_dump(),
            "no_trade_decision": _no_trade(fixture).model_dump(),
        }
    payload.update(updates)

    with pytest.raises(ValidationError, match=match):
        ReplayDecisionOutputEnvelope.model_validate(payload)


@pytest.mark.parametrize(
    ("intent", "match"),
    (
        ({"bot_id": BotId("bot-2")}, "bot_id"),
        ({"source_kind": DecisionSourceKind.RULE_BASED}, "source_kind"),
        ({"source_id": "stack-2"}, "source_id"),
        ({"created_at": "later"}, "created_at"),
        ({"status": DecisionIntentStatus.CANCELLED}, "PROPOSED"),
    ),
)
def test_v2_envelope_rejects_invalid_decision_binding(
    intent: dict[str, object],
    match: str,
) -> None:
    fixture = replay_decision_market_fixture()
    if intent.get("created_at") == "later":
        intent = {"created_at": fixture.event.event_time + timedelta(seconds=1)}

    with pytest.raises(ValidationError, match=match):
        _envelope(fixture, decision_intent=_intent(fixture, **intent))
