from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
    RejectedCandidate,
    TradeSide,
)
from futures_bot.domain.ids import BotId, CandidateId, DecisionIntentId


def _created_at() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _intent(source_kind: DecisionSourceKind = DecisionSourceKind.ML_MODEL) -> DecisionIntent:
    return DecisionIntent(
        decision_intent_id=DecisionIntentId("intent-1"),
        bot_id=BotId("bot-1"),
        instrument="BTC/USDT",
        side=TradeSide.LONG,
        proposed_action=ProposedAction.OPEN_POSITION,
        source_kind=source_kind,
        source_id="model-1",
        created_at=_created_at(),
        valid_until=_created_at() + timedelta(minutes=5),
        proposed_margin=AssetAmount(asset="USDT", amount="25"),
        proposed_leverage="3",
        confidence="0.7",
        reason_tags=("breakout",),
    )


def test_decision_intent_accepts_ml_neural_and_llm_sources() -> None:
    assert _intent(DecisionSourceKind.ML_MODEL).source_kind is DecisionSourceKind.ML_MODEL
    assert _intent(DecisionSourceKind.NEURAL_MODEL).source_kind is DecisionSourceKind.NEURAL_MODEL
    assert _intent(DecisionSourceKind.LLM).source_kind is DecisionSourceKind.LLM


def test_decision_intent_rejects_naive_datetimes() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        DecisionIntent(
            decision_intent_id=DecisionIntentId("intent-1"),
            bot_id=BotId("bot-1"),
            instrument="BTC/USDT",
            side=TradeSide.LONG,
            proposed_action=ProposedAction.OPEN_POSITION,
            source_kind=DecisionSourceKind.ML_MODEL,
            source_id="model-1",
            created_at=datetime(2026, 1, 1),
        )


def test_decision_intent_rejects_expired_valid_until() -> None:
    with pytest.raises(ValidationError, match="valid_until"):
        DecisionIntent(
            decision_intent_id=DecisionIntentId("intent-1"),
            bot_id=BotId("bot-1"),
            instrument="BTC/USDT",
            side=TradeSide.LONG,
            proposed_action=ProposedAction.OPEN_POSITION,
            source_kind=DecisionSourceKind.ML_MODEL,
            source_id="model-1",
            created_at=_created_at(),
            valid_until=_created_at(),
        )


@pytest.mark.parametrize("field", ["confidence", "proposed_leverage"])
def test_decision_intent_rejects_float_confidence_and_leverage(field: str) -> None:
    kwargs = {
        "decision_intent_id": DecisionIntentId("intent-1"),
        "bot_id": BotId("bot-1"),
        "instrument": "BTC/USDT",
        "side": TradeSide.LONG,
        "proposed_action": ProposedAction.OPEN_POSITION,
        "source_kind": DecisionSourceKind.ML_MODEL,
        "source_id": "model-1",
        "created_at": _created_at(),
        field: 0.5,
    }

    with pytest.raises(ValidationError, match="float input"):
        DecisionIntent(**kwargs)


def test_decision_intent_validates_reason_tags_and_defaults_status() -> None:
    intent = _intent()

    assert intent.status is DecisionIntentStatus.PROPOSED
    assert intent.proposed_leverage == Decimal("3")

    with pytest.raises(ValidationError, match="reason_tags"):
        DecisionIntent(
            decision_intent_id=DecisionIntentId("intent-1"),
            bot_id=BotId("bot-1"),
            instrument="BTC/USDT",
            side=TradeSide.LONG,
            proposed_action=ProposedAction.OPEN_POSITION,
            source_kind=DecisionSourceKind.ML_MODEL,
            source_id="model-1",
            created_at=_created_at(),
            reason_tags=("x", "x"),
        )


def test_no_trade_decision_requires_reasons_and_validates_confidence() -> None:
    no_trade = NoTradeDecision(
        decision_intent_id=DecisionIntentId("intent-1"),
        bot_id=BotId("bot-1"),
        instrument="BTC/USDT",
        source_kind=DecisionSourceKind.CONTROL_BASELINE,
        source_id="baseline",
        created_at=_created_at(),
        reasons=(NoTradeReasonKind.CONTROL_BASELINE_NO_TRADE,),
        confidence="0.5",
    )

    assert no_trade.confidence == Decimal("0.5")

    with pytest.raises(ValidationError, match="at least one reason"):
        NoTradeDecision(
            decision_intent_id=DecisionIntentId("intent-1"),
            bot_id=BotId("bot-1"),
            source_kind=DecisionSourceKind.CONTROL_BASELINE,
            source_id="baseline",
            created_at=_created_at(),
            reasons=(),
        )


def _base_intent_kwargs() -> dict:
    return {
        "decision_intent_id": DecisionIntentId("intent-bad"),
        "bot_id": BotId("bot-1"),
        "instrument": "BTC/USDT",
        "side": TradeSide.LONG,
        "proposed_action": ProposedAction.OPEN_POSITION,
        "source_kind": DecisionSourceKind.ML_MODEL,
        "source_id": "model-1",
        "created_at": _created_at(),
    }


def test_decision_intent_invalid_instrument_type_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        DecisionIntent(**{**_base_intent_kwargs(), "instrument": 123})  # type: ignore[arg-type]


def test_no_trade_decision_invalid_instrument_type_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        NoTradeDecision(
            decision_intent_id=DecisionIntentId("intent-bad"),
            bot_id=BotId("bot-1"),
            instrument=123,  # type: ignore[arg-type]
            source_kind=DecisionSourceKind.CONTROL_BASELINE,
            source_id="baseline",
            created_at=_created_at(),
            reasons=(NoTradeReasonKind.CONTROL_BASELINE_NO_TRADE,),
        )


@pytest.mark.parametrize("bad", ["abc", "", "not-a-number"])
def test_decision_intent_confidence_invalid_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        DecisionIntent(**_base_intent_kwargs(), confidence=bad)


@pytest.mark.parametrize("bad", ["abc", "", "not-a-number"])
def test_decision_intent_leverage_invalid_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        DecisionIntent(**_base_intent_kwargs(), proposed_leverage=bad)


@pytest.mark.parametrize("bad", ["abc", "", "not-a-number"])
def test_no_trade_decision_confidence_invalid_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        NoTradeDecision(
            decision_intent_id=DecisionIntentId("intent-bad"),
            bot_id=BotId("bot-1"),
            source_kind=DecisionSourceKind.CONTROL_BASELINE,
            source_id="baseline",
            created_at=_created_at(),
            reasons=(NoTradeReasonKind.CONTROL_BASELINE_NO_TRADE,),
            confidence=bad,
        )


def test_rejected_candidate_validates_text_and_timestamp() -> None:
    candidate = RejectedCandidate(
        candidate_id=CandidateId("candidate-1"),
        bot_id=BotId("bot-1"),
        instrument="BTC/USDT",
        rejected_by="universe-policy",
        reason="not eligible",
        created_at=_created_at(),
    )

    assert str(candidate.candidate_id) == "candidate-1"

    with pytest.raises(ValidationError, match="timezone-aware"):
        RejectedCandidate(
            candidate_id=CandidateId("candidate-1"),
            bot_id=BotId("bot-1"),
            instrument="BTC/USDT",
            rejected_by="universe-policy",
            reason="not eligible",
            created_at=datetime(2026, 1, 1),
        )
