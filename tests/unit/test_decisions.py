from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.assets import AssetAmount, AssetSymbol, StableCollateralAsset
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


def test_decision_models_normalize_external_instrument_symbols() -> None:
    intent = DecisionIntent(**{**_base_intent_kwargs(), "instrument": "btcusd"})
    no_trade = NoTradeDecision(
        decision_intent_id=DecisionIntentId("intent-no-trade"),
        bot_id=BotId("bot-1"),
        instrument="BTCUSD",
        source_kind=DecisionSourceKind.CONTROL_BASELINE,
        source_id="baseline",
        created_at=_created_at(),
        reasons=(NoTradeReasonKind.CONTROL_BASELINE_NO_TRADE,),
    )
    rejected = RejectedCandidate(
        candidate_id=CandidateId("candidate-1"),
        bot_id=BotId("bot-1"),
        instrument="btc-usd",
        rejected_by="universe-policy",
        reason="not eligible",
        created_at=_created_at(),
    )

    assert str(intent.instrument) == "BTC/USD"
    assert str(no_trade.instrument) == "BTC/USD"
    assert str(rejected.instrument) == "BTC/USD"


def test_decision_models_model_dump_round_trip() -> None:
    intent = _intent()
    no_trade = NoTradeDecision(
        decision_intent_id=DecisionIntentId("intent-no-trade"),
        bot_id=BotId("bot-1"),
        instrument="BTCUSD",
        source_kind=DecisionSourceKind.CONTROL_BASELINE,
        source_id="baseline",
        created_at=_created_at(),
        reasons=(NoTradeReasonKind.CONTROL_BASELINE_NO_TRADE,),
    )
    rejected = RejectedCandidate(
        candidate_id=CandidateId("candidate-1"),
        bot_id=BotId("bot-1"),
        instrument="btc-usd",
        rejected_by="universe-policy",
        reason="not eligible",
        created_at=_created_at(),
    )

    assert DecisionIntent.model_validate(intent.model_dump()) == intent
    assert NoTradeDecision.model_validate(no_trade.model_dump()) == no_trade
    assert RejectedCandidate.model_validate(rejected.model_dump()) == rejected


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


# ---------------------------------------------------------------------------
# DecisionIntent proposed_margin tampering
# ---------------------------------------------------------------------------


def test_decision_intent_accepts_valid_existing_asset_amount() -> None:
    valid_margin = AssetAmount(asset=StableCollateralAsset("USDT"), amount="100.0000")
    intent = DecisionIntent(
        **_base_intent_kwargs(),
        proposed_margin=valid_margin,
    )
    assert intent.proposed_margin == AssetAmount(asset="USDT", amount="100.0000")
    assert isinstance(intent.proposed_margin.asset, AssetSymbol)
    assert isinstance(intent.proposed_margin.amount, Decimal)


def test_decision_intent_accepts_none_margin() -> None:
    intent = DecisionIntent(**_base_intent_kwargs())
    assert intent.proposed_margin is None


def test_decision_intent_rejects_asset_amount_with_corrupted_stable_collateral_asset() -> None:
    bad_stable = StableCollateralAsset("USDT").model_copy(
        update={"symbol": AssetSymbol("USD")}
    )
    bad_amount = AssetAmount(asset="USDT", amount="1").model_copy(
        update={"asset": bad_stable}
    )
    with pytest.raises(ValidationError):
        DecisionIntent(**_base_intent_kwargs(), proposed_margin=bad_amount)


@pytest.mark.parametrize(
    "corrupted_asset",
    [
        "USDT",
        {"value": "USDT"},
    ],
)
def test_decision_intent_rejects_asset_amount_with_non_asset_symbol_asset(
    corrupted_asset: object,
) -> None:
    bad_amount = AssetAmount(asset="USDT", amount="1").model_copy(
        update={"asset": corrupted_asset}
    )
    with pytest.raises(ValidationError):
        DecisionIntent(**_base_intent_kwargs(), proposed_margin=bad_amount)


@pytest.mark.parametrize(
    "corrupted_amount",
    [
        "1",
        1.0,
        Decimal("-1"),
        Decimal("Infinity"),
    ],
)
def test_decision_intent_rejects_asset_amount_with_corrupted_amount(
    corrupted_amount: object,
) -> None:
    bad_amount = AssetAmount(asset="USDT", amount="1").model_copy(
        update={"amount": corrupted_amount}
    )
    with pytest.raises(ValidationError):
        DecisionIntent(**_base_intent_kwargs(), proposed_margin=bad_amount)


def test_decision_intent_rejects_asset_amount_with_invalid_asset_symbol() -> None:
    bad_symbol = AssetSymbol("USDT").model_copy(update={"value": "bad!"})
    bad_amount = AssetAmount(asset="USDT", amount="1").model_copy(
        update={"asset": bad_symbol}
    )
    with pytest.raises(ValidationError):
        DecisionIntent(**_base_intent_kwargs(), proposed_margin=bad_amount)


def test_decision_intent_rejects_non_asset_amount_proposed_margin() -> None:
    with pytest.raises(ValidationError):
        DecisionIntent(**_base_intent_kwargs(), proposed_margin=object())  # type: ignore[arg-type]
