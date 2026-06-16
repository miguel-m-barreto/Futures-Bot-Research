from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

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
    ReplayDecisionStackDescriptor,
    build_replay_decision_intent_id,
    build_replay_decision_stack_fingerprint,
)


def _utc() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _descriptor(
    *,
    stack_id: str = "stack-1",
    stack_version: str = "1",
    bot_id: BotId | None = None,
    source_kind: DecisionSourceKind = DecisionSourceKind.ML_MODEL,
    supported_event_kinds: tuple[ReplayInputKind, ...] = (ReplayInputKind.MARK_PRICE,),
) -> ReplayDecisionStackDescriptor:
    return ReplayDecisionStackDescriptor(
        stack_id=stack_id,
        stack_version=stack_version,
        bot_id=bot_id or BotId("bot-1"),
        source_kind=source_kind,
        supported_event_kinds=supported_event_kinds,
    )


def _decision_id(
    descriptor: ReplayDecisionStackDescriptor,
    *,
    run_id: str = "run-1",
    event_order_index: int = 0,
    event_id: str = "event-1",
    decision_index: int = 0,
) -> DecisionIntentId:
    return build_replay_decision_intent_id(
        run_id=run_id,
        event_order_index=event_order_index,
        event_id=event_id,
        decision_stack_fingerprint=build_replay_decision_stack_fingerprint(descriptor),
        decision_index=decision_index,
    )


def _intent(  # noqa: PLR0913 - explicit invalid binding fixture
    descriptor: ReplayDecisionStackDescriptor,
    *,
    decision_index: int = 0,
    status: DecisionIntentStatus = DecisionIntentStatus.PROPOSED,
    bot_id: BotId | None = None,
    source_kind: DecisionSourceKind | None = None,
    source_id: str | None = None,
    created_at: datetime | None = None,
    decision_id: DecisionIntentId | None = None,
) -> DecisionIntent:
    return DecisionIntent(
        decision_intent_id=decision_id
        or _decision_id(descriptor, decision_index=decision_index),
        bot_id=bot_id or descriptor.bot_id,
        instrument="BTC/USDT",
        side=TradeSide.LONG,
        proposed_action=ProposedAction.OPEN_POSITION,
        source_kind=source_kind or descriptor.source_kind,
        source_id=source_id or descriptor.stack_id,
        created_at=created_at or _utc(),
        valid_until=_utc() + timedelta(minutes=5),
        confidence="0.7",
        status=status,
    )


def _no_trade(
    descriptor: ReplayDecisionStackDescriptor,
    *,
    decision_index: int = 0,
    decision_id: DecisionIntentId | None = None,
) -> NoTradeDecision:
    return NoTradeDecision(
        decision_intent_id=decision_id
        or _decision_id(descriptor, decision_index=decision_index),
        bot_id=descriptor.bot_id,
        instrument="BTC/USDT",
        source_kind=descriptor.source_kind,
        source_id=descriptor.stack_id,
        created_at=_utc(),
        reasons=(NoTradeReasonKind.MARKET_TOO_UNCERTAIN,),
        confidence="0.4",
    )


def test_descriptor_validates_identity_and_event_kind_order() -> None:
    descriptor = _descriptor(
        supported_event_kinds=(ReplayInputKind.MARK_PRICE, ReplayInputKind.TRADE)
    )

    assert descriptor.supported_event_kinds == (
        ReplayInputKind.MARK_PRICE,
        ReplayInputKind.TRADE,
    )

    with pytest.raises(ValidationError, match="non-empty"):
        _descriptor(stack_id=" ")
    with pytest.raises(ValidationError, match="duplicate"):
        _descriptor(
            supported_event_kinds=(ReplayInputKind.MARK_PRICE, ReplayInputKind.MARK_PRICE)
        )
    with pytest.raises(ValidationError, match="sorted"):
        _descriptor(
            supported_event_kinds=(ReplayInputKind.TRADE, ReplayInputKind.MARK_PRICE)
        )


def test_descriptor_model_copy_tampering_is_rejected_by_fingerprint() -> None:
    descriptor = _descriptor().model_copy(update={"stack_id": " "})

    with pytest.raises(ValidationError, match="non-empty"):
        build_replay_decision_stack_fingerprint(descriptor)


def test_stack_fingerprint_is_stable_and_changes_with_descriptor_fields() -> None:
    base = _descriptor()
    assert build_replay_decision_stack_fingerprint(base) == (
        build_replay_decision_stack_fingerprint(_descriptor())
    )
    variants = (
        _descriptor(stack_id="stack-2"),
        _descriptor(stack_version="2"),
        _descriptor(bot_id=BotId("bot-2")),
        _descriptor(source_kind=DecisionSourceKind.RULE_BASED),
        _descriptor(supported_event_kinds=(ReplayInputKind.TRADE,)),
    )
    assert all(
        build_replay_decision_stack_fingerprint(variant)
        != build_replay_decision_stack_fingerprint(base)
        for variant in variants
    )


