from decimal import Decimal

import pytest
from pydantic import ValidationError

from futures_bot.domain.assets import AssetAmount
from futures_bot.domain.ids import DecisionIntentId
from futures_bot.domain.risk import (
    HardRiskGateDecision,
    HardRiskGateOutcome,
    HardRiskGateRejectReason,
    RiskBehaviorProposal,
    RiskBehaviorSourceKind,
)


def test_risk_behavior_proposal_accepts_ml_rl_and_llm_assisted_sources() -> None:
    for source_kind in (
        RiskBehaviorSourceKind.ML_MODEL,
        RiskBehaviorSourceKind.RL_POLICY,
        RiskBehaviorSourceKind.LLM_ASSISTED,
    ):
        proposal = RiskBehaviorProposal(
            decision_intent_id=DecisionIntentId("intent-1"),
            source_kind=source_kind,
            source_id="risk-model",
            proposed_margin=AssetAmount(asset="USDT", amount="10"),
            proposed_leverage="2",
            confidence="0.7",
        )
        assert proposal.source_kind is source_kind
        assert proposal.proposed_leverage == Decimal("2")


def test_risk_behavior_proposal_rejects_invalid_values() -> None:
    with pytest.raises(ValidationError, match="source_id"):
        RiskBehaviorProposal(
            decision_intent_id=DecisionIntentId("intent-1"),
            source_kind=RiskBehaviorSourceKind.ML_MODEL,
            source_id=" bad ",
        )
    with pytest.raises(ValidationError, match="float input"):
        RiskBehaviorProposal(
            decision_intent_id=DecisionIntentId("intent-1"),
            source_kind=RiskBehaviorSourceKind.ML_MODEL,
            source_id="risk-model",
            confidence=0.5,
        )
    with pytest.raises(ValidationError, match="positive"):
        RiskBehaviorProposal(
            decision_intent_id=DecisionIntentId("intent-1"),
            source_kind=RiskBehaviorSourceKind.ML_MODEL,
            source_id="risk-model",
            proposed_leverage="0",
        )


def test_hard_risk_gate_reject_reasons_are_not_strategy_like() -> None:
    reason_names = {reason.name for reason in HardRiskGateRejectReason}

    for forbidden in (
        "BAD_ALPHA",
        "LOW_CONFIDENCE",
        "STRATEGY_NOT_INTELLIGENT",
        "RSI_OVERBOUGHT",
        "HIGH_VOLATILITY",
        "LOW_MARKET_CAP",
    ):
        assert forbidden not in reason_names


def test_hard_risk_gate_approved_cannot_have_reject_reasons() -> None:
    decision = HardRiskGateDecision(
        decision_intent_id=DecisionIntentId("intent-1"),
        outcome=HardRiskGateOutcome.APPROVED,
        approved_margin=AssetAmount(asset="USDT", amount="10"),
        approved_leverage="2",
    )

    assert decision.approved_leverage == Decimal("2")

    with pytest.raises(ValidationError, match="must not have reject reasons"):
        HardRiskGateDecision(
            decision_intent_id=DecisionIntentId("intent-1"),
            outcome=HardRiskGateOutcome.APPROVED,
            reject_reasons=(HardRiskGateRejectReason.INSUFFICIENT_CAPITAL,),
        )


@pytest.mark.parametrize("bad", ["abc", "", "not-a-number"])
def test_risk_behavior_proposal_confidence_invalid_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        RiskBehaviorProposal(
            decision_intent_id=DecisionIntentId("intent-bad"),
            source_kind=RiskBehaviorSourceKind.ML_MODEL,
            source_id="risk-model",
            confidence=bad,
        )


@pytest.mark.parametrize("bad", ["abc", "", "not-a-number"])
def test_risk_behavior_proposal_leverage_invalid_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        RiskBehaviorProposal(
            decision_intent_id=DecisionIntentId("intent-bad"),
            source_kind=RiskBehaviorSourceKind.ML_MODEL,
            source_id="risk-model",
            proposed_leverage=bad,
        )


@pytest.mark.parametrize("bad", ["abc", "", "not-a-number"])
def test_hard_risk_gate_leverage_invalid_string_raises_validation_error(bad: str) -> None:
    with pytest.raises(ValidationError):
        HardRiskGateDecision(
            decision_intent_id=DecisionIntentId("intent-bad"),
            outcome=HardRiskGateOutcome.APPROVED,
            approved_leverage=bad,
        )


def test_hard_risk_gate_rejected_requires_reject_reasons_and_rejects_duplicates() -> None:
    with pytest.raises(ValidationError, match="requires reject reasons"):
        HardRiskGateDecision(
            decision_intent_id=DecisionIntentId("intent-1"),
            outcome=HardRiskGateOutcome.REJECTED,
        )

    with pytest.raises(ValidationError, match="duplicate"):
        HardRiskGateDecision(
            decision_intent_id=DecisionIntentId("intent-1"),
            outcome=HardRiskGateOutcome.REJECTED,
            reject_reasons=(
                HardRiskGateRejectReason.INSUFFICIENT_CAPITAL,
                HardRiskGateRejectReason.INSUFFICIENT_CAPITAL,
            ),
        )

    rejected = HardRiskGateDecision(
        decision_intent_id=DecisionIntentId("intent-1"),
        outcome=HardRiskGateOutcome.REJECTED,
        reject_reasons=(HardRiskGateRejectReason.INSUFFICIENT_CAPITAL,),
    )

    assert rejected.reject_reasons == (HardRiskGateRejectReason.INSUFFICIENT_CAPITAL,)
