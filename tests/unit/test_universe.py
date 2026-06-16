import pytest
from pydantic import ValidationError

from futures_bot.domain.ids import PolicyId
from futures_bot.domain.market_annotations import (
    MarketAnnotation,
    MarketAnnotationKind,
    MarketAnnotationSet,
)
from futures_bot.domain.policies import UniversePolicyKind
from futures_bot.domain.universe import UniverseEligibilityDecision, UniversePolicySpec


def test_universe_policy_rejects_duplicate_and_conflicting_instruments() -> None:
    with pytest.raises(ValidationError, match="duplicate allowed"):
        UniversePolicySpec(
            policy_id=PolicyId("policy-1"),
            policy_kind=UniversePolicyKind.BOT_RESTRICTED,
            allowed_instruments=("BTC/USDT", "BTC/USDT"),
        )

    with pytest.raises(ValidationError, match="both allowed and blocked"):
        UniversePolicySpec(
            policy_id=PolicyId("policy-1"),
            policy_kind=UniversePolicyKind.BOT_RESTRICTED,
            allowed_instruments=("BTC/USDT",),
            blocked_instruments=("BTC/USDT",),
        )

    with pytest.raises(ValidationError, match="duplicate allowed"):
        UniversePolicySpec(
            policy_id=PolicyId("policy-1"),
            policy_kind=UniversePolicyKind.BOT_RESTRICTED,
            allowed_instruments=("BTCUSD", "BTC/USD"),
        )


def test_universe_policy_rejects_duplicate_and_conflicting_annotations() -> None:
    with pytest.raises(ValidationError, match="duplicate required"):
        UniversePolicySpec(
            policy_id=PolicyId("policy-1"),
            policy_kind=UniversePolicyKind.BOT_RESTRICTED,
            required_annotations=(
                MarketAnnotationKind.HIGH_VOLATILITY,
                MarketAnnotationKind.HIGH_VOLATILITY,
            ),
        )

    with pytest.raises(ValidationError, match="both required and blocked"):
        UniversePolicySpec(
            policy_id=PolicyId("policy-1"),
            policy_kind=UniversePolicyKind.BOT_RESTRICTED,
            required_annotations=(MarketAnnotationKind.HIGH_VOLATILITY,),
            blocked_annotations=(MarketAnnotationKind.HIGH_VOLATILITY,),
        )


def test_single_instrument_requires_exactly_one_allowed_instrument() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        UniversePolicySpec(
            policy_id=PolicyId("policy-1"),
            policy_kind=UniversePolicyKind.SINGLE_INSTRUMENT,
        )

    policy = UniversePolicySpec(
        policy_id=PolicyId("policy-1"),
        policy_kind=UniversePolicyKind.SINGLE_INSTRUMENT,
        allowed_instruments=("SOL/USDC",),
    )

    assert policy.evaluate("SOL/USDC").eligible
    assert not policy.evaluate("BTC/USDT").eligible


def test_universe_policy_normalizes_alternate_external_spellings() -> None:
    policy = UniversePolicySpec(
        policy_id=PolicyId("policy-1"),
        policy_kind=UniversePolicyKind.BOT_RESTRICTED,
        allowed_instruments=("BTCUSD",),
        blocked_instruments=("ETH_USD",),
    )

    assert str(policy.allowed_instruments[0]) == "BTC/USD"
    assert policy.evaluate("btc-usd").eligible
    assert not policy.evaluate("ETH/USD").eligible
    assert not policy.evaluate("BTCUSDT").eligible


def test_research_universe_can_allow_low_cap_high_volatility_markets() -> None:
    annotations = MarketAnnotationSet(
        instrument="DOGE/USDT",
        annotations=(
            MarketAnnotation(
                instrument="DOGE/USDT",
                kind=MarketAnnotationKind.LOW_MARKET_CAP,
                source="scanner",
            ),
            MarketAnnotation(
                instrument="DOGE/USDT",
                kind=MarketAnnotationKind.HIGH_VOLATILITY,
                source="scanner",
            ),
        ),
    )
    policy = UniversePolicySpec(
        policy_id=PolicyId("policy-1"),
        policy_kind=UniversePolicyKind.LOW_CAP_RESEARCH,
        required_annotations=(MarketAnnotationKind.LOW_MARKET_CAP,),
    )

    assert policy.evaluate("DOGE/USDT", annotations).eligible


def test_universe_policy_can_block_annotations_locally() -> None:
    annotations = MarketAnnotationSet(
        instrument="BTC/USDT",
        annotations=(
            MarketAnnotation(
                instrument="BTC/USDT",
                kind=MarketAnnotationKind.FUNDING_UNFAVORABLE,
                source="funding-model",
            ),
        ),
    )
    policy = UniversePolicySpec(
        policy_id=PolicyId("policy-1"),
        policy_kind=UniversePolicyKind.BOT_RESTRICTED,
        blocked_annotations=(MarketAnnotationKind.FUNDING_UNFAVORABLE,),
    )

    decision = policy.evaluate("BTC/USDT", annotations)

    assert not decision.eligible
    assert "blocked annotation" in decision.reason


def test_universe_policy_invalid_instrument_types_raise_validation_error() -> None:
    with pytest.raises(ValidationError):
        UniversePolicySpec(
            policy_id=PolicyId("policy-1"),
            policy_kind=UniversePolicyKind.BOT_RESTRICTED,
            allowed_instruments=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError):
        UniversePolicySpec(
            policy_id=PolicyId("policy-1"),
            policy_kind=UniversePolicyKind.BOT_RESTRICTED,
            allowed_instruments=(object(),),  # type: ignore[arg-type]
        )


def test_universe_policy_rejects_missing_required_annotations() -> None:
    policy = UniversePolicySpec(
        policy_id=PolicyId("policy-1"),
        policy_kind=UniversePolicyKind.HIGH_VOLATILITY_RESEARCH,
        required_annotations=(MarketAnnotationKind.HIGH_VOLATILITY,),
    )

    assert not policy.evaluate("BTC/USDT").eligible


def test_universe_models_model_dump_round_trip() -> None:
    decision = UniverseEligibilityDecision(
        instrument="BTCUSD",
        eligible=True,
        policy_kind=UniversePolicyKind.BOT_RESTRICTED,
        reason="ok",
    )
    policy = UniversePolicySpec(
        policy_id=PolicyId("policy-1"),
        policy_kind=UniversePolicyKind.BOT_RESTRICTED,
        allowed_instruments=("BTCUSD",),
    )

    assert UniverseEligibilityDecision.model_validate(decision.model_dump()) == decision
    assert UniversePolicySpec.model_validate(policy.model_dump()) == policy