def test_decision_id_is_deterministic_delimiter_safe_and_strict() -> None:
    descriptor = _descriptor()
    fp = build_replay_decision_stack_fingerprint(descriptor)
    first = build_replay_decision_intent_id(
        run_id="a",
        event_order_index=1,
        event_id="2:b",
        decision_stack_fingerprint=fp,
        decision_index=0,
    )
    second = build_replay_decision_intent_id(
        run_id="a:1",
        event_order_index=2,
        event_id="b",
        decision_stack_fingerprint=fp,
        decision_index=0,
    )
    assert first != second
    assert first == build_replay_decision_intent_id(
        run_id="a",
        event_order_index=1,
        event_id="2:b",
        decision_stack_fingerprint=fp,
        decision_index=0,
    )

    for kwargs in (
        {"event_order_index": True},
        {"event_order_index": "1"},
        {"event_order_index": 1.0},
        {"decision_index": True},
        {"decision_index": "0"},
        {"decision_index": 0.0},
    ):
        call_kwargs = {
            "run_id": "run-1",
            "event_order_index": 0,
            "event_id": "event-1",
            "decision_stack_fingerprint": fp,
            "decision_index": 0,
        }
        call_kwargs.update(kwargs)
        with pytest.raises(ValueError):
            build_replay_decision_intent_id(**call_kwargs)


def test_valid_decision_intent_and_no_trade_envelopes() -> None:
    descriptor = _descriptor()
    intent = _intent(descriptor)
    no_trade = _no_trade(descriptor)

    assert ReplayDecisionOutputEnvelope(
        run_id="run-1",
        event_id="event-1",
        event_order_index=0,
        event_time=_utc(),
        event_kind=ReplayInputKind.MARK_PRICE,
        stack_descriptor=descriptor,
        decision_index=0,
        decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
        decision_intent=intent,
    ).decision_intent == intent
    assert ReplayDecisionOutputEnvelope(
        run_id="run-1",
        event_id="event-1",
        event_order_index=0,
        event_time=_utc(),
        event_kind=ReplayInputKind.MARK_PRICE,
        stack_descriptor=descriptor,
        decision_index=0,
        decision_kind=ReplayDecisionOutputKind.NO_TRADE_DECISION,
        no_trade_decision=no_trade,
    ).no_trade_decision == no_trade


def test_envelope_rejects_ambiguous_kind_and_identity_mismatches() -> None:
    descriptor = _descriptor()
    intent = _intent(descriptor)
    base = {
        "run_id": "run-1",
        "event_id": "event-1",
        "event_order_index": 0,
        "event_time": _utc(),
        "event_kind": ReplayInputKind.MARK_PRICE,
        "stack_descriptor": descriptor,
        "decision_index": 0,
    }

    with pytest.raises(ValidationError, match="exactly one"):
        ReplayDecisionOutputEnvelope(
            **base,
            decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
        )
    with pytest.raises(ValidationError, match="exactly one"):
        ReplayDecisionOutputEnvelope(
            **base,
            decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
            decision_intent=intent,
            no_trade_decision=_no_trade(descriptor),
        )
    with pytest.raises(ValidationError, match="decision_kind"):
        ReplayDecisionOutputEnvelope(
            **base,
            decision_kind=ReplayDecisionOutputKind.NO_TRADE_DECISION,
            decision_intent=intent,
        )
    with pytest.raises(ValidationError, match="deterministic"):
        ReplayDecisionOutputEnvelope(
            **base,
            decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
            decision_intent=_intent(
                descriptor,
                decision_id=DecisionIntentId("not-deterministic"),
            ),
        )


@pytest.mark.parametrize(
    ("intent_kwargs", "match"),
    (
        ({"bot_id": BotId("other")}, "bot_id"),
        ({"source_kind": DecisionSourceKind.RULE_BASED}, "source_kind"),
        ({"source_id": "other"}, "source_id"),
        ({"created_at": _utc() + timedelta(seconds=1)}, "created_at"),
        ({"status": DecisionIntentStatus.CANCELLED}, "PROPOSED"),
    ),
)
def test_envelope_rejects_invalid_decision_binding(
    intent_kwargs: dict[str, object],
    match: str,
) -> None:
    descriptor = _descriptor()
    with pytest.raises(ValidationError, match=match):
        ReplayDecisionOutputEnvelope(
            run_id="run-1",
            event_id="event-1",
            event_order_index=0,
            event_time=_utc(),
            event_kind=ReplayInputKind.MARK_PRICE,
            stack_descriptor=descriptor,
            decision_index=0,
            decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
            decision_intent=_intent(descriptor, **intent_kwargs),
        )


