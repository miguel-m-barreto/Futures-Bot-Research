from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError
from tests.unit.replay_decision_market_fixtures import (
    NOW,
    decision_id,
    replay_decision_market_fixture,
    stack_descriptor,
)

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
from futures_bot.domain.replay import ReplayInputKind
from futures_bot.domain.replay_decisions import (
    ReplayDecisionOutputEnvelope,
    ReplayDecisionOutputKind,
    ReplayDecisionStackContext,
    build_replay_decision_handler_fingerprint,
    build_replay_decision_intent_id,
    build_replay_decision_market_context_reference,
    build_replay_decision_stack_context_id,
    build_replay_decision_stack_fingerprint,
)


def _intent(  # noqa: PLR0913 - explicit invalid envelope fixture
    fixture,
    *,
    decision_index: int = 0,
    status: DecisionIntentStatus = DecisionIntentStatus.PROPOSED,
    decision_intent_id: DecisionIntentId | None = None,
    bot_id: BotId | None = None,
    source_kind: DecisionSourceKind | None = None,
    source_id: str | None = None,
    created_at=None,
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
        valid_until=fixture.event.event_time + timedelta(minutes=5),
        proposed_margin=AssetAmount(asset="USDT", amount="12.3400"),
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
        confidence="0.4",
    )


def _envelope(fixture, decision, *, decision_index: int = 0) -> ReplayDecisionOutputEnvelope:
    kind = (
        ReplayDecisionOutputKind.DECISION_INTENT
        if isinstance(decision, DecisionIntent)
        else ReplayDecisionOutputKind.NO_TRADE_DECISION
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
        market_context_reference=build_replay_decision_market_context_reference(
            fixture.decision_context
        ),
        decision_index=decision_index,
        decision_kind=kind,
        decision_intent=decision if isinstance(decision, DecisionIntent) else None,
        no_trade_decision=decision if isinstance(decision, NoTradeDecision) else None,
    )


def test_descriptor_fingerprints_and_handler_fingerprint_change_with_market() -> None:
    descriptor = stack_descriptor(
        supported_event_kinds=(ReplayInputKind.MARK_PRICE, ReplayInputKind.TRADE)
    )
    assert descriptor.supported_event_kinds == (
        ReplayInputKind.MARK_PRICE,
        ReplayInputKind.TRADE,
    )
    assert build_replay_decision_stack_fingerprint(descriptor).startswith(
        "decision-stack:"
    )

    first = replay_decision_market_fixture(descriptor=descriptor)
    changed_market = replay_decision_market_fixture(price="101", descriptor=descriptor)
    assert build_replay_decision_handler_fingerprint(
        stack_descriptor=descriptor,
        market_lookup_descriptor=first.lookup.descriptor,
    ) != build_replay_decision_handler_fingerprint(
        stack_descriptor=descriptor,
        market_lookup_descriptor=changed_market.lookup.descriptor,
    )

    with pytest.raises(ValidationError, match="sorted"):
        stack_descriptor(
            supported_event_kinds=(ReplayInputKind.TRADE, ReplayInputKind.MARK_PRICE)
        )


def test_decision_context_id_and_reference_are_deterministic_and_compact() -> None:
    fixture = replay_decision_market_fixture()
    context = fixture.decision_context
    reference = build_replay_decision_market_context_reference(context)

    assert ReplayDecisionStackContext.model_validate(context.model_dump()) == context
    assert context.context_id == build_replay_decision_stack_context_id(
        dispatch_context=fixture.dispatch_context,
        event=fixture.event,
        market=context.market,
    )
    assert reference.context_id == context.context_id
    dumped = reference.model_dump(mode="json")
    assert "frame" not in dumped
    assert "observations" not in dumped
    assert reference.frame_id == context.market.frame_projection.frame.frame_id
    assert reference.binding_authority_fingerprint == (
        context.market.observation_projection.binding_authority.binding_authority_fingerprint
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("run_id", "run-forged"),
        ("manifest_id", "manifest-forged"),
        ("replay_plan_id", "plan-forged"),
        ("replay_timeline_id", "timeline-forged"),
        ("timeline_fingerprint_id", "fp-forged"),
        ("event_id", "event-forged"),
        ("event_order_index", 99),
        ("lookup_authority_fingerprint", "replay-market-frame-lookup-authority:" + "0" * 64),
        ("adapter_fingerprint", "replay-market-adapter:" + "0" * 64),
    ),
)
def test_market_context_reference_rejects_tampering_with_old_reference_id(
    field_name: str,
    value: object,
) -> None:
    fixture = replay_decision_market_fixture()
    reference = build_replay_decision_market_context_reference(fixture.decision_context)
    payload = reference.model_dump()
    payload[field_name] = value

    with pytest.raises(ValidationError, match="reference_id"):
        type(reference).model_validate(payload)


