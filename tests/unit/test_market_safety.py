import pytest
from pydantic import ValidationError

from futures_bot.domain.market_safety import MarketSafetyBlockReason, MarketSafetyDecision


def test_market_safety_allow_requires_no_block_reasons() -> None:
    decision = MarketSafetyDecision.allow("BTC/USDT", notes="valid")

    assert decision.allowed
    assert decision.block_reasons == ()

    with pytest.raises(ValidationError, match="must not have block reasons"):
        MarketSafetyDecision(
            instrument="BTC/USDT",
            allowed=True,
            block_reasons=(MarketSafetyBlockReason.UNSAFE_ASSET,),
        )


def test_market_safety_block_requires_reasons_and_rejects_duplicates() -> None:
    decision = MarketSafetyDecision.block(
        "BTC/USDT",
        (MarketSafetyBlockReason.UNSAFE_ASSET, MarketSafetyBlockReason.NON_TRADABLE),
    )

    assert not decision.allowed

    with pytest.raises(ValidationError, match="requires at least one"):
        MarketSafetyDecision(instrument="BTC/USDT", allowed=False)

    with pytest.raises(ValidationError, match="duplicate"):
        MarketSafetyDecision.block(
            "BTC/USDT",
            (MarketSafetyBlockReason.UNSAFE_ASSET, MarketSafetyBlockReason.UNSAFE_ASSET),
        )


def test_market_safety_notes_must_be_trimmed() -> None:
    with pytest.raises(ValidationError, match="notes"):
        MarketSafetyDecision.allow("BTC/USDT", notes=" bad ")


def test_market_safety_invalid_instrument_type_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        MarketSafetyDecision.allow(123)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        MarketSafetyDecision.block(123, (MarketSafetyBlockReason.UNSAFE_ASSET,))  # type: ignore[arg-type]


def test_market_safety_reasons_do_not_include_strategy_annotations() -> None:
    reason_names = {reason.name for reason in MarketSafetyBlockReason}

    for forbidden in (
        "RSI_OVERBOUGHT",
        "RSI_OVERSOLD",
        "LOW_MARKET_CAP",
        "HIGH_VOLATILITY",
        "HIGH_SPREAD",
        "RECENT_LISTING",
        "SHITCOIN_LIKE_PROFILE",
        "FUNDING_UNFAVORABLE",
    ):
        assert forbidden not in reason_names