def test_envelope_rejects_unsupported_event_and_bad_schema_version() -> None:
    descriptor = _descriptor(supported_event_kinds=(ReplayInputKind.TRADE,))

    with pytest.raises(ValidationError, match="supported"):
        ReplayDecisionOutputEnvelope(
            run_id="run-1",
            event_id="event-1",
            event_order_index=0,
            event_time=_utc(),
            event_kind=ReplayInputKind.MARK_PRICE,
            stack_descriptor=descriptor,
            decision_index=0,
            decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
            decision_intent=_intent(descriptor),
        )
    with pytest.raises(ValidationError, match="schema_version"):
        ReplayDecisionOutputEnvelope(
            schema_version=True,
            run_id="run-1",
            event_id="event-1",
            event_order_index=0,
            event_time=_utc(),
            event_kind=ReplayInputKind.TRADE,
            stack_descriptor=descriptor,
            decision_index=0,
            decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
            decision_intent=_intent(descriptor),
        )


def test_margin_leverage_confidence_remain_optional() -> None:
    descriptor = _descriptor()
    intent = DecisionIntent(
        decision_intent_id=_decision_id(descriptor),
        bot_id=descriptor.bot_id,
        instrument="BTC/USDT",
        side=TradeSide.SHORT,
        proposed_action=ProposedAction.OPEN_POSITION,
        source_kind=descriptor.source_kind,
        source_id=descriptor.stack_id,
        created_at=_utc(),
    )

    envelope = ReplayDecisionOutputEnvelope(
        run_id="run-1",
        event_id="event-1",
        event_order_index=0,
        event_time=_utc(),
        event_kind=ReplayInputKind.MARK_PRICE,
        stack_descriptor=descriptor,
        decision_index=0,
        decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
        decision_intent=intent,
    )

    assert envelope.decision_intent is not None
    assert envelope.decision_intent.proposed_margin is None
    assert envelope.decision_intent.proposed_leverage is None
    assert envelope.decision_intent.confidence is None


@pytest.mark.parametrize("asset", ["USDT", "USDC"])
def test_decision_intent_with_proposed_margin_enters_envelope(asset: str) -> None:
    descriptor = _descriptor()
    intent = DecisionIntent(
        decision_intent_id=_decision_id(descriptor),
        bot_id=descriptor.bot_id,
        instrument="BTCUSD",
        side=TradeSide.LONG,
        proposed_action=ProposedAction.OPEN_POSITION,
        source_kind=descriptor.source_kind,
        source_id=descriptor.stack_id,
        created_at=_utc(),
        proposed_margin=AssetAmount(asset=asset, amount="100.0000"),
        proposed_leverage="3",
        confidence="0.7",
    )

    envelope = ReplayDecisionOutputEnvelope(
        run_id="run-1",
        event_id="event-1",
        event_order_index=0,
        event_time=_utc(),
        event_kind=ReplayInputKind.MARK_PRICE,
        stack_descriptor=descriptor,
        decision_index=0,
        decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
        decision_intent=intent,
    )

    assert envelope.decision_intent is not None
    assert str(envelope.decision_intent.instrument) == "BTC/USD"
    assert envelope.decision_intent.proposed_margin == AssetAmount(
        asset=asset,
        amount="100.0000",
    )


@pytest.mark.parametrize(
    "proposed_margin",
    (
        {"asset": {"value": "bad!"}, "amount": "100"},
        {"asset": {"value": "USDT"}, "amount": "-1"},
        {"asset": {"value": "USDT"}, "amount": 1.5},
    ),
)
def test_decision_intent_margin_tampering_rejected_in_envelope(
    proposed_margin: object,
) -> None:
    descriptor = _descriptor()
    intent = _intent(descriptor).model_copy(update={"proposed_margin": proposed_margin})

    with pytest.raises(ValidationError):
        ReplayDecisionOutputEnvelope(
            run_id="run-1",
            event_id="event-1",
            event_order_index=0,
            event_time=_utc(),
            event_kind=ReplayInputKind.MARK_PRICE,
            stack_descriptor=descriptor,
            decision_index=0,
            decision_kind=ReplayDecisionOutputKind.DECISION_INTENT,
            decision_intent=intent,
        )