def test_decision_context_rejects_dispatch_event_and_market_mismatches() -> None:
    fixture = replay_decision_market_fixture()

    with pytest.raises(ValidationError, match="event_id"):
        ReplayDecisionStackContext.model_validate(
            fixture.decision_context.model_copy(
                update={
                    "event": fixture.event.model_copy(update={"event_id": "event-other"})
                }
            ).model_dump()
        )
    with pytest.raises(ValidationError, match="timeline_id"):
        ReplayDecisionStackContext.model_validate(
            fixture.decision_context.model_copy(
                update={
                    "dispatch_context": fixture.dispatch_context.model_copy(
                        update={"timeline_id": "other-timeline"}
                    )
                }
            ).model_dump()
        )


def test_decision_id_commits_to_handler_and_market_context() -> None:
    fixture = replay_decision_market_fixture()
    changed_market = replay_decision_market_fixture(price="101")

    first = decision_id(fixture)
    assert first == decision_id(fixture)
    assert first != decision_id(changed_market)
    assert first != build_replay_decision_intent_id(
        run_id=fixture.dispatch_context.run_id,
        event_order_index=fixture.dispatch_context.event_order_index,
        event_id=fixture.dispatch_context.event_id,
        decision_handler_fingerprint="replay-decision-handler:" + "0" * 64,
        market_context_reference_id=build_replay_decision_market_context_reference(
            fixture.decision_context
        ).reference_id,
        decision_index=0,
    )

    with pytest.raises(ValueError):
        build_replay_decision_intent_id(
            run_id="run-1",
            event_order_index=True,
            event_id="event-1",
            decision_handler_fingerprint=fixture.handler_fingerprint,
            market_context_reference_id=build_replay_decision_market_context_reference(
                fixture.decision_context
            ).reference_id,
            decision_index=0,
        )


def test_v2_decision_intent_and_no_trade_envelopes_round_trip() -> None:
    fixture = replay_decision_market_fixture()
    intent = _intent(fixture)
    no_trade = _no_trade(fixture)

    intent_envelope = _envelope(fixture, intent)
    no_trade_envelope = _envelope(fixture, no_trade)

    assert intent_envelope.schema_version == 2
    assert intent_envelope.decision_kind is ReplayDecisionOutputKind.DECISION_INTENT
    assert intent_envelope.decision_intent == intent
    assert no_trade_envelope.no_trade_decision == no_trade
    assert ReplayDecisionOutputEnvelope.model_validate(
        intent_envelope.model_dump(mode="json")
    ) == intent_envelope


def test_recomputed_market_reference_with_old_decision_id_is_rejected() -> None:
    fixture = replay_decision_market_fixture(price="100")
    changed = replay_decision_market_fixture(price="101")
    payload = _envelope(fixture, _intent(fixture)).model_dump()
    payload["market_lookup_descriptor"] = changed.lookup.descriptor.model_dump()
    payload["market_context_reference"] = build_replay_decision_market_context_reference(
        changed.decision_context
    ).model_dump()

    with pytest.raises(ValidationError, match="decision_intent_id"):
        ReplayDecisionOutputEnvelope.model_validate(payload)


def test_envelope_rejects_valid_market_reference_from_another_event() -> None:
    fixture = replay_decision_market_fixture(event_id="event-1", event_order_index=0)
    other_event = replay_decision_market_fixture(event_id="event-2", event_order_index=0)
    payload = _envelope(fixture, _intent(fixture)).model_dump()
    payload["market_context_reference"] = build_replay_decision_market_context_reference(
        other_event.decision_context
    ).model_dump()

    with pytest.raises(ValidationError, match="event_id"):
        ReplayDecisionOutputEnvelope.model_validate(payload)


@pytest.mark.parametrize(
    ("intent_kwargs", "match"),
    (
        ({"bot_id": BotId("other")}, "bot_id"),
        ({"source_kind": DecisionSourceKind.RULE_BASED}, "source_kind"),
        ({"source_id": "other"}, "source_id"),
        ({"created_at": NOW + timedelta(seconds=1)}, "created_at"),
        ({"status": DecisionIntentStatus.CANCELLED}, "PROPOSED"),
    ),
)
def test_envelope_rejects_invalid_decision_binding(intent_kwargs, match: str) -> None:
    fixture = replay_decision_market_fixture()
    with pytest.raises(ValidationError, match=match):
        _envelope(fixture, _intent(fixture, **intent_kwargs))


def test_envelope_rejects_v1_kind_and_market_reference_mismatches() -> None:
    fixture = replay_decision_market_fixture()
    payload = _envelope(fixture, _intent(fixture)).model_dump()
    payload["decision_kind"] = "replay.decision-intent.v1"
    with pytest.raises(ValidationError):
        ReplayDecisionOutputEnvelope.model_validate(payload)

    payload = _envelope(fixture, _intent(fixture)).model_dump()
    payload["market_context_reference"]["adapter_fingerprint"] = (
        "replay-market-adapter:" + "0" * 64
    )
    with pytest.raises(ValidationError, match="reference_id"):
        ReplayDecisionOutputEnvelope.model_validate(payload)
